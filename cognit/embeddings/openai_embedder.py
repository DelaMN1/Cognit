"""Optional OpenAI-backed embeddings."""

from __future__ import annotations

from typing import Any

from cognit.embeddings.base import BaseEmbedder
from cognit.exceptions import CognitAIError


class OpenAIEmbedder(BaseEmbedder):
    """Use OpenAI embeddings when configured."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "text-embedding-3-small",
        timeout: float = 20.0,
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.client = client

    def embed(self, text: str) -> list[float]:
        if not self.api_key:
            raise CognitAIError("OpenAI embedding API key is missing.")

        client = self.client or self._build_client()
        try:
            response = client.embeddings.create(
                model=self.model,
                input=text,
            )
        except CognitAIError:
            raise
        except Exception as exc:
            raise CognitAIError(self._classify_runtime_error(exc)) from exc

        data = getattr(response, "data", None)
        if not isinstance(data, list) or not data:
            raise CognitAIError("OpenAI returned an empty embedding response.")
        vector = getattr(data[0], "embedding", None)
        if not isinstance(vector, list) or not vector:
            raise CognitAIError("OpenAI returned an invalid embedding response.")
        return [float(value) for value in vector]

    def _build_client(self) -> Any:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise CognitAIError("OpenAI package is not installed.") from exc
        return OpenAI(api_key=self.api_key, timeout=self.timeout)

    def _classify_runtime_error(self, exc: Exception) -> str:
        message = str(exc).lower()
        if "timeout" in message:
            return "OpenAI embedding request timed out."
        if "rate limit" in message or "too many requests" in message:
            return "OpenAI embedding rate limit exceeded."
        if "api key" in message or "unauthorized" in message or "authentication" in message:
            return "OpenAI embedding authentication failed."
        if "model" in message and "not" in message:
            return "OpenAI embedding model is invalid or unavailable."
        if "network" in message or "connection" in message:
            return "OpenAI embedding network failure."
        return "OpenAI embedding failed."
