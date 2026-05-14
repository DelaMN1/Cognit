"""Structured schema helpers for Cognit AI analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognit.exceptions import CognitAIError

ALLOWED_SEVERITIES = {"low", "medium", "high", "critical", "unknown"}


@dataclass(slots=True)
class AIAnalysis:
    summary: str
    likely_cause: str
    severity: str
    affected_area: str | None
    suggested_steps: list[str]
    possible_fix: str | None
    similar_incidents_summary: str | None
    follow_up_questions: list[str]
    raw_response: str | None = None


def coerce_analysis_payload(payload: dict[str, Any], *, raw_response: str | None = None) -> AIAnalysis:
    required_string_fields = ("summary", "likely_cause", "severity")
    for field in required_string_fields:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CognitAIError(f"Invalid AI response: missing or empty '{field}'.")

    severity = payload["severity"].strip().lower()
    if severity not in ALLOWED_SEVERITIES:
        raise CognitAIError("Invalid AI response: unsupported severity value.")

    suggested_steps = _normalize_string_list(payload.get("suggested_steps"))
    follow_up_questions = _normalize_string_list(payload.get("follow_up_questions"))
    if not suggested_steps:
        raise CognitAIError("Invalid AI response: suggested_steps must contain at least one item.")

    return AIAnalysis(
        summary=payload["summary"].strip(),
        likely_cause=payload["likely_cause"].strip(),
        severity=severity,
        affected_area=_normalize_optional_string(payload.get("affected_area")),
        suggested_steps=suggested_steps,
        possible_fix=_normalize_optional_string(payload.get("possible_fix")),
        similar_incidents_summary=_normalize_optional_string(
            payload.get("similar_incidents_summary")
        ),
        follow_up_questions=follow_up_questions,
        raw_response=raw_response,
    )


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CognitAIError("Invalid AI response: expected string field.")
    stripped = value.strip()
    return stripped or None


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CognitAIError("Invalid AI response: expected list field.")

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise CognitAIError("Invalid AI response: list items must be strings.")
        stripped = item.strip()
        if stripped:
            items.append(stripped)
    return items
