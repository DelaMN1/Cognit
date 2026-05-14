"""Transform standard LogRecord objects into structured Cognit events."""

from __future__ import annotations

import logging

from cognit.capture.event import LogEvent
from cognit.capture.traceback_parser import parse_exc_info
from cognit.constants import RESERVED_LOG_RECORD_FIELDS
from cognit.utils.ids import generate_fingerprint, generate_incident_id
from cognit.utils.json import make_json_safe
from cognit.utils.time import format_log_record_timestamp


def build_log_event(
    record: logging.LogRecord,
    *,
    app_name: str,
    environment: str,
    tags: dict[str, str] | None = None,
) -> LogEvent:
    exception_type, exception_message, rendered_traceback = parse_exc_info(record.exc_info)

    message = record.getMessage()
    event = LogEvent(
        incident_id=generate_incident_id(),
        app_name=app_name,
        environment=environment,
        level=record.levelname,
        levelno=record.levelno,
        message=message,
        logger_name=record.name,
        timestamp=format_log_record_timestamp(record.created),
        pathname=record.pathname,
        filename=record.filename,
        module=record.module,
        function=record.funcName,
        line_number=record.lineno,
        process_id=record.process,
        process_name=record.processName,
        thread_id=record.thread,
        thread_name=record.threadName,
        exception_type=exception_type,
        exception_message=exception_message,
        traceback=rendered_traceback,
        tags=dict(tags or {}),
        extra=_extract_extra_fields(record),
    )
    event.fingerprint = generate_fingerprint(
        app_name=app_name,
        environment=environment,
        exception_type=event.exception_type,
        exception_message=event.exception_message,
        pathname=event.pathname,
        function=event.function,
        line_number=event.line_number,
    )
    return event


def _extract_extra_fields(record: logging.LogRecord) -> dict[str, object]:
    extra: dict[str, object] = {}
    for key, value in record.__dict__.items():
        if key in RESERVED_LOG_RECORD_FIELDS:
            continue
        extra[key] = make_json_safe(value)
    return extra
