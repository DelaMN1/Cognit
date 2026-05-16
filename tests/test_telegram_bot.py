from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from cognit import CognitHandler
from cognit.ai.fallback import FallbackAnalyzer
from cognit.ai.schemas import AIAnalysis
from cognit.capture.event import LogEvent
from cognit.config import CognitConfig
from cognit.embeddings import LocalHashEmbedder, build_embedding_text
from cognit.exceptions import CognitAIError
from cognit.integrations.telegram import split_telegram_message
from cognit.integrations.telegram_bot import NO_CONTEXT_MESSAGE, TelegramFollowUpBot, USAGE_MESSAGE
from cognit.storage.models import StoredIncident
from cognit.storage.sqlite_store import SQLiteStore


def _event(
    incident_id: str,
    fingerprint: str,
    *,
    message: str,
    app_name: str = "demo",
    environment: str = "test",
) -> LogEvent:
    return LogEvent(
        incident_id=incident_id,
        app_name=app_name,
        environment=environment,
        level="ERROR",
        levelno=40,
        message=message,
        logger_name="demo",
        timestamp="2026-05-14T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="app",
        function="explode",
        line_number=10,
        process_id=123,
        process_name="MainProcess",
        thread_id=456,
        thread_name="MainThread",
        exception_type="RuntimeError",
        exception_message="redis://:secret@localhost:6379/0",
        traceback="Traceback with password=swordfish",
        fingerprint=fingerprint,
    )


def test_valid_cognit_command(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    embedder = LocalHashEmbedder(dimensions=256)
    primary = _event(
        "cog_20260509_143522_a8f29c",
        "fp-primary",
        message="orders database timeout for admin@example.com",
    )
    similar = _event(
        "cog_related",
        "fp-related",
        message="orders database timeout while syncing invoices",
    )
    store.save_incident(primary)
    store.save_incident(similar)
    similar_text = build_embedding_text(similar)
    store.save_embedding(similar.incident_id, embedder.embed(similar_text), embedder.text_hash(similar_text))
    store.save_conversation_message(primary.incident_id, "assistant", "Previous note for admin@example.com")

    analyzer = CapturingFollowUpAnalyzer(
        answer="The incident most likely points to a database timeout in the orders flow for admin@example.com."
    )
    telegram = FakeTelegramClient(
        updates=[
            {
                "update_id": 10,
                "message": {
                    "chat": {"id": 12345},
                    "text": "/cognit cog_20260509_143522_a8f29c Is password=swordfish related?",
                },
            }
        ]
    )
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=analyzer,
        fallback_analyzer=FallbackAnalyzer(),
        embedder=embedder,
    )

    next_offset = bot.process_updates_once()

    assert next_offset == 11
    assert telegram.sent_chunks[0][0] == "12345"
    assert "Cognit Follow-up" in telegram.sent_texts[0]
    assert "\n\nAnswer\n" in telegram.sent_texts[0]
    assert "\n\nWhy this is likely\n" in telegram.sent_texts[0]
    assert "\n\nWhat to inspect next\n1. " in telegram.sent_texts[0]
    assert "\n\nConfidence\n" in telegram.sent_texts[0]
    assert analyzer.last_incident_id == primary.incident_id
    assert analyzer.last_question == "Is password=[REDACTED_PASSWORD] related?"
    assert analyzer.last_similar_ids == ["cog_related"]
    assert analyzer.last_history_contents == ["Previous note for [REDACTED_EMAIL]"]
    assert "swordfish" not in telegram.sent_texts[0]
    assert "admin@example.com" not in telegram.sent_texts[0]
    assert "[REDACTED_EMAIL]" in telegram.sent_texts[0]
    assert store.get_active_incident("12345") == primary.incident_id


def test_cognit_with_no_args_replies_with_usage():
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="fallback"),
        store=None,
        telegram_client=telegram,
        analyzer=None,
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit"}})

    assert telegram.sent_texts == [USAGE_MESSAGE]


def test_cognit_with_incident_but_no_question_replies_with_usage():
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="fallback"),
        store=None,
        telegram_client=telegram,
        analyzer=None,
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit cog_123"}})

    assert telegram.sent_texts == [USAGE_MESSAGE]


def test_unknown_incident_id_replies_clearly(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="fallback"),
        store=store,
        telegram_client=telegram,
        analyzer=None,
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit cog_missing What happened?"}})

    assert telegram.sent_texts == ["Incident cog_missing was not found."]


def test_plain_text_message_without_context_returns_guidance(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="fallback"),
        store=store,
        telegram_client=telegram,
        analyzer=None,
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "hello there"}})

    assert telegram.sent_texts == [NO_CONTEXT_MESSAGE]


