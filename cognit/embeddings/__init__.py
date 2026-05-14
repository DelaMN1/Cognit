"""Embedding helpers and similar incident retrieval."""

from cognit.embeddings.base import (
    BaseEmbedder,
    SimilarIncidentRetriever,
    build_embedder,
    build_embedding_text,
    build_stored_incident_embedding_text,
)
from cognit.embeddings.local_hash import LocalHashEmbedder
from cognit.embeddings.openai_embedder import OpenAIEmbedder

__all__ = [
    "BaseEmbedder",
    "LocalHashEmbedder",
    "OpenAIEmbedder",
    "SimilarIncidentRetriever",
    "build_embedder",
    "build_embedding_text",
    "build_stored_incident_embedding_text",
]
