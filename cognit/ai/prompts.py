"""Prompt builders for Cognit AI analyzers."""

from __future__ import annotations

import json
from collections.abc import Sequence

from cognit.capture.event import LogEvent
from cognit.storage.models import StoredConversationMessage, StoredIncident


def build_system_prompt() -> str:
    return (
        "You analyze redacted application incidents for developers. "
        "Avoid guessing, state uncertainty when evidence is weak, never reconstruct secrets, "
        "and return structured JSON with practical debugging steps."
    )


def build_follow_up_system_prompt() -> str:
    return (
        "You answer developer follow-up questions about a single redacted application incident. "
        "Use only the redacted context provided, avoid guessing, state uncertainty when evidence is weak, "
        "never reconstruct secrets, keep the answer concise and practical, and answer the user's question directly. "
        "Answer the latest user question directly. Do not repeat the generic incident summary unless the question asks "
        "for a summary. If the incident appears to be a manual or intentional test, say that clearly. "
        "Do not output placeholders like <string>, string, N/A, or null."
    )


def build_user_prompt(
    event: LogEvent,
    *,
    similar_incidents: Sequence[StoredIncident] | None = None,
) -> str:
    similar_summary = [
        {
            "incident_id": incident.incident_id,
            "summary": incident.message,
            "exception_type": incident.exception_type,
            "exception_message": incident.exception_message,
            "occurrence_count": incident.occurrence_count,
        }
        for incident in (similar_incidents or [])
    ]
    payload = {
        "incident": event.to_dict(),
        "similar_incidents": similar_summary,
        "response_schema": {
            "summary": "string",
            "likely_cause": "string",
            "severity": "low|medium|high|critical|unknown",
            "affected_area": "string|null",
            "suggested_steps": ["string"],
            "possible_fix": "string|null",
            "similar_incidents_summary": "string|null",
            "follow_up_questions": ["string"],
        },
    }
    return json.dumps(payload, sort_keys=True)


def build_follow_up_user_prompt(
    incident: StoredIncident,
    question: str,
    *,
    similar_incidents: Sequence[StoredIncident] | None = None,
    conversation_history: Sequence[StoredConversationMessage] | None = None,
    max_context_chars: int = 6000,
    max_history_messages: int = 4,
    max_similar_incidents: int = 2,
    max_similar_incident_chars: int = 800,
) -> str:
    mode = _question_mode(question)
    history = list(conversation_history or [])[-max(0, max_history_messages) :]
    similar = list(similar_incidents or [])[: max(0, max_similar_incidents)]

    incident_lines = [
        f"Incident ID: {incident.incident_id}",
        f"App: {incident.app_name}",
        f"Environment: {incident.environment}",
        f"Error message: {_clean_value(incident.message)}",
    ]
    exception_line = _build_exception_line(incident)
    if exception_line:
        incident_lines.append(exception_line)
    location_line = _build_location_line(incident)
    if location_line:
        incident_lines.append(location_line)

    sections: list[tuple[str, str, bool]] = [
        ("INCIDENT CONTEXT:", "\n".join(incident_lines), True),
    ]

    traceback_tail = _build_traceback_tail(incident.traceback)
    if mode in {"cause", "inspect", "traceback"} and traceback_tail:
        title = "TRACEBACK TAIL:" if mode == "traceback" else "SHORT TRACEBACK TAIL:"
        sections.append((title, traceback_tail, mode in {"cause", "traceback"}))

    stored_analysis = _build_stored_analysis_block(incident, mode=mode)
    if stored_analysis:
        sections.append(("STORED ANALYSIS:", stored_analysis, True))

    if mode == "sensitive":
        redaction_evidence = _build_redaction_evidence_block(incident, history)
        if redaction_evidence:
            sections.append(("REDACTION EVIDENCE:", redaction_evidence, True))
    elif similar and mode == "general":
        similar_block = _build_similar_block(
            similar,
            max_similar_incident_chars=max_similar_incident_chars,
        )
        if similar_block:
            sections.append(("SIMILAR INCIDENTS:", similar_block, False))

    history_block = _build_history_block(history)
    if history_block:
        sections.append(("RECENT CONVERSATION HISTORY:", history_block, False))

    tail_sections = [
        ("LATEST USER QUESTION:", question),
        (
            "INSTRUCTIONS:",
            (
                "Answer the latest user question directly. Do not repeat the generic incident summary unless the "
                "user asks for a summary. Use only the redacted evidence in this prompt."
            ),
        ),
    ]
    tail_text = "\n\n".join(f"{title}\n{content}" for title, content in tail_sections)
    header_budget = max(256, max_context_chars - len(tail_text) - 4)
    context_text = _build_limited_sections(sections, header_budget)
    prompt = f"{context_text}\n\n{tail_text}" if context_text else tail_text
    return _truncate_preserving_tail(prompt, max_context_chars=max_context_chars, tail_text=tail_text)


def _question_mode(question: str) -> str:
    normalized = question.lower()
    if any(term in normalized for term in ("sensitive", "secret", "exposed", "password", "token", "api key")):
        return "sensitive"
    if "traceback" in normalized or "stack trace" in normalized:
        return "traceback"
    if any(term in normalized for term in ("inspect", "check", "next", "fix")):
        return "inspect"
    if any(term in normalized for term in ("cause", "why", "root cause")):
        return "cause"
    return "general"


def _build_exception_line(incident: StoredIncident) -> str:
    if incident.exception_type and incident.exception_message:
        return f"Exception: {incident.exception_type}: {incident.exception_message}"
    if incident.exception_type:
        return f"Exception: {incident.exception_type}"
    if incident.exception_message:
        return f"Exception message: {incident.exception_message}"
    return ""