def test_natural_follow_up_uses_active_chat_context(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event("cog_natural", "fp-natural", message="orders timeout")
    store.save_incident(incident)
    store.set_active_incident("12345", "cog_natural", ttl_seconds=1800)
    telegram = FakeTelegramClient()
    analyzer = CapturingFollowUpAnalyzer(answer="Look at the orders database path.")
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=analyzer,
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "What changed before this?"}})
    history = store.get_conversation("cog_natural", limit=10)

    assert analyzer.last_incident_id == "cog_natural"
    assert analyzer.last_question == "What changed before this?"
    assert [item.source for item in history][-2:] == ["natural", "natural"]
    assert "Cognit Follow-up" in telegram.sent_texts[0]


def test_follow_up_limits_similar_incidents_and_conversation_history(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    embedder = LocalHashEmbedder(dimensions=256)
    primary = _event("cog_limit", "fp-limit", message="orders timeout")
    store.save_incident(primary)
    for index in range(4):
        similar = _event(f"cog_sim_{index}", f"fp-sim-{index}", message=f"orders timeout {index}")
        store.save_incident(similar)
        similar_text = build_embedding_text(similar)
        store.save_embedding(similar.incident_id, embedder.embed(similar_text), embedder.text_hash(similar_text))
    for index in range(6):
        role = "user" if index % 2 == 0 else "assistant"
        store.save_conversation_message(primary.incident_id, role, f"history {index}", source="natural")

    telegram = FakeTelegramClient()
    analyzer = CapturingFollowUpAnalyzer(answer="Investigate the timeout path.")
    bot = TelegramFollowUpBot(
        config=CognitConfig(
            ai_provider="gemini",
            max_conversation_history_messages=4,
            max_similar_incidents_for_followup=2,
        ),
        store=store,
        telegram_client=telegram,
        analyzer=analyzer,
        fallback_analyzer=FallbackAnalyzer(),
        embedder=embedder,
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit cog_limit What caused this?"}})

    assert len(analyzer.last_similar_ids) == 2
    assert len(analyzer.last_history_contents) == 4
    assert analyzer.last_history_contents == ["history 2", "history 3", "history 4", "history 5"]


def test_alert_send_sets_active_incident_and_first_plain_text_follow_up_works(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    telegram = FakeTelegramClient(
        updates=[
            {
                "update_id": 1,
                "message": {
                    "chat": {"id": 12345},
                    "text": "What caused this?",
                },
            }
        ]
    )
    logger = logging.getLogger("cognit.tests.telegram_bot.integration")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    handler = CognitHandler(
        app_name="demo",
        environment="test",
        config=CognitConfig(enable_capture=True, telegram_chat_id="12345"),
        store=store,
        analyzer=AlertAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
        telegram_client=telegram,
    )
    logger.addHandler(handler)

    try:
        raise ValueError('invalid literal for int() with base 10: "GHS 250"')
    except ValueError:
        logger.exception("Manual follow-up test: payment amount parsing failed")

    incident = store.list_recent_incidents(limit=1)[0]
    context = store.get_chat_context("12345")
    assert context is not None
    assert context.chat_id == "12345"
    assert context.active_incident_id == incident.incident_id

    analyzer = CapturingFollowUpAnalyzer(
        answer='The amount value was "GHS 250", and the code attempted int("GHS 250"), causing a ValueError.'
    )
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=analyzer,
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    next_offset = bot.process_updates_once()

    assert next_offset == 2
    assert analyzer.last_incident_id == incident.incident_id
    assert analyzer.last_question == "What caused this?"
    assert "int(\"GHS 250\")" in telegram.sent_texts[-1]


def test_current_command_shows_remaining_ttl(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event("cog_current", "fp-current", message="Manual follow-up test")
    store.save_incident(incident)
    base_time = datetime(2026, 5, 14, 13, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(store, "_utc_now", lambda: base_time)
    store.set_active_incident("12345", "cog_current", ttl_seconds=1500)
    monkeypatch.setattr("cognit.integrations.telegram_bot.utc_now", lambda: base_time + timedelta(minutes=1))

    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="fallback"),
        store=store,
        telegram_client=telegram,
        analyzer=None,
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/current"}})

    assert telegram.sent_texts == [
        "Active incident: cog_current\nManual follow-up test\nExpires: in 24 minutes\n\nUse /clear to reset, or just reply with your question."
    ]


def test_clear_command_resets_active_chat_context(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    store.set_active_incident("12345", "cog_clear", ttl_seconds=1800)
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="fallback"),
        store=store,
        telegram_client=telegram,
        analyzer=None,
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/clear"}})

    assert telegram.sent_texts == ["Active incident cleared for this chat."]
    assert store.get_active_incident("12345") is None


def test_ai_failure_returns_fallback_response(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event("cog_fail", "fp-fail", message="cache timeout for admin@example.com")
    store.save_incident(incident)
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=FailingFollowUpAnalyzer(),
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit cog_fail What caused this?"}})

    assert "Cognit Follow-up" in telegram.sent_texts[0]
    assert "\nAnswer\n" in telegram.sent_texts[0]
    assert "\nWhy this is likely\n" in telegram.sent_texts[0]
    assert "\nWhat to inspect next\n1. " in telegram.sent_texts[0]
    assert "\nConfidence\n" in telegram.sent_texts[0]
    assert "admin@example.com" not in telegram.sent_texts[0]


def test_rate_limited_ai_returns_question_specific_fallback(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event("cog_rate", "fp-rate", message='amount "GHS 250" failed')
    store.save_incident(incident)
    store.save_ai_analysis(
        incident.incident_id,
        AIAnalysis(
            summary="Payment parsing failure",
            likely_cause='The amount value was "GHS 250", and the code attempted int("GHS 250"), causing a ValueError.',
            severity="high",
            affected_area="payments",
            suggested_steps=["Check payment parsing"],
            possible_fix=None,
            similar_incidents_summary=None,
            follow_up_questions=[],
        ),
    )
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=RateLimitedFollowUpAnalyzer(),
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit cog_rate What caused this?"}})

    reply = telegram.sent_texts[-1]
    assert 'The amount value was "GHS 250"' in reply
    assert "stored analysis points" not in reply.lower()


def test_fallback_follow_up_changes_based_on_question(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event(
        "cog_amount",
        "fp-amount",
        message='payment parser rejected amount "GHS 250" for admin@example.com',
    )
    store.save_incident(incident)
    store.save_ai_analysis(
        incident.incident_id,
        AIAnalysis(
            summary="Payment parsing failure",
            likely_cause='The amount value was "GHS 250", and the code attempted int("GHS 250"), causing a ValueError.',
            severity="high",
            affected_area="payments",
            suggested_steps=[
                "Check the payment amount parsing and validation code around manual_bot_test.py line 42.",
                "Confirm whether currency-formatted strings are being passed into int().",
                "Review upstream normalization before amount conversion.",
            ],
            possible_fix=None,
            similar_incidents_summary=None,
            follow_up_questions=[],
        ),
    )
    store.set_active_incident("12345", incident.incident_id, ttl_seconds=1800)
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=FailingFollowUpAnalyzer(),
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "What caused this?"}})
    cause_reply = telegram.sent_texts[-1]

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "What should I inspect first?"}})
    inspect_reply = telegram.sent_texts[-1]

    assert cause_reply != inspect_reply
    assert 'The amount value was "GHS 250"' in cause_reply
    assert "Check the payment amount parsing and validation code around manual_bot_test.py line 42." in inspect_reply


def test_sensitive_follow_up_explains_redaction_without_exposing_secrets(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event(
        "cog_sensitive",
        "fp-sensitive",
        message="password=swordfish email=admin@example.com token=abc123",
    )
    store.save_incident(incident)
    store.set_active_incident("12345", incident.incident_id, ttl_seconds=1800)
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=FailingFollowUpAnalyzer(),
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "Was any sensitive data exposed?"}})

    reply = telegram.sent_texts[-1]
    assert "redacted" in reply.lower()
    assert "[REDACTED_" in reply
    assert "swordfish" not in reply
    assert "admin@example.com" not in reply
    assert "abc123" not in reply


