from __future__ import annotations

import logging

from cognit import CognitHandler
from cognit.capture.event import LogEvent
from cognit.redaction.redactor import Redactor


def _event(message: str, *, exception_message: str | None = None, traceback: str | None = None) -> LogEvent:
    return LogEvent(
        incident_id="cog_20260513_010203_abcdef",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=logging.ERROR,
        message=message,
        logger_name="demo",
        timestamp="2026-05-13T01:02:03.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="app",
        function="handle",
        line_number=42,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="RuntimeError",
        exception_message=exception_message,
        traceback=traceback,
        fingerprint="fingerprint",
        tags={"owner": "dev@example.com"},
        extra={"token": "Bearer abc.def.ghi", "db": "postgres://user:pass@localhost:5432/app"},
    )


def test_redactor_redacts_default_secret_types():
    redactor = Redactor()
    event = _event(
        (
            "email admin@example.com "
            "phone +1 (555) 123-4567 "
            "card 4242 4242 4242 4242 "
            "key sk-proj-abcdefghijklmnopqrstuvwxyz "
            "gho_abcdefghijklmnopqrstuvwxyz123456 "
            "jwt eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def "
            "password=hunter2"
        ),
        exception_message="Connect redis://:secret@localhost:6379/0",
        traceback=(
            "Traceback...\n"
            "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n"
        ),
    )

    redacted = redactor.redact_event(event)

    assert "[REDACTED_EMAIL]" in redacted.message
    assert "[REDACTED_PHONE]" in redacted.message
    assert "[REDACTED_CARD]" in redacted.message
    assert "[REDACTED_API_KEY]" in redacted.message
    assert "[REDACTED_TOKEN]" in redacted.message
    assert "[REDACTED_JWT]" in redacted.message
    assert "[REDACTED_PASSWORD]" in redacted.message
    assert redacted.exception_message == "Connect [REDACTED_DATABASE_URL]"
    assert "[REDACTED_PRIVATE_KEY]" in redacted.traceback
    assert redacted.tags["owner"] == "[REDACTED_EMAIL]"
    assert redacted.extra["token"] == "[REDACTED_TOKEN]"
    assert redacted.extra["db"] == "[REDACTED_DATABASE_URL]"


def test_redactor_skips_invalid_custom_regex_safely():
    redactor = Redactor(custom_patterns=["(", r"tenant-\d+"])
    redacted = redactor.redact_text("tenant-1234")

    assert redacted == "[REDACTED_CUSTOM]"
    assert redactor.invalid_custom_patterns == ["("]


def test_handler_redacts_captured_event(monkeypatch):
    monkeypatch.setenv("COGNIT_ENABLE_CAPTURE", "true")
    logger = logging.getLogger("cognit.tests.redaction")
    logger.handlers.clear()
    logger.propagate = False

    handler = CognitHandler(app_name="demo", environment="test")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)

    try:
        raise RuntimeError("redis://:secret@localhost:6379/0")
    except RuntimeError:
        logger.exception("password=swordfish email=admin@example.com")

    event = handler.get_last_event()

    assert event is not None
    assert "[REDACTED_PASSWORD]" in event.message
    assert "[REDACTED_EMAIL]" in event.message
    assert event.exception_message == "[REDACTED_DATABASE_URL]"
    assert "[REDACTED_DATABASE_URL]" in event.traceback
