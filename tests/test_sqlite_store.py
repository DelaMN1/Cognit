from __future__ import annotations

import re
import sqlite3

from cognit.capture.event import LogEvent
from cognit.storage.sqlite_store import SQLiteStore


def _event(incident_id: str, fingerprint: str) -> LogEvent:
    return LogEvent(
        incident_id=incident_id,
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message=f"message for {incident_id}",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
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
        exception_message="boom",
        traceback="Traceback...",
        fingerprint=fingerprint,
        tags={"service": "api"},
        extra={"request_id": "req-1"},
    )


def test_database_initialization_and_required_indexes(tmp_path):
    db_path = tmp_path / "cognit.db"
    store = SQLiteStore(db_path)

    assert db_path.exists()

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        journal_mode = connection.execute("PRAGMA journal_mode;").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout;").fetchone()[0]

    assert {"incidents", "logs", "embeddings", "telegram_messages", "conversations", "alert_events"} <= tables
    assert {
        "idx_incidents_fingerprint",
        "idx_alert_events_fingerprint",
        "idx_alert_events_channel_created_at",
        "idx_conversations_incident_id",
        "idx_embeddings_incident_id",
        "idx_telegram_messages_incident_id",
    } <= indexes
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000
    assert store.list_recent_incidents() == []


def test_incident_save_retrieval_and_missing_lookup(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    event = _event("cog_1", "fp-1")

    saved = store.save_incident(event)
    loaded = store.get_incident("cog_1")

    assert saved.incident_id == "cog_1"
    assert loaded is not None
    assert loaded.message == event.message
    assert loaded.tags == {"service": "api"}
    assert loaded.extra == {"request_id": "req-1"}
    assert store.get_incident("missing") is None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", loaded.created_at)
    assert loaded.created_at == loaded.updated_at


def test_ai_analysis_embedding_conversation_and_alert_persistence(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    event = _event("cog_2", "fp-2")
    store.save_incident(event)

    store.save_ai_analysis(
        "cog_2",
        {
            "summary": "Failure in database layer",
            "likely_cause": "Connection pool exhausted",
            "severity": "high",
            "affected_area": "orders",
            "suggested_steps": ["Inspect pool metrics"],
            "possible_fix": "Raise pool size",
            "similar_incidents_summary": "Matches prior db spikes",
            "follow_up_questions": ["Was traffic elevated?"],
            "raw_response": '{"ok": true}',
        },
    )
    store.save_embedding("cog_2", [0.1, 0.2, 0.3], "hash-123")
    store.save_conversation_message("cog_2", "user", "What happened?")
    store.save_conversation_message("cog_2", "assistant", "Pool exhaustion is likely.")
    store.save_telegram_message("cog_2", "chat-1", "msg-9")
    store.save_alert_event("fp-2", "cog_2", "telegram", True, None)
    store.save_alert_event("fp-2", "cog_2", "telegram", False, "duplicate")

    loaded = store.get_incident("cog_2")
    conversation = store.get_conversation("cog_2")
    alert_count = store.count_recent_sent_alert_events("telegram", window_seconds=60)

    assert loaded is not None
    assert loaded.ai_analysis is not None
    assert loaded.ai_analysis["severity"] == "high"
    assert loaded.ai_analysis["suggested_steps"] == ["Inspect pool metrics"]
    assert [message.role for message in conversation] == ["user", "assistant"]
    assert alert_count == 1

    with sqlite3.connect(tmp_path / "cognit.db") as connection:
        embedding_row = connection.execute(
            "SELECT dimensions, text_hash FROM embeddings WHERE incident_id = ?",
            ("cog_2",),
        ).fetchone()
        telegram_row = connection.execute(
            "SELECT chat_id, message_id FROM telegram_messages WHERE incident_id = ?",
            ("cog_2",),
        ).fetchone()

    assert embedding_row == (3, "hash-123")
    assert telegram_row == ("chat-1", "msg-9")


def test_recent_lookup_occurrence_and_suppressed_count_updates(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    first = _event("cog_3", "fp-3")
    second = _event("cog_4", "fp-4")
    store.save_incident(first)
    store.save_incident(second)

    recent = store.get_recent_incident_by_fingerprint("fp-3", within_seconds=60)
    assert recent is not None
    assert recent.incident_id == "cog_3"

    store.increment_occurrence("cog_3")
    store.increment_suppressed_count("cog_3")
    updated = store.get_incident("cog_3")
    listed = store.list_recent_incidents(limit=1)

    assert updated is not None
    assert updated.occurrence_count == 2
    assert updated.suppressed_count == 1
    assert listed[0].incident_id == "cog_3"
