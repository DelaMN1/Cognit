from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from cognit import CognitHandler
from cognit.ai.schemas import AIAnalysis
from cognit.capture.event import LogEvent
from cognit.config import CognitConfig
from cognit.controls.dedupe import Deduplicator
from cognit.controls.rate_limiter import RateLimiter
from cognit.embeddings import LocalHashEmbedder, SimilarIncidentRetriever, build_embedding_text
from cognit.exceptions import CognitAIError
from cognit.storage.sqlite_store import SQLiteStore


def test_public_import_exposes_handler():
    assert CognitHandler.__name__ == "CognitHandler"


def test_logger_exception_runs_full_pipeline(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    embedder = CapturingEmbedder()
    telegram = FakeTelegramClient()
    analyzer = CapturingAnalyzer()
    retriever = SimilarIncidentRetriever(store, limit=2)

    prior = LogEvent(
        incident_id="cog_prior",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message="orders database timeout",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="app",
        function="explode",
        line_number=10,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="RuntimeError",
        exception_message="database timeout",
        traceback="Traceback...",
        fingerprint="fp-prior",
    )
    store.save_incident(prior)
    prior_text = build_embedding_text(prior)
    store.save_embedding("cog_prior", embedder._local.embed(prior_text), "prior-hash")

    logger = logging.getLogger("cognit.tests.pipeline.full")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    handler = CognitHandler(
        app_name="demo",
        environment="test",
        config=CognitConfig(enable_capture=True),
        store=store,
        deduplicator=Deduplicator(store, dedupe_window_seconds=60),
        rate_limiter=RateLimiter(store, telegram_alert_limit=5, telegram_alert_window_seconds=60),
        analyzer=analyzer,
        embedder=embedder,
        similar_retriever=retriever,
        telegram_client=telegram,
    )
    logger.addHandler(handler)

    try:
        raise RuntimeError("redis://:secret@localhost:6379/0")
    except RuntimeError:
        logger.exception("password=swordfish email=admin@example.com orders database timeout")

    incident = store.list_recent_incidents(limit=1)[0]
    assert handler.get_last_event() is not None
    assert "[REDACTED_PASSWORD]" in incident.message
    assert "[REDACTED_EMAIL]" in incident.message
    assert incident.exception_message == "[REDACTED_DATABASE_URL]"
    assert analyzer.last_event is not None
    assert "[REDACTED_PASSWORD]" in analyzer.last_event.message
    assert "swordfish" not in embedder.last_text
    assert "admin@example.com" not in embedder.last_text
    assert "redis://:secret@localhost:6379/0" not in telegram.messages[0]
    assert analyzer.last_similar_ids == ["cog_prior"]
    assert incident.ai_analysis is not None

    with sqlite3.connect(tmp_path / "cognit.db") as connection:
        telegram_rows = connection.execute(
            "SELECT chat_id, message_id FROM telegram_messages WHERE incident_id = ?",
            (incident.incident_id,),
        ).fetchall()
        alert_rows = connection.execute(
            "SELECT sent, suppressed_reason FROM alert_events WHERE incident_id = ?",
            (incident.incident_id,),
        ).fetchall()
        embedding_rows = connection.execute(
            "SELECT dimensions FROM embeddings WHERE incident_id = ?",
            (incident.incident_id,),
        ).fetchall()

    assert telegram_rows == [("", "msg-1")]
    assert alert_rows == [(1, None)]
    assert embedding_rows


def test_storage_failure_still_uses_fallback_and_telegram():
    telegram = FakeTelegramClient()
    logger = logging.getLogger("cognit.tests.pipeline.storage_failure")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    handler = CognitHandler(
        app_name="demo",
        environment="test",
        config=CognitConfig(enable_capture=True, ai_provider="fallback"),
        store=FailingStore(),
        embedder=CapturingEmbedder(),
        telegram_client=telegram,
    )
    logger.addHandler(handler)

    try:
        raise RuntimeError("database down")
    except RuntimeError:
        logger.exception("request failed")

    assert handler.last_analysis is not None
    assert telegram.messages


def test_ai_failure_uses_fallback_and_still_sends_telegram(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    telegram = FakeTelegramClient()
    logger = logging.getLogger("cognit.tests.pipeline.ai_failure")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    handler = CognitHandler(
        app_name="demo",
        environment="test",
        config=CognitConfig(enable_capture=True),
        store=store,
        analyzer=FailingAnalyzer(),
        embedder=CapturingEmbedder(),
        telegram_client=telegram,
    )
    logger.addHandler(handler)

    try:
        raise RuntimeError("database down")
    except RuntimeError:
        logger.exception("request failed")

    incident = store.list_recent_incidents(limit=1)[0]
    assert incident.ai_analysis is not None
    assert incident.ai_analysis["severity"] == "high"
    assert telegram.messages


def test_telegram_failure_does_not_crash_and_records_alert_event(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    logger = logging.getLogger("cognit.tests.pipeline.telegram_failure")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    handler = CognitHandler(
        app_name="demo",
        environment="test",
        config=CognitConfig(enable_capture=True),
        store=store,
        analyzer=CapturingAnalyzer(),
        embedder=CapturingEmbedder(),
        telegram_client=FailingTelegramClient(),
    )
    logger.addHandler(handler)

    try:
        raise RuntimeError("database down")
    except RuntimeError:
        logger.exception("request failed")

    incident = store.list_recent_incidents(limit=1)[0]
    with sqlite3.connect(tmp_path / "cognit.db") as connection:
        rows = connection.execute(
            "SELECT sent, suppressed_reason FROM alert_events WHERE incident_id = ?",
            (incident.incident_id,),
        ).fetchall()

    assert rows == [(0, "telegram_error")]


def test_dedupe_suppression_skips_second_telegram_send(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    telegram = FakeTelegramClient()
    logger = logging.getLogger("cognit.tests.pipeline.dedupe")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    handler = CognitHandler(
        app_name="demo",
        environment="test",
        config=CognitConfig(enable_capture=True),
        store=store,
        deduplicator=Deduplicator(store, dedupe_window_seconds=60),
        rate_limiter=RateLimiter(store, telegram_alert_limit=5, telegram_alert_window_seconds=60),
        analyzer=CapturingAnalyzer(),
        embedder=CapturingEmbedder(),
        telegram_client=telegram,
    )
    logger.addHandler(handler)

    for _ in range(2):
        try:
            raise RuntimeError("database down")
        except RuntimeError:
            logger.exception("request failed")

    assert len(telegram.messages) == 1
    incidents = store.list_recent_incidents(limit=1)
    assert incidents[0].suppressed_count == 1


def test_rate_limit_suppression_skips_second_telegram_send(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    telegram = FakeTelegramClient()
    logger = logging.getLogger("cognit.tests.pipeline.rate_limit")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    handler = CognitHandler(
        app_name="demo",
        environment="test",
        config=CognitConfig(enable_capture=True, telegram_alert_limit=1),
        store=store,
        deduplicator=Deduplicator(store, dedupe_window_seconds=60),
        rate_limiter=RateLimiter(store, telegram_alert_limit=1, telegram_alert_window_seconds=60),
        analyzer=CapturingAnalyzer(),
        embedder=CapturingEmbedder(),
        telegram_client=telegram,
    )
    logger.addHandler(handler)

    try:
        raise RuntimeError("first down")
    except RuntimeError:
        logger.exception("request failed first")

    try:
        raise ValueError("second down")
    except ValueError:
        logger.exception("request failed second")

    assert len(telegram.messages) == 1
    with sqlite3.connect(tmp_path / "cognit.db") as connection:
        rows = connection.execute(
            "SELECT sent, suppressed_reason FROM alert_events ORDER BY id",
        ).fetchall()
    assert rows[-1] == (0, "rate_limit")


@dataclass
class CapturingAnalyzer:
    last_event: LogEvent | None = None
    last_similar_ids: list[str] | None = None

    def analyze(self, event: LogEvent, *, similar_incidents=None):
        self.last_event = event
        self.last_similar_ids = [incident.incident_id for incident in (similar_incidents or [])]
        return AIAnalysis(
            summary="Handled incident",
            likely_cause=event.exception_message or event.message,
            severity="high",
            affected_area=event.module,
            suggested_steps=["Inspect logs"],
            possible_fix="Retry request",
            similar_incidents_summary=None,
            follow_up_questions=["Did config change?"],
        )


class FailingAnalyzer:
    def analyze(self, event: LogEvent, *, similar_incidents=None):
        del event, similar_incidents
        raise CognitAIError("provider failed")


class CapturingEmbedder:
    def __init__(self) -> None:
        self._local = LocalHashEmbedder(dimensions=256)
        self.last_text = ""

    def embed(self, text: str) -> list[float]:
        self.last_text = text
        return self._local.embed(text)

    def text_hash(self, text: str) -> str:
        return self._local.text_hash(text)


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_long_message(self, chat_id: str | None, text: str, max_chars: int = 3500) -> list[str]:
        del chat_id, max_chars
        self.messages.append(text)
        return [f"msg-{len(self.messages)}"]


class FailingTelegramClient:
    def send_long_message(self, chat_id: str | None, text: str, max_chars: int = 3500) -> list[str]:
        del chat_id, text, max_chars
        raise RuntimeError("telegram down")


class FailingStore:
    def save_incident(self, event):
        del event
        raise RuntimeError("storage down")
