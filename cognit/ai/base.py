"""Base interfaces and orchestration for AI analysis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from cognit.ai.fallback import FallbackAnalyzer
from cognit.ai.schemas import AIAnalysis
from cognit.capture.event import LogEvent
from cognit.config import CognitConfig
from cognit.exceptions import CognitAIError
from cognit.redaction.redactor import Redactor
from cognit.storage.models import StoredConversationMessage, StoredIncident


class BaseAnalyzer(ABC):
    """Common interface for Cognit analyzers."""

    @abstractmethod
    def analyze(
        self,
        event: LogEvent,
        *,
        similar_incidents: Sequence[StoredIncident] | None = None,
    ) -> AIAnalysis:
        raise NotImplementedError

    def answer_follow_up(
        self,
        incident: StoredIncident,
        question: str,
        *,
        similar_incidents: Sequence[StoredIncident] | None = None,
        conversation_history: Sequence[StoredConversationMessage] | None = None,
    ) -> str:
        raise CognitAIError("Follow-up responses are not supported by this analyzer.")


def analyze_with_fallback(
    event: LogEvent,
    *,
    analyzer: BaseAnalyzer | None,
    fallback: FallbackAnalyzer | None = None,
    similar_incidents: Sequence[StoredIncident] | None = None,
) -> AIAnalysis:
    fallback_analyzer = fallback or FallbackAnalyzer()
    redactor = Redactor()
    safe_event = redactor.redact_event(event)
    safe_similar_incidents = [
        redactor.redact_stored_incident(incident) for incident in (similar_incidents or [])
    ]
    if analyzer is None:
        return redactor.redact_analysis(
            fallback_analyzer.analyze(safe_event, similar_incidents=safe_similar_incidents)
        )
    try:
        return redactor.redact_analysis(
            analyzer.analyze(safe_event, similar_incidents=safe_similar_incidents)
        )
    except CognitAIError:
        return redactor.redact_analysis(
            fallback_analyzer.analyze(safe_event, similar_incidents=safe_similar_incidents)
        )


def answer_follow_up_with_fallback(
    incident: StoredIncident,
    question: str,
    *,
    analyzer: BaseAnalyzer | None,
    fallback: FallbackAnalyzer | None = None,
    similar_incidents: Sequence[StoredIncident] | None = None,
    conversation_history: Sequence[StoredConversationMessage] | None = None,
) -> str:
    fallback_analyzer = fallback or FallbackAnalyzer()
    redactor = Redactor()
    safe_incident = redactor.redact_stored_incident(incident)
    safe_question = redactor.redact_text(question) or ""
    safe_similar_incidents = [
        redactor.redact_stored_incident(item) for item in (similar_incidents or [])
    ]
    safe_conversation_history = [
        StoredConversationMessage(
            incident_id=item.incident_id,
            role=item.role,
            content=redactor.redact_text(item.content) or "",
            created_at=item.created_at,
        )
        for item in (conversation_history or [])
    ]
    if analyzer is None:
        return redactor.redact_text(
            fallback_analyzer.answer_follow_up(
                safe_incident,
                safe_question,
                similar_incidents=safe_similar_incidents,
                conversation_history=safe_conversation_history,
            )
        ) or ""

    try:
        return redactor.redact_text(
            analyzer.answer_follow_up(
                safe_incident,
                safe_question,
                similar_incidents=safe_similar_incidents,
                conversation_history=safe_conversation_history,
            )
        ) or ""
    except CognitAIError:
        return redactor.redact_text(
            fallback_analyzer.answer_follow_up(
                safe_incident,
                safe_question,
                similar_incidents=safe_similar_incidents,
                conversation_history=safe_conversation_history,
            )
        ) or ""

def build_analyzer(config: CognitConfig | None = None) -> BaseAnalyzer | None:
    resolved_config = config or CognitConfig.from_env()
    provider = (resolved_config.ai_provider or "openai").strip().lower()

    if provider == "openai":
        from cognit.ai.openai_analyzer import OpenAIAnalyzer

        return OpenAIAnalyzer(
            api_key=resolved_config.openai_api_key,
            model=resolved_config.openai_model,
        )
    if provider == "gemini":
        from cognit.ai.gemini_analyzer import GeminiAnalyzer

        return GeminiAnalyzer(
            api_key=resolved_config.gemini_api_key,
            model=resolved_config.gemini_model,
        )
    return None
