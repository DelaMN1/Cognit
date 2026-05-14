"""Identifier helpers for Cognit incidents."""

from __future__ import annotations

import hashlib
import secrets

from cognit.constants import INCIDENT_ID_PREFIX
from cognit.utils.time import utc_now


def generate_incident_id() -> str:
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(3)
    return f"{INCIDENT_ID_PREFIX}_{timestamp}_{suffix}"


def generate_fingerprint(
    *,
    app_name: str,
    environment: str,
    exception_type: str | None,
    exception_message: str | None,
    pathname: str,
    function: str,
    line_number: int,
) -> str:
    payload = "|".join(
        [
            app_name,
            environment,
            exception_type or "",
            exception_message or "",
            pathname,
            function,
            str(line_number),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
