"""OpenAI-backed analyzer with structured fallback-friendly error handling."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from cognit.ai.base import BaseAnalyzer
from cognit.ai.prompts import (
    build_follow_up_system_prompt,
    build_follow_up_user_prompt,
    build_system_prompt,
    build_user_prompt,
)
from cognit.ai.schemas import AIAnalysis, coerce_analysis_payload
from cognit.capture.event import LogEvent
from cognit.config import CognitConfig
from cognit.exceptions import CognitAIError
from cognit.storage.models import StoredConversationMessage, StoredIncident


class OpenAIAnalyzer(BaseAnalyzer):
    """Use the OpenAI SDK when available to analyze incidents."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 20.0,
        client: Any | None = None,
    ) -> None:
        config = CognitConfig.from_env()
        self.api_key = api_key if api_key is not None else config.openai_api_key
        self.model = model if model is not None else config.openai_model
        self.timeout = timeout
        self.client = client

    def analyze(
        self,
        event: LogEvent,
        *,
        similar_incidents: Sequence[StoredIncident] | None = None,
    ) -> AIAnalysis:
        if not self.api_key:
            raise CognitAIError("OpenAI API key is missing.")

        client = self.client or self._build_client()
        try:
            response = client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": build_system_prompt()},
                    {
                        "role": "user",
                        "content": build_user_prompt(
                            event,
                            similar_incidents=similar_incidents,
                        ),
                    },
                ],
                timeout=self.timeout,
            )
        except CognitAIError:
            raise
        except Exception as exc:
            raise CognitAIError(self._classify_runtime_error(exc)) from exc

        raw_text = self._extract_response_text(response)
        if not raw_text or not raw_text.strip():
            raise CognitAIError("OpenAI returned an empty response.")

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise CognitAIError("OpenAI returned invalid JSON.") from exc

        return coerce_analysis_payload(payload, raw_response=raw_text)

    def answer_follow_up(
        self,
        incident: StoredIncident,
        question: str,
        *,
        similar_incidents: Sequence[StoredIncident] | None = None,
        conversation_history: Sequence[StoredConversationMessage] | None = None,
    ) -> str:
        if not self.api_key:
            raise CognitAIError("OpenAI API key is missing.")

        client = self.client or self._build_client()
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": "system", "content": build_follow_up_system_prompt()},
                {
                    "role": "user",
                    "content": build_follow_up_user_prompt(
                        incident,
                        question,
                        similar_incidents=similar_incidents,
                        conversation_history=conversation_history,
                    ),
                },
            ],
            "timeout": self.timeout,
            "max_output_tokens": 400,
        }
        try:
            response = client.responses.create(**request_kwargs)
        except TypeError as exc:
            if "max_output_tokens" not in str(exc):
                raise CognitAIError(self._classify_runtime_error(exc)) from exc
            request_kwargs.pop("max_output_tokens", None)
            try:
                response = client.responses.create(**request_kwargs)
            except Exception as retry_exc:
                raise CognitAIError(self._classify_runtime_error(retry_exc)) from retry_exc
        except CognitAIError:
            raise
        except Exception as exc:
            raise CognitAIError(self._classify_runtime_error(exc)) from exc

        raw_text = self._extract_response_text(response).strip()
        if not raw_text:
            raise CognitAIError("OpenAI returned an empty follow-up response.")
        return raw_text

    def _build_client(self) -> Any:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise CognitAIError("OpenAI package is not installed.") from exc

        try:
            return OpenAI(api_key=self.api_key, timeout=self.timeout)
        except Exception as exc:
            raise CognitAIError(self._classify_runtime_error(exc)) from exc

    def _extract_response_text(self, response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            return output_text

        choices = getattr(response, "choices", None)
        if isinstance(choices, list) and choices:
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None)
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    text = getattr(item, "text", None)
                    if isinstance(text, str):
                        parts.append(text)
                return "\n".join(parts)
        raise CognitAIError("OpenAI returned an unsupported response format.")

    def _classify_runtime_error(self, exc: Exception) -> str:
        message = str(exc).lower()
        if "timeout" in message:
            return "OpenAI request timed out."
        if "rate limit" in message or "too many requests" in message:
            return "OpenAI rate limit exceeded."
        if "api key" in message or "unauthorized" in message or "authentication" in message:
            return "OpenAI authentication failed."
        if "model" in message and "not" in message:
            return "OpenAI model is invalid or unavailable."
        if "network" in message or "connection" in message:
            return "OpenAI network failure."
        return "OpenAI analysis failed."
