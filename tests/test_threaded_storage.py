from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from cognit.capture.event import LogEvent
from cognit.storage.sqlite_store import SQLiteStore


def _event(index: int) -> LogEvent:
    return LogEvent(
        incident_id=f"cog_thread_{index}",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message=f"message {index}",
        logger_name="threaded",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="app",
        function="explode",
        line_number=index,
        process_id=123,
        process_name="MainProcess",
        thread_id=index,
        thread_name=f"Thread-{index}",
        exception_type="RuntimeError",
        exception_message=f"boom {index}",
        traceback="Traceback...",
        fingerprint=f"fp-thread-{index % 3}",
        tags={"service": "api"},
        extra={"index": index},
    )


def test_concurrent_writes_are_safe(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")

    def write(index: int) -> None:
        event = _event(index)
        store.save_incident(event)
        store.save_alert_event(event.fingerprint, event.incident_id, "telegram", True, None)
        store.save_conversation_message(event.incident_id, "user", f"question {index}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(25)))

    incidents = store.list_recent_incidents(limit=30)
    conversation = store.get_conversation("cog_thread_0")

    assert len(incidents) == 25
    assert incidents[0].created_at.endswith("Z")
    assert conversation[0].content == "question 0"
    assert store.count_recent_sent_alert_events("telegram", window_seconds=60) == 25
