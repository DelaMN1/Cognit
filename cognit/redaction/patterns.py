"""Regex patterns used by the Cognit redaction layer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


@dataclass(frozen=True, slots=True)
class RedactionRule:
    name: str
    placeholder: str
    pattern: str
    flags: int = 0

    def compile(self) -> Pattern[str]:
        return re.compile(self.pattern, self.flags)


DEFAULT_REDACTION_RULES: tuple[RedactionRule, ...] = (
    RedactionRule(
        name="private_key",
        placeholder="[REDACTED_PRIVATE_KEY]",
        pattern=r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        flags=re.IGNORECASE,
    ),
    RedactionRule(
        name="database_url",
        placeholder="[REDACTED_DATABASE_URL]",
        pattern=r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|sqlite|redis)://[^\s\"']+",
        flags=re.IGNORECASE,
    ),
    RedactionRule(
        name="openai_api_key",
        placeholder="[REDACTED_API_KEY]",
        pattern=r"\bsk-[A-Za-z0-9_-]{20,}\b",
    ),
    RedactionRule(
        name="github_token",
        placeholder="[REDACTED_TOKEN]",
        pattern=r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
    ),
    RedactionRule(
        name="bearer_token",
        placeholder="[REDACTED_TOKEN]",
        pattern=r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b",
        flags=re.IGNORECASE,
    ),
    RedactionRule(
        name="jwt",
        placeholder="[REDACTED_JWT]",
        pattern=r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+\b",
    ),
    RedactionRule(
        name="password_field",
        placeholder="[REDACTED_PASSWORD]",
        pattern=r"(?i)\b(password|passwd|pwd)\b\s*[:=]\s*([\"']?)([^,\s\"'}\]]+)\2",
    ),
    RedactionRule(
        name="email",
        placeholder="[REDACTED_EMAIL]",
        pattern=r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        flags=re.IGNORECASE,
    ),
    RedactionRule(
        name="phone",
        placeholder="[REDACTED_PHONE]",
        pattern=r"(?:(?<=\D)|^)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){2}\d{4}(?=\D|$)",
    ),
    RedactionRule(
        name="credit_card",
        placeholder="[REDACTED_CARD]",
        pattern=r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)",
    ),
)


def compile_custom_rule(pattern: str) -> Pattern[str] | None:
    try:
        return re.compile(pattern)
    except re.error:
        return None