def test_conversation_is_saved_for_user_and_ai(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event("cog_conv", "fp-conv", message="worker crashed")
    store.save_incident(incident)
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=CapturingFollowUpAnalyzer(answer="Check worker memory usage."),
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit cog_conv Is password=swordfish involved?"}})
    history = store.get_conversation("cog_conv", limit=10)

    assert [item.role for item in history][-2:] == ["user", "assistant"]
    assert history[-2].content == "Is password=[REDACTED_PASSWORD] involved?"
    assert "Cognit Follow-up" in history[-1].content
    assert "Check worker memory usage." in history[-1].content
    assert [item.source for item in history][-2:] == ["explicit", "explicit"]


def test_long_response_is_split_safely(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event("cog_long", "fp-long", message="database timeout")
    store.save_incident(incident)
    telegram = FakeTelegramClient(max_chars=80)
    long_answer = " ".join(["investigate"] * 120)
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=CapturingFollowUpAnalyzer(answer=long_answer),
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit cog_long What should I inspect?"}})

    chunks = telegram.sent_chunks[0][1]
    assert len(chunks) > 1
    assert " ".join(chunks).split() == telegram.sent_texts[0].split()


def test_follow_up_redacts_before_truncation(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event("cog_truncate", "fp-truncate", message="worker crashed")
    store.save_incident(incident)
    telegram = FakeTelegramClient()
    analyzer = CapturingFollowUpAnalyzer(answer="Investigate the worker crash.")
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=analyzer,
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
        max_followup_chars=18,
    )

    bot.handle_update(
        {
            "message": {
                "chat": {"id": 12345},
                "text": "/cognit cog_truncate prefix password=swordfish suffix",
            }
        }
    )

    assert "swordfish" not in analyzer.last_question
    assert "[REDACTED_PASSWORD]" in analyzer.last_question
    assert analyzer.last_question.endswith("[TRUNCATED]")


def test_explicit_cognit_command_still_works_after_plain_text_routing_changes(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event("cog_explicit", "fp-explicit", message="worker crashed")
    store.save_incident(incident)
    telegram = FakeTelegramClient()
    analyzer = CapturingFollowUpAnalyzer(answer="Check the worker crash path.")
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=analyzer,
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit cog_explicit What should I inspect first?"}})

    assert analyzer.last_incident_id == "cog_explicit"
    assert analyzer.last_question == "What should I inspect first?"
    assert "Cognit Follow-up" in telegram.sent_texts[-1]


def test_manual_test_incident_produces_useful_concise_explanation(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    incident = _event("cog_manual", "fp-manual", message="manual follow-up test triggered")
    store.save_incident(incident)
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="gemini"),
        store=store,
        telegram_client=telegram,
        analyzer=CapturingFollowUpAnalyzer(answer="The likely cause of this incident is a manual follow-up test."),
        fallback_analyzer=FallbackAnalyzer(),
        embedder=LocalHashEmbedder(dimensions=256),
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "/cognit cog_manual What caused this?"}})

    assert "manual test" in telegram.sent_texts[0].lower()
    assert "unexpected production failure" in telegram.sent_texts[0].lower()
    assert len(telegram.sent_texts[0]) < 1200