def _build_location_line(incident: StoredIncident) -> str:
    parts: list[str] = []
    if incident.pathname:
        parts.append(incident.pathname)
    elif incident.filename:
        parts.append(incident.filename)
    if incident.function:
        parts.append(f"in {incident.function}()")
    if incident.line_number:
        parts.append(f"line {incident.line_number}")
    if not parts:
        return ""
    return f"Location: {' '.join(parts)}"


def _build_traceback_tail(traceback: str | None, *, max_lines: int = 8, max_chars: int = 700) -> str:
    cleaned = _clean_value(traceback)
    if not cleaned:
        return ""
    tail_lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()][-max_lines:]
    tail = "\n".join(tail_lines)
    if len(tail) <= max_chars:
        return tail
    return f"{tail[-max_chars:].lstrip()}"


def _build_stored_analysis_block(incident: StoredIncident, *, mode: str) -> str:
    if not isinstance(incident.ai_analysis, dict):
        return ""

    lines: list[str] = []
    summary = _clean_value(incident.ai_analysis.get("summary"))
    likely_cause = _clean_value(incident.ai_analysis.get("likely_cause"))
    affected_area = _clean_value(incident.ai_analysis.get("affected_area"))
    raw_steps = incident.ai_analysis.get("suggested_steps")
    steps = (
        [_clean_value(item) for item in raw_steps if isinstance(item, str) and _clean_value(item)]
        if isinstance(raw_steps, list)
        else []
    )

    if summary:
        lines.append(f"Summary: {summary}")
    if likely_cause and mode in {"cause", "general", "traceback"}:
        lines.append(f"Likely cause: {likely_cause}")
    if affected_area and mode in {"inspect", "general"}:
        lines.append(f"Affected area: {affected_area}")
    if steps and mode in {"inspect", "general"}:
        lines.append("Debugging steps:")
        lines.extend(f"{index}. {step}" for index, step in enumerate(steps[:3], start=1))
    return "\n".join(lines)


def _build_redaction_evidence_block(
    incident: StoredIncident,
    history: Sequence[StoredConversationMessage],
) -> str:
    markers = _collect_redaction_markers(
        [
            incident.message,
            incident.exception_message,
            incident.traceback,
            str(incident.ai_analysis) if incident.ai_analysis is not None else "",
            *(message.content for message in history),
        ]
    )
    if not markers:
        return "No explicit redaction placeholders appeared in the compact incident context."
    return (
        "Redaction placeholders present in the incident context: "
        + ", ".join(markers[:6])
        + ". This confirms redaction in this follow-up context, not every external sink."
    )


def _collect_redaction_markers(chunks: Sequence[str | None]) -> list[str]:
    markers: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        for part in chunk.split():
            if part.startswith("[REDACTED_") and part.endswith("]") and part not in markers:
                markers.append(part)
    return markers


def _build_similar_block(
    similar_incidents: Sequence[StoredIncident],
    *,
    max_similar_incident_chars: int,
) -> str:
    items: list[str] = []
    for index, incident in enumerate(similar_incidents, start=1):
        summary_parts = [
            f"{incident.incident_id}",
            _clean_value(incident.message),
            _build_exception_line(incident),
        ]
        summary = " | ".join(part for part in summary_parts if part)
        items.append(f"{index}. {_truncate_text(summary, max_similar_incident_chars)}")
    return "\n".join(items)


def _build_history_block(history: Sequence[StoredConversationMessage]) -> str:
    lines = [
        f"{message.role} ({message.source}): {_truncate_text(_clean_value(message.content), 280)}"
        for message in history
        if _clean_value(message.content)
    ]
    return "\n".join(lines)


def _build_limited_sections(sections: Sequence[tuple[str, str, bool]], max_chars: int) -> str:
    included: list[str] = []
    remaining = max_chars

    for title, content, required in sections:
        if not content:
            continue
        section = f"{title}\n{content}"
        separator = "\n\n" if included else ""
        required_length = len(separator) + len(section)
        if required:
            if required_length > remaining:
                content_budget = max(0, remaining - len(separator) - len(title) - 1)
                section = f"{title}\n{_truncate_text(content, content_budget)}" if content_budget > 0 else ""
                required_length = len(separator) + len(section)
            if section:
                included.append(f"{separator}{section}" if separator else section)
                remaining -= required_length
            continue
        if required_length <= remaining:
            included.append(f"{separator}{section}" if separator else section)
            remaining -= required_length
    return "".join(included)


def _truncate_preserving_tail(prompt: str, *, max_context_chars: int, tail_text: str) -> str:
    if len(prompt) <= max_context_chars:
        return prompt
    tail = tail_text[-min(len(tail_text), max_context_chars - 32) :]
    head_budget = max(0, max_context_chars - len(tail) - len("\n\n[CONTEXT TRUNCATED]\n\n"))
    head = prompt[:head_budget].rstrip()
    pieces = [piece for piece in (head, "[CONTEXT TRUNCATED]", tail) if piece]
    return "\n\n".join(pieces)[:max_context_chars]


def _truncate_text(value: str, limit: int) -> str:
    cleaned = _clean_value(value)
    if limit <= 0:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 16:
        return cleaned[:limit]
    return f"{cleaned[: limit - 12].rstrip()} [TRUNCATED]"


def _clean_value(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return " ".join(text.split()) if "\n" not in text else "\n".join(line.rstrip() for line in text.splitlines())
