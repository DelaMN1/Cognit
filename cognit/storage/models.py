"""Typed models returned by Cognit storage backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StoredIncident:
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
    exception_type: str | None
    exception_message: str | None
    traceback: str | None
    fingerprint: str
    tags: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    occurrence_count: int = 1
    suppressed_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    ai_analysis: dict[str, Any] | None = None


@dataclass(slots=True)
class StoredEmbedding:
    incident_id: str
    embedding: list[float]
    text_hash: str
    dimensions: int
    created_at: str


@dataclass(slots=True)
class StoredTelegramMessage:
    incident_id: str
    chat_id: str
    message_id: str
    created_at: str


@dataclass(slots=True)
class StoredAlertEvent:
    fingerprint: str
    incident_id: str
    channel: str
    sent: bool
    suppressed_reason: str | None
    created_at: str


@dataclass(slots=True)
class StoredConversationMessage:
    incident_id: str
    role: str
    content: str
    created_at: str
