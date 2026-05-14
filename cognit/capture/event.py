"""Structured event models for captured incidents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class LogEvent:
    incident_id: str
    app_name: str
    environment: str
    level: str
    levelno: int
    message: str
    logger_name: str
    timestamp: str
    pathname: str
    filename: str
    module: str
    function: str
    line_number: int
    process_id: int
    process_name: str
    thread_id: int
    thread_name: str
    exception_type: str | None = None
    exception_message: str | None = None
    traceback: str | None = None
    fingerprint: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
