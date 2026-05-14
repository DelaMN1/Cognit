from __future__ import annotations

import sqlite3

from cognit.capture.event import LogEvent
from cognit.controls.dedupe import Deduplicator
from cognit.controls.rate_limiter import RateLimiter
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


def test_rate_limit_allows_alerts_under_limit_and_suppresses_above_limit(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    limiter = RateLimiter(store, telegram_alert_limit=2, telegram_alert_window_seconds=60)
    dedupe = Deduplicator(store, dedupe_window_seconds=60)

    first = dedupe.process(_event("cog_1", "fp-a"))
    second = dedupe.process(_event("cog_2", "fp-b"))
    third = dedupe.process(_event("cog_3", "fp-c"))

    first_decision = limiter.consume("fp-a", first.incident_id)
    second_decision = limiter.consume("fp-b", second.incident_id)
    third_decision = limiter.consume("fp-c", third.incident_id)

    assert first_decision.should_send_alert is True
    assert second_decision.should_send_alert is True
    assert third_decision.should_send_alert is False
    assert third_decision.suppressed_reason == "rate_limit"
    assert store.count_recent_sent_alert_events("telegram", 60) == 2

    with sqlite3.connect(tmp_path / "cognit.db") as connection:
        rows = connection.execute(
            "SELECT sent, suppressed_reason FROM alert_events WHERE incident_id = ? ORDER BY id",
            ("cog_3",),
        ).fetchall()
    assert rows == [(0, "rate_limit")]


def test_fresh_limiter_instance_uses_database_backed_counts(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    dedupe = Deduplicator(store, dedupe_window_seconds=60)
    first = dedupe.process(_event("cog_1", "fp-a"))
    RateLimiter(store, telegram_alert_limit=1, telegram_alert_window_seconds=60).consume(
        "fp-a",
        first.incident_id,
    )

    second = dedupe.process(_event("cog_2", "fp-b"))
    fresh_limiter = RateLimiter(store, telegram_alert_limit=1, telegram_alert_window_seconds=60)
    decision = fresh_limiter.consume("fp-b", second.incident_id)

    assert decision.should_send_alert is False
    assert decision.suppressed_reason == "rate_limit"