@dataclass
class CapturingFollowUpAnalyzer:
    answer: str
    last_incident_id: str | None = None
    last_question: str | None = None
    last_similar_ids: list[str] = field(default_factory=list)
    last_history_contents: list[str] = field(default_factory=list)

    def answer_follow_up(
        self,
        incident: StoredIncident,
        question: str,
        *,
        similar_incidents=None,
        conversation_history=None,
    ) -> str:
        self.last_incident_id = incident.incident_id
        self.last_question = question
        self.last_similar_ids = [item.incident_id for item in (similar_incidents or [])]
        self.last_history_contents = [item.content for item in (conversation_history or [])]
        return self.answer


class FailingFollowUpAnalyzer:
    def answer_follow_up(
        self,
        incident: StoredIncident,
        question: str,
        *,
        similar_incidents=None,
        conversation_history=None,
    ) -> str:
        del incident, question, similar_incidents, conversation_history
        raise CognitAIError("provider failed")


class RateLimitedFollowUpAnalyzer:
    def answer_follow_up(
        self,
        incident: StoredIncident,
        question: str,
        *,
        similar_incidents=None,
        conversation_history=None,
    ) -> str:
        del incident, question, similar_incidents, conversation_history
        raise CognitAIError("Gemini rate limit exceeded.")


class AlertAnalyzer:
    def analyze(self, event: LogEvent, *, similar_incidents=None):
        del similar_incidents
        return AIAnalysis(
            summary="Alerted incident",
            likely_cause=event.exception_message or event.message,
            severity="high",
            affected_area=event.module,
            suggested_steps=["Inspect logs"],
            possible_fix=None,
            similar_incidents_summary=None,
            follow_up_questions=["What caused this?"],
        )


class FakeTelegramClient:
    def __init__(self, *, updates=None, max_chars: int = 3500) -> None:
        self.updates = list(updates or [])
        self.max_chars = max_chars
        self.sent_texts: list[str] = []
        self.sent_chunks: list[tuple[str, list[str]]] = []

    def get_updates(self, *, offset=None, timeout=30):
        del offset, timeout
        return list(self.updates)

    def send_long_message(self, chat_id: str | None, text: str, max_chars: int = 3500):
        limit = min(max_chars, self.max_chars)
        chunks = split_telegram_message(text, max_chars=limit)
        self.sent_texts.append(text)
        self.sent_chunks.append((str(chat_id), chunks))
        return [str(index) for index, _ in enumerate(chunks, start=1)]
