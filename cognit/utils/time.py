"""UTC time helpers for Cognit."""

from __future__ import annotations

from datetime import UTC, datetime

from cognit.constants import TIMESTAMP_FORMAT


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def format_log_record_timestamp(created_at: float) -> str:
    return format_utc_timestamp(datetime.fromtimestamp(created_at, tz=UTC))
