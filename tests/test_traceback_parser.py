from __future__ import annotations

import logging
import re

from cognit.capture.record_builder import build_log_event


def _make_record(*, exc_info=None, message="plain error", level=logging.ERROR):
    return logging.LogRecord(
        name="cognit.tests.capture",
        level=level,
        pathname=__file__,
        lineno=42,
        msg=message,
        args=(),
        exc_info=exc_info,
        func="test_case",
    )


def test_build_log_event_without_exception():
    record = _make_record()
    event = build_log_event(record, app_name="demo", environment="test")

    assert event.exception_type is None
    assert event.exception_message is None
    assert event.traceback is None
    assert event.message == "plain error"
    assert re.fullmatch(r"cog_\d{8}_\d{6}_[0-9a-f]{6}", event.incident_id)
    assert event.timestamp.endswith("Z")


def test_build_log_event_with_exception():
    try:
        raise RuntimeError("database down")
    except RuntimeError:
        record = _make_record(exc_info=True, message="request failed")
        record.exc_info = __import__("sys").exc_info()

    event = build_log_event(record, app_name="demo", environment="test")

    assert event.exception_type == "RuntimeError"
    assert event.exception_message == "database down"
    assert "RuntimeError: database down" in event.traceback
    assert event.fingerprint


def test_fingerprint_is_deterministic_for_same_record_shape():
    try:
        raise KeyError("missing user")
    except KeyError:
        exc_info = __import__("sys").exc_info()

    record_one = _make_record(exc_info=exc_info, message="lookup failed")
    record_two = _make_record(exc_info=exc_info, message="lookup failed")

    event_one = build_log_event(record_one, app_name="demo", environment="test")
    event_two = build_log_event(record_two, app_name="demo", environment="test")

    assert event_one.fingerprint == event_two.fingerprint
