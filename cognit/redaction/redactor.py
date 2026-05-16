"""Recursive redaction helpers for Cognit events."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Sequence

from cognit.capture.event import LogEvent
from cognit.storage.models import StoredIncident
from cognit.redaction.patterns import DEFAULT_REDACTION_RULES, compile_custom_rule

if TYPE_CHECKING:
    from cognit.ai.schemas import AIAnalysis


class Redactor:
    """Redact sensitive values from strings, mappings, and events."""

    def __init__(self, custom_patterns: Sequence[str] | None = None) -> None:
        self._rules = [
            (rule.compile(), rule.placeholder, rule.name) for rule in DEFAULT_REDACTION_RULES
        ]
        self.invalid_custom_patterns: list[str] = []
        self.custom_patterns = list(custom_patterns or [])
        for pattern in self.custom_patterns:
            compiled = compile_custom_rule(pattern)
            if compiled is None:
                self.invalid_custom_patterns.append(pattern)
                continue
            self._rules.append((compiled, "[REDACTED_CUSTOM]", "custom"))

    def redact_text(self, value: str | None) -> str | None:
        if value is None:
            return None

        redacted = value
        for pattern, placeholder, name in self._rules:
            if name in {"password_field", "api_key_field", "token_field"}:
                redacted = pattern.sub(rf"\1={placeholder}", redacted)
            else:
                redacted = pattern.sub(placeholder, redacted)
        return redacted

    def redact_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_value(item) for item in value)
        if isinstance(value, set):
            return {self.redact_value(item) for item in value}
        if isinstance(value, dict):
            return {
                str(self.redact_value(key)): self.redact_value(item)
                for key, item in value.items()
            }
        return self.redact_text(repr(value))

    def redact_event(self, event: LogEvent) -> LogEvent:
        return replace(
            event,
            message=self.redact_text(event.message) or "",
            exception_message=self.redact_text(event.exception_message),
            traceback=self.redact_text(event.traceback),
            tags=self.redact_value(event.tags),
            extra=self.redact_value(event.extra),
        )

    def redact_analysis(self, analysis: AIAnalysis) -> AIAnalysis:
        return replace(
            analysis,
            summary=self.redact_text(analysis.summary) or "",
            likely_cause=self.redact_text(analysis.likely_cause) or "",
            severity=self.redact_text(analysis.severity) or "unknown",
            affected_area=self.redact_text(analysis.affected_area),
            suggested_steps=[self.redact_text(step) or "" for step in analysis.suggested_steps],
            possible_fix=self.redact_text(analysis.possible_fix),
            similar_incidents_summary=self.redact_text(analysis.similar_incidents_summary),
            follow_up_questions=[
                self.redact_text(question) or "" for question in analysis.follow_up_questions
            ],
            raw_response=self.redact_text(analysis.raw_response),
        )

    def redact_stored_incident(self, incident: StoredIncident) -> StoredIncident:
        return replace(
            incident,
            message=self.redact_text(incident.message) or "",
            exception_message=self.redact_text(incident.exception_message),
            traceback=self.redact_text(incident.traceback),
            tags=self.redact_value(incident.tags),
            extra=self.redact_value(incident.extra),
            ai_analysis=self.redact_value(incident.ai_analysis),
        )
