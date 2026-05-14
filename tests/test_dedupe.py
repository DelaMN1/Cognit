from __future__ import annotations

import sqlite3

from cognit.capture.event import LogEvent
from cognit.controls.dedupe import Deduplicator
from cognit.storage.sqlite_store import SQLiteStore


def _event(incident_id: str, fingerprint: str) -> LogEvent:
    return LogEvent(
        incident_id=incident_id,
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message="request failed",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="app",
        function="explode",
        line_number=99,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="RuntimeError",
        exception_message="database down",
        traceback="Traceback...",
        fingerprint=fingerprint,
    )


def test_first_incident_is_saved_and_allowed(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    deduplicator = Deduplicator(store, dedupe_window_seconds=60)

    decision = deduplicator.process(_event("cog_1", "fp-a"))

    assert decision.should_send_alert is True
    assert decision.is_duplicate is False
    assert store.get_incident("cog_1") is not None


def test_duplicate_within_window_is_suppressed_and_updates_counts(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    deduplicator = Deduplicator(store, dedupe_window_seconds=60)

    first = deduplicator.process(_event("cog_1", "fp-a"))
    duplicate = deduplicator.process(_event("cog_2", "fp-a"))
    incident = store.get_incident(first.incident_id)

    assert duplicate.should_send_alert is False
    assert duplicate.is_duplicate is True
    assert duplicate.incident_id == first.incident_id
    assert incident is not None
    assert incident.occurrence_count == 2
    assert incident.suppressed_count == 1

    with sqlite3.connect(tmp_path / "cognit.db") as connection:
        row = connection.execute(
            "SELECT sent, suppressed_reason FROM alert_events WHERE incident_id = ?",
            (first.incident_id,),
        ).fetchone()
    assert row == (0, "duplicate")


def test_different_fingerprint_is_not_suppressed(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    deduplicator = Deduplicator(store, dedupe_window_seconds=60)

    first = deduplicator.process(_event("cog_1", "fp-a"))
    second = deduplicator.process(_event("cog_2", "fp-b"))

    assert first.should_send_alert is True
    assert second.should_send_alert is True
    assert second.incident_id == "cog_2"
