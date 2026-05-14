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
        "If the incident appears to be a manual or intentional test, say that clearly. "
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
) -> str:
    similar_summary = [
        {
            "incident_id": similar.incident_id,
            "message": similar.message,
            "exception_type": similar.exception_type,
            "exception_message": similar.exception_message,
            "occurrence_count": similar.occurrence_count,
        }
        for similar in (similar_incidents or [])
    ]
    history_summary = [
        {
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at,
        }
        for message in (conversation_history or [])
    ]
    payload = {
        "incident": {
            "incident_id": incident.incident_id,
            "app_name": incident.app_name,
            "environment": incident.environment,
            "level": incident.level,
            "message": incident.message,
            "logger_name": incident.logger_name,
            "module": incident.module,
            "function": incident.function,
            "line_number": incident.line_number,
            "exception_type": incident.exception_type,
            "exception_message": incident.exception_message,
            "traceback": incident.traceback,
            "occurrence_count": incident.occurrence_count,
            "suppressed_count": incident.suppressed_count,
            "ai_analysis": incident.ai_analysis,
        },
        "similar_incidents": similar_summary,
        "conversation_history": history_summary,
        "question": question,
        "instructions": (
            "Answer in plain text. Give a direct answer first, then briefly explain the strongest evidence. "
            "Do not invent facts not present in the incident context."
        ),
    }
    return json.dumps(payload, sort_keys=True)
