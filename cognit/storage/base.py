"""Abstract storage interface for Cognit."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from cognit.capture.event import LogEvent
from cognit.storage.models import ChatContext, StoredConversationMessage, StoredIncident


class BaseStore(ABC):
    """Common interface expected from Cognit storage backends."""

    @abstractmethod
    def save_incident(self, event: LogEvent) -> StoredIncident:
        raise NotImplementedError

    @abstractmethod
    def save_ai_analysis(self, incident_id: str, analysis: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_embedding(self, incident_id: str, embedding: list[float], text_hash: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_incident(self, incident_id: str) -> StoredIncident | None:
        raise NotImplementedError

    @abstractmethod
    def get_recent_incident_by_fingerprint(
        self,
        fingerprint: str,
        within_seconds: int,
    ) -> StoredIncident | None:
        raise NotImplementedError

    @abstractmethod
    def increment_occurrence(self, incident_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def increment_suppressed_count(self, incident_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def count_recent_sent_alert_events(self, channel: str, window_seconds: int) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_recent_incidents(self, limit: int = 20) -> list[StoredIncident]:
        raise NotImplementedError

    @abstractmethod
    def find_similar_incidents(
        self,
        embedding: list[float],
        *,
        exclude_incident_id: str,
        app_name: str,
        environment: str,
        limit: int = 3,
    ) -> list[StoredIncident]:
        raise NotImplementedError

    @abstractmethod
    def save_telegram_message(self, incident_id: str, chat_id: str, message_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_alert_event(
        self,
        fingerprint: str,
        incident_id: str,
        channel: str,
        sent: bool,
        suppressed_reason: str | None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_conversation_message(
        self,
        incident_id: str,
        role: str,
        content: str,
        *,
        source: str = "explicit",
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_conversation(self, incident_id: str, limit: int = 20) -> list[StoredConversationMessage]:
        raise NotImplementedError

    @abstractmethod
    def set_active_incident(self, chat_id: str, incident_id: str, *, ttl_seconds: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_chat_context(self, chat_id: str) -> ChatContext | None:
        raise NotImplementedError

    @abstractmethod
    def get_active_incident(self, chat_id: str) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def clear_chat_context(self, chat_id: str) -> None:
        raise NotImplementedError
