"""Telegram delivery client for Cognit alerts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request

from cognit.exceptions import CognitTelegramError

Transport = Callable[[str, str, dict[str, Any], float], dict[str, Any]]


@dataclass(slots=True)
class TelegramClientError(CognitTelegramError):
    category: str
    detail: str

    def __str__(self) -> str:
        return self.detail


class TelegramClient:
    """Small wrapper around the Telegram Bot API."""

    def __init__(
        self,
        *,
        token: str | None,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        self.token = token
        self.timeout = timeout
        self.transport = transport or _default_transport

    def send_message(self, chat_id: str | None, text: str) -> str:
        self._ensure_token()
        self._ensure_chat_id(chat_id)

        response = self._request(
            "sendMessage",
            {"chat_id": chat_id, "text": text},
        )
        result = response.get("result")
        if not isinstance(result, dict) or "message_id" not in result:
            raise TelegramClientError(
                "unknown_api_error",
                "Telegram returned a response without a message ID.",
            )
        return str(result["message_id"])

    def send_long_message(self, chat_id: str | None, text: str, max_chars: int = 3500) -> list[str]:
        message_ids: list[str] = []
        for chunk in split_telegram_message(text, max_chars=max_chars):
            message_ids.append(self.send_message(chat_id, chunk))
        return message_ids

    def test_connection(self, chat_id: str | None) -> str:
        return self.send_message(
            chat_id,
            "Cognit Telegram setup test succeeded. Your bot can send alerts to this chat.",
        )

    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 30,
    ) -> list[dict[str, Any]]:
        self._ensure_token()
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset

        response = self._request("getUpdates", payload)
        result = response.get("result")
        if not isinstance(result, list):
            raise TelegramClientError(
                "unknown_api_error",
                "Telegram returned a response without an updates list.",
            )
        return [item for item in result if isinstance(item, dict)]

    def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.transport(method, self._build_url(method), payload, self.timeout)
        except TelegramClientError:
            raise
        except (TimeoutError, OSError, error.URLError) as exc:
            raise TelegramClientError("network_failure", "Telegram network request failed.") from exc

    def _build_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _ensure_token(self) -> None:
        if not self.token:
            raise TelegramClientError("missing_token", "Telegram bot token is missing.")

    def _ensure_chat_id(self, chat_id: str | None) -> None:
        if not chat_id:
            raise TelegramClientError("missing_chat_id", "Telegram chat ID is missing.")


def split_telegram_message(text: str, max_chars: int = 3500) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero.")
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        split_at = remaining.rfind("\n", 0, max_chars + 1)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _default_transport(method: str, url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    del method
    encoded = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return _parse_telegram_response(body, response.status)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise _classify_http_failure(status_code=exc.code, body=body) from exc


def _parse_telegram_response(body: str, status_code: int) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise TelegramClientError(
            "unknown_api_error",
            "Telegram returned invalid JSON.",
        ) from exc

    if status_code >= 400 or not payload.get("ok", False):
        raise _classify_payload_failure(payload, status_code)
    return payload


def _classify_http_failure(status_code: int, body: str) -> TelegramClientError:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {"description": body}
    return _classify_payload_failure(payload, status_code)


def _classify_payload_failure(payload: dict[str, Any], status_code: int) -> TelegramClientError:
    description = str(payload.get("description", "Telegram API request failed."))
    lowered = description.lower()

    if status_code == 401 or "unauthorized" in lowered or "invalid token" in lowered:
        return TelegramClientError("invalid_token", "Telegram bot token is invalid.")
    if status_code == 400 and any(
        term in lowered
        for term in (
            "chat not found",
            "user not found",
            "peer_id invalid",
            "chat_id is empty",
        )
    ):
        return TelegramClientError("wrong_chat_id", "Telegram chat ID is invalid or the bot cannot access it.")
    if status_code == 403 and any(
        term in lowered
        for term in (
            "blocked",
            "kicked",
            "can't initiate conversation",
            "have no rights to send a message",
        )
    ):
        return TelegramClientError("bot_blocked", "The Telegram bot was blocked by the target user or chat.")
    if status_code == 429 or "too many requests" in lowered or "retry after" in lowered:
        return TelegramClientError("rate_limit", "Telegram rate limited the bot request.")
    return TelegramClientError("unknown_api_error", f"Telegram API error: {description}")
