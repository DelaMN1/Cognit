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
        suggested_steps: list[str] = []
        if isinstance(incident.ai_analysis, dict):
            likely_cause = incident.ai_analysis.get("likely_cause")
            raw_steps = incident.ai_analysis.get("suggested_steps")
            if isinstance(raw_steps, list):
                suggested_steps = [item for item in raw_steps if isinstance(item, str)]

        normalized_question = question.strip().lower()
        if _is_sensitive_data_question(normalized_question):
            if _contains_redaction_markers(incident, similar_incidents, conversation_history):
                return (
                    "The incident context used for this reply is redacted. I can see placeholder values such as "
                    "[REDACTED_EMAIL], [REDACTED_API_KEY], [REDACTED_PASSWORD], or [REDACTED_DATABASE_URL], which "
                    "shows the bot output is redacted. That confirms redaction in this follow-up path, not "
                    "necessarily every external sink unless those paths are verified separately."
                )
            return (
                "I do not see raw secrets in the redacted incident context used for this reply. That confirms this "
                "follow-up answer used redacted data, not that every external sink has been verified."
            )
        if _is_traceback_question(normalized_question):
            traceback_tail = _build_traceback_tail(incident.traceback)
            if traceback_tail:
                return f"Here is the most relevant traceback tail:\n{traceback_tail}"
            return "The incident does not include a traceback tail in the stored context."
        if _is_inspection_question(normalized_question):
            return _build_inspection_answer(incident, suggested_steps)
        if _looks_like_manual_test(incident):
            return (
                "This incident appears to be a manual test because the incident text explicitly says it was triggered "
                "for testing rather than describing an unexpected production failure. The immediate cause is the "
                "intentional sample exception raised by that test path."
            )
        if _is_cause_question(normalized_question):
            if likely_cause:
                return f"The most likely cause is: {likely_cause}"
            if incident.exception_message:
                return f"The most likely cause is the exception message: {incident.exception_message}"
            return f"The most likely cause is the logged error message: {incident.message}"
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


def _is_cause_question(question: str) -> bool:
    return "cause" in question or "why" in question or "root cause" in question


def _is_inspection_question(question: str) -> bool:
    return any(term in question for term in ("inspect", "check", "next", "first", "look at"))


def _is_sensitive_data_question(question: str) -> bool:
    return any(
        term in question
        for term in ("sensitive", "secret", "exposed", "password", "api key", "token")
    )


def _is_traceback_question(question: str) -> bool:
    return "traceback" in question or "stack trace" in question


def _build_inspection_answer(incident: StoredIncident, suggested_steps: Sequence[str]) -> str:
    steps = [step.strip() for step in suggested_steps if step.strip()]
    if steps:
        first_step = steps[0]
        if len(steps) > 1:
            return f"Inspect this first: {first_step} Then check: {steps[1]}"
        return f"Inspect this first: {first_step}"
    return (
        f"Inspect the failing location at {incident.pathname}:{incident.line_number} in {incident.function}() first, "
        "then review the inputs and recent changes around that code path."
    )


def _contains_redaction_markers(
    incident: StoredIncident,
    similar_incidents: Sequence[StoredIncident] | None,
    conversation_history: Sequence[StoredConversationMessage] | None,
) -> bool:
    chunks = [incident.message or "", incident.exception_message or "", incident.traceback or ""]
    if isinstance(incident.ai_analysis, dict):
        chunks.append(str(incident.ai_analysis))
    for item in similar_incidents or []:
        chunks.extend([item.message or "", item.exception_message or "", item.traceback or ""])
    for item in conversation_history or []:
        chunks.append(item.content or "")
    return "[REDACTED_" in " ".join(chunks)


def _build_traceback_tail(traceback: str | None, *, max_lines: int = 6, max_chars: int = 500) -> str:
    if not traceback:
        return ""
    tail_lines = [line.rstrip() for line in traceback.splitlines() if line.strip()][-max_lines:]
    tail = "\n".join(tail_lines)
    if len(tail) <= max_chars:
        return tail
    return tail[-max_chars:].lstrip()
