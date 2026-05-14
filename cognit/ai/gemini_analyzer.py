"""Gemini-backed analyzer with structured fallback-friendly error handling."""

from __future__ import annotations

import json
import re
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


class GeminiAnalyzer(BaseAnalyzer):
    """Use the Gemini SDK when available to analyze incidents."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 20.0,
        client: Any | None = None,
    ) -> None:
        config = CognitConfig.from_env()
        self.api_key = api_key if api_key is not None else config.gemini_api_key
        self.model = model if model is not None else config.gemini_model
        self.timeout = timeout
        self.client = client

    def analyze(
        self,
        event: LogEvent,
        *,
        similar_incidents: Sequence[StoredIncident] | None = None,
    ) -> AIAnalysis:
        if not self.api_key:
            raise CognitAIError("Gemini API key is missing.")

        client = self.client or self._build_client()
        prompt = self._build_prompt(event, similar_incidents=similar_incidents)
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
        except CognitAIError:
            raise
        except Exception as exc:
            raise CognitAIError(self._classify_runtime_error(exc)) from exc

        raw_text = self._extract_response_text(response)
        if not raw_text or not raw_text.strip():
            raise CognitAIError("Gemini returned an empty response.")

        try:
            payload = self._parse_json_payload(raw_text)
        except json.JSONDecodeError as exc:
            raise CognitAIError("Gemini returned invalid JSON.") from exc

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
            raise CognitAIError("Gemini API key is missing.")

        client = self.client or self._build_client()
        prompt = (
            f"{build_follow_up_system_prompt()}\n\n"
            f"{build_follow_up_user_prompt(incident, question, similar_incidents=similar_incidents, conversation_history=conversation_history)}"
        )
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
        except CognitAIError:
            raise
        except Exception as exc:
            raise CognitAIError(self._classify_runtime_error(exc)) from exc

        raw_text = self._extract_response_text(response).strip()
        if not raw_text:
            raise CognitAIError("Gemini returned an empty follow-up response.")
        return raw_text

    def _build_client(self) -> Any:
        try:
            from google import genai  # type: ignore
        except ImportError as exc:
            raise CognitAIError("Gemini package is not installed.") from exc

        try:
            return genai.Client(api_key=self.api_key)
        except Exception as exc:
            raise CognitAIError(self._classify_runtime_error(exc)) from exc

    def _build_prompt(
        self,
        event: LogEvent,
        *,
        similar_incidents: Sequence[StoredIncident] | None = None,
    ) -> str:
        return (
            f"{build_system_prompt()}\n\n"
            "Return only valid JSON that matches the provided response_schema.\n\n"
            f"{build_user_prompt(event, similar_incidents=similar_incidents)}"
        )

    def _extract_response_text(self, response: Any) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return text

        candidates = getattr(response, "candidates", None)
        if isinstance(candidates, list):
            parts: list[str] = []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                response_parts = getattr(content, "parts", None)
                if not isinstance(response_parts, list):
                    continue
                for part in response_parts:
                    part_text = getattr(part, "text", None)
                    if isinstance(part_text, str):
                        parts.append(part_text)
            if parts:
                return "\n".join(parts)

        raise CognitAIError("Gemini returned an unsupported response format.")

    def _parse_json_payload(self, raw_text: str) -> dict[str, Any]:
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            cleaned = raw_text.strip()
            fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", cleaned, re.IGNORECASE)
            if fence_match:
                return json.loads(fence_match.group(1))

            object_match = re.search(r"(\{[\s\S]*\})", cleaned)
            if object_match:
                return json.loads(object_match.group(1))
            raise

    def _classify_runtime_error(self, exc: Exception) -> str:
        status_code = getattr(exc, "status_code", None)
        message = str(exc).lower()
        error_name = type(exc).__name__.lower()

        if "timeout" in message or "timed out" in message or error_name in {"apitimeouterror", "timeout"}:
            return "Gemini request timed out."
        if status_code == 429 or "rate limit" in message or "too many requests" in message:
            return "Gemini rate limit exceeded."
        if status_code == 401 or "api key" in message or "unauthorized" in message or "authentication" in message:
            return "Gemini authentication failed."
        if status_code == 403 or "permission" in message or "quota" in message or "billing" in message:
            return "Gemini permission or quota check failed."
        if "model" in message and any(term in message for term in ("invalid", "not found", "unsupported", "unavailable")):
            return "Gemini model is invalid or unavailable."
        if "network" in message or "connection" in message or "dns" in message:
            return "Gemini network failure."
        return "Gemini analysis failed."
