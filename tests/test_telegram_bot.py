from __future__ import annotations

from dataclasses import dataclass, field

from cognit.ai.fallback import FallbackAnalyzer
from cognit.capture.event import LogEvent
from cognit.config import CognitConfig
from cognit.embeddings import LocalHashEmbedder, build_embedding_text
from cognit.exceptions import CognitAIError
from cognit.integrations.telegram import split_telegram_message
from cognit.integrations.telegram_bot import TelegramFollowUpBot, USAGE_MESSAGE
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


def test_non_command_message_is_ignored(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    telegram = FakeTelegramClient()
    bot = TelegramFollowUpBot(
        config=CognitConfig(ai_provider="fallback"),
        store=store,
        telegram_client=telegram,
        analyzer=None,
    )

    bot.handle_update({"message": {"chat": {"id": 12345}, "text": "hello there"}})

    assert telegram.sent_texts == []


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
