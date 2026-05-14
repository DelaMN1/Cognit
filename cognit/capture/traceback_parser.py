"""Helpers for extracting traceback data from log records."""

from __future__ import annotations

import traceback
from typing import Any


def parse_exc_info(exc_info: Any) -> tuple[str | None, str | None, str | None]:
    if not exc_info:
        return None, None, None

    exc_type, exc_value, exc_tb = exc_info
    if exc_type is None:
        return None, None, None

    type_name = exc_type.__name__
    message = str(exc_value) if exc_value is not None else ""
    rendered = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).strip()
    return type_name, message, rendered or None
