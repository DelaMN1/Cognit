"""Telegram message formatting helpers."""

from __future__ import annotations

from cognit.ai.schemas import AIAnalysis
from cognit.capture.event import LogEvent
from cognit.redaction.redactor import Redactor
from cognit.storage.models import StoredIncident


_PLACEHOLDER_VALUES = {
    "",
    "<string>",
    "string",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
}


def format_telegram_alert(event: LogEvent, analysis: AIAnalysis) -> str:
    redactor = Redactor()
    safe_event = redactor.redact_event(event)
    safe_analysis = redactor.redact_analysis(analysis)

    error_line = _sanitize_text(safe_event.exception_message or safe_event.message, fallback="Unknown")
    likely_cause = _sanitize_text(safe_analysis.likely_cause, fallback="Unknown")
    affected_area = _sanitize_text(safe_analysis.affected_area, fallback="Unknown")
    steps = _format_numbered_steps(
        _sanitize_steps(
            safe_analysis.suggested_steps,
            fallback_steps=_default_debugging_steps(safe_event),
        )
    )
    follow_up = f"/cognit {safe_event.incident_id} What caused this?"

    return "\n".join(
        [
            "Cognit Incident Alert",
            "",
            f"App: {safe_event.app_name}",
            f"Environment: {safe_event.environment}",
            f"Severity: {_sanitize_text(safe_analysis.severity, fallback='unknown').lower()}",
            f"Incident: {safe_event.incident_id}",
            "",
            "Error",
            error_line,
            "",
            "Likely cause",
            likely_cause,
            "",
            "Affected area",
            affected_area,
            "",
            "First debugging steps",
            steps,
            "",
            "Follow-up",
            follow_up,
        ]
    )


def format_follow_up_response(
    incident: StoredIncident,
    question: str,
    answer: str,
    *,
    similar_incidents: list[StoredIncident] | None = None,
) -> str:
    redactor = Redactor()
    safe_incident = redactor.redact_stored_incident(incident)
    safe_similar = [redactor.redact_stored_incident(item) for item in (similar_incidents or [])]
    safe_question = redactor.redact_text(question) or ""
    safe_answer = redactor.redact_text(answer) or ""

    direct_answer = _build_direct_answer(safe_incident, safe_question, safe_answer)
    why_likely = _build_why_likely(safe_incident, safe_similar)
    steps = _format_numbered_steps(_build_follow_up_steps(safe_incident))
    confidence = _build_confidence(safe_incident, safe_similar)

    return "\n".join(
        [
            "Cognit Follow-up",
            "",
            f"Incident: {safe_incident.incident_id}",
            "",
            "Answer",
            direct_answer,
            "",
            "Why this is likely",
            why_likely,
            "",
            "What to inspect next",
            steps,
            "",
            "Confidence",
            confidence,
        ]
    )


def _sanitize_text(value: str | None, *, fallback: str) -> str:
    if value is None:
        return fallback
    stripped = value.strip()
    if not stripped:
        return fallback
    normalized = stripped.lower()
    if normalized in _PLACEHOLDER_VALUES:
        return fallback
    if stripped.startswith("<") and stripped.endswith(">"):
        return fallback
    return stripped


def _sanitize_steps(steps: list[str], *, fallback_steps: list[str]) -> list[str]:
    cleaned: list[str] = []
    for step in steps:
        sanitized = _sanitize_text(step, fallback="")
        if sanitized:
            cleaned.append(sanitized)
    return cleaned[:3] or fallback_steps[:3]


def _default_debugging_steps(event: LogEvent) -> list[str]:
    location = _format_location(event.pathname, event.function, event.line_number)
    return [
        f"Inspect the failing location at {location}.",
        "Review recent configuration, deploy, and dependency changes around this incident.",
        "Reproduce the failure with the same inputs and compare it with recent similar incidents.",
    ]


def _build_direct_answer(incident: StoredIncident, question: str, answer: str) -> str:
    cleaned_answer = _sanitize_text(answer, fallback="")
    if _looks_like_manual_test(incident):
        manual_text = (
            "This incident looks like a manual test rather than an unexpected production failure."
        )
        if cleaned_answer:
            if "manual test" in cleaned_answer.lower():
                return cleaned_answer
            return f"{manual_text} {cleaned_answer}"
        return manual_text
    if cleaned_answer:
        return cleaned_answer

    if incident.exception_message:
        return f"The incident is most directly explained by: {incident.exception_message}"
    return f"The incident is most directly explained by the log message: {incident.message}"


def _build_why_likely(incident: StoredIncident, similar_incidents: list[StoredIncident]) -> str:
    evidence: list[str] = []
    message = _sanitize_text(incident.message, fallback="")
    if message:
        evidence.append(f"Message: {message}")
    exception_message = _sanitize_text(incident.exception_message, fallback="")
    if exception_message:
        evidence.append(f"Exception: {exception_message}")
    evidence.append(f"Location: {_format_location(incident.pathname, incident.function, incident.line_number)}")
    if similar_incidents:
        ids = ", ".join(item.incident_id for item in similar_incidents[:3])
        evidence.append(f"Similar incidents: {ids}")
    return " ".join(evidence[:4])


def _build_follow_up_steps(incident: StoredIncident) -> list[str]:
    ai_steps: list[str] = []
    if isinstance(incident.ai_analysis, dict):
        raw_steps = incident.ai_analysis.get("suggested_steps")
        if isinstance(raw_steps, list):
            for item in raw_steps:
                if isinstance(item, str):
                    ai_steps.append(item)
    if ai_steps:
        return _sanitize_steps(ai_steps, fallback_steps=_default_follow_up_steps(incident))
    return _default_follow_up_steps(incident)


def _default_follow_up_steps(incident: StoredIncident) -> list[str]:
    location = _format_location(incident.pathname, incident.function, incident.line_number)
    if _looks_like_manual_test(incident):
        return [
            "Confirm this alert was triggered intentionally as part of a manual test.",
            f"Check the code path or script that raised the sample exception at {location}.",
            "Trigger a real application failure if you need production-grade debugging evidence.",
        ]
    return [
        f"Inspect the failing location at {location}.",
        "Compare recent config, deploy, or dependency changes with the time this incident started.",
        "Review related incidents and retry the same code path with the original inputs if possible.",
    ]


def _build_confidence(incident: StoredIncident, similar_incidents: list[StoredIncident]) -> str:
    if _looks_like_manual_test(incident):
        return "high - the incident text itself indicates a manual or intentional test."
    if incident.exception_message and similar_incidents:
        return "high - the incident includes an exception message, source location, and similar prior incidents."
    if incident.exception_message or incident.traceback:
        return "medium - the incident includes direct failure evidence, but the root cause is still inferred."
    return "low - the incident has limited diagnostic detail beyond the log message."


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


def _format_location(pathname: str, function: str, line_number: int) -> str:
    if pathname and function:
        return f"{pathname}:{line_number} in {function}()"
    if pathname:
        return f"{pathname}:{line_number}"
    if function:
        return f"{function}():{line_number}"
    return f"line {line_number}"


def _format_numbered_steps(steps: list[str]) -> str:
    return "\n".join(f"{index}. {step}" for index, step in enumerate(steps[:3], start=1))
