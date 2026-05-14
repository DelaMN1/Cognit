"""Fallback analyzer used when AI providers are unavailable."""

from __future__ import annotations

from collections.abc import Sequence

from cognit.ai.schemas import AIAnalysis
from cognit.capture.event import LogEvent
from cognit.storage.models import StoredConversationMessage, StoredIncident


class FallbackAnalyzer:
    """Produce a deterministic, useful analysis without an external AI service."""

    def analyze(
        self,
        event: LogEvent,
        *,
        similar_incidents: Sequence[StoredIncident] | None = None,
    ) -> AIAnalysis:
        severity = _infer_severity(event)
        likely_cause = event.exception_message or event.message or "The log record does not include an exception message."
        similar_summary = None
        if similar_incidents:
            ids = ", ".join(incident.incident_id for incident in similar_incidents[:3])
            similar_summary = f"Recent similar incidents: {ids}."

        steps = [
            f"Inspect the failing location at {event.pathname}:{event.line_number}.",
            "Review recent deployments, configuration changes, and upstream dependencies.",
            "Reproduce the failure with the same input and compare stack traces across occurrences.",
        ]
        follow_ups = [
            "What changed immediately before this incident started?",
            "Does this failure affect every request or a specific code path?",
        ]

        return AIAnalysis(
            summary=f"{event.level} in {event.logger_name}: {event.message}",
            likely_cause=likely_cause,
            severity=severity,
            affected_area=event.module or None,
            suggested_steps=steps,
            possible_fix="Add targeted logging around the failing branch and validate the dependent inputs.",
            similar_incidents_summary=similar_summary,
            follow_up_questions=follow_ups,
        )

    def answer_follow_up(
        self,
        incident: StoredIncident,
        question: str,
        *,
        similar_incidents: Sequence[StoredIncident] | None = None,
        conversation_history: Sequence[StoredConversationMessage] | None = None,
    ) -> str:
        likely_cause = None
        if isinstance(incident.ai_analysis, dict):
            likely_cause = incident.ai_analysis.get("likely_cause")

        del question, conversation_history
        if _looks_like_manual_test(incident):
            return (
                "This incident appears to be a manual test because the incident text explicitly says it was triggered "
                "for testing rather than describing an unexpected production failure."
            )
        if likely_cause:
            return f"The stored analysis points to this likely cause: {likely_cause}"
        if incident.exception_message:
            return f"The incident is most directly explained by this exception: {incident.exception_message}"
        if similar_incidents:
            similar_ids = ", ".join(item.incident_id for item in similar_incidents[:3])
            return f"This looks similar to prior incidents ({similar_ids}), so the same failure pattern may be recurring."
        return f"The incident is most directly explained by the logged error message: {incident.message}"


def _infer_severity(event: LogEvent) -> str:
    if event.levelno >= 50:
        return "critical"
    if event.levelno >= 40:
        return "high"
    if event.levelno >= 30:
        return "medium"
    if event.levelno > 0:
        return "low"
    return "unknown"


def _looks_like_manual_test(incident: StoredIncident) -> bool:
    haystack = " ".join(
        filter(
            None,
            [
                incident.message,
                incident.exception_message,
                incident.traceback,
            ],
        )
    ).lower()
    return "manual test" in haystack or "manual follow-up test" in haystack or "manual alert test" in haystack
