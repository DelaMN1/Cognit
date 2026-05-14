"""Base embedding helpers for Cognit."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Sequence

from cognit.capture.event import LogEvent
from cognit.config import CognitConfig
from cognit.storage.base import BaseStore
from cognit.storage.models import StoredIncident


class BaseEmbedder(ABC):
    """Common interface for Cognit embedders."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    def text_hash(self, text: str) -> str:
        normalized = " ".join(text.split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_embedder(config: CognitConfig | None = None) -> BaseEmbedder:
    resolved_config = config or CognitConfig.from_env()
    provider = (resolved_config.ai_provider or "openai").strip().lower()

    if provider == "openai" and resolved_config.openai_api_key:
        from cognit.embeddings.openai_embedder import OpenAIEmbedder

        return OpenAIEmbedder(
            api_key=resolved_config.openai_api_key,
            model=resolved_config.openai_embedding_model,
        )

    from cognit.embeddings.local_hash import LocalHashEmbedder

    return LocalHashEmbedder()


def build_embedding_text(event: LogEvent) -> str:
    parts = [
        event.app_name,
        event.environment,
        event.level,
        event.logger_name,
        event.module,
        event.function,
        event.message,
        event.exception_type or "",
        event.exception_message or "",
        event.traceback or "",
    ]
    return "\n".join(part for part in parts if part)


def build_stored_incident_embedding_text(incident: StoredIncident) -> str:
    parts = [
        incident.app_name,
        incident.environment,
        incident.level,
        incident.logger_name,
        incident.module,
        incident.function,
        incident.message,
        incident.exception_type or "",
        incident.exception_message or "",
        incident.traceback or "",
    ]
    return "\n".join(part for part in parts if part)


class SimilarIncidentRetriever:
    """Look up similar incidents using stored embeddings."""

    def __init__(self, store: BaseStore, *, limit: int = 3) -> None:
        self.store = store
        self.limit = limit

    def find_similar(
        self,
        event: LogEvent,
        embedding: Sequence[float],
        *,
        incident_id: str,
    ) -> list[StoredIncident]:
        return self.store.find_similar_incidents(
            list(embedding),
            exclude_incident_id=incident_id,
            app_name=event.app_name,
            environment=event.environment,
            limit=self.limit,
        )
