"""Configuration helpers for Cognit."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from cognit.constants import DEFAULT_APP_NAME, DEFAULT_ENVIRONMENT


def _load_dotenv_if_available(dotenv_path: str | os.PathLike[str] | None = None) -> None:
    resolved_path = Path(dotenv_path) if dotenv_path is not None else Path(".env")
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        _load_simple_dotenv(resolved_path)
        return

    load_dotenv(dotenv_path=resolved_path)


def _load_simple_dotenv(dotenv_path: str | os.PathLike[str] | None = None) -> None:
    candidate = Path(dotenv_path) if dotenv_path is not None else Path(".env")
    if not candidate.exists() or not candidate.is_file():
        return

    for raw_line in candidate.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _to_bool(value: str | bool | None, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_tags(raw_tags: str | None) -> dict[str, str]:
    if not raw_tags:
        return {}

    tags: dict[str, str] = {}
    for part in raw_tags.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" in item:
            key, value = item.split(":", 1)
            tags[key.strip()] = value.strip()
        else:
            tags[item] = "true"
    return tags


def _to_int(value: str | int | None, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _parse_list(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


@dataclass(slots=True)
class CognitConfig:
    """Runtime configuration for Cognit."""

    app_name: str = DEFAULT_APP_NAME
    environment: str = DEFAULT_ENVIRONMENT
    enable_capture: bool = True
    tags: dict[str, str] = field(default_factory=dict)
    ai_provider: str = "openai"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    enable_ai_analysis: bool = True
    enable_telegram_alerts: bool = True
    enable_deduplication: bool = True
    dedupe_window_seconds: int = 300
    enable_rate_limiting: bool = True
    telegram_alert_limit: int = 10
    telegram_alert_window_seconds: int = 60
    max_followup_context_chars: int = 6000
    max_conversation_history_messages: int = 4
    max_similar_incidents_for_followup: int = 2
    max_similar_incident_chars: int = 800
    custom_redaction_patterns: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, dotenv_path: str | os.PathLike[str] | None = None) -> "CognitConfig":
        _load_dotenv_if_available(dotenv_path)

        return cls(
            app_name=os.getenv("COGNIT_APP_NAME", DEFAULT_APP_NAME),
            environment=os.getenv("COGNIT_ENVIRONMENT", DEFAULT_ENVIRONMENT),
            enable_capture=_to_bool(
                os.getenv("COGNIT_ENABLE_CAPTURE"),
                default=True,
            ),
            tags=_parse_tags(os.getenv("COGNIT_TAGS")),
            ai_provider=os.getenv("COGNIT_AI_PROVIDER", "openai").strip().lower() or "openai",
            openai_api_key=os.getenv("COGNIT_OPENAI_API_KEY"),
            openai_model=os.getenv("COGNIT_OPENAI_MODEL", "gpt-4.1-mini"),
            openai_embedding_model=os.getenv("COGNIT_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            gemini_api_key=os.getenv("COGNIT_GEMINI_API_KEY"),
            gemini_model=os.getenv("COGNIT_GEMINI_MODEL", "gemini-2.5-flash"),
            telegram_bot_token=os.getenv("COGNIT_TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("COGNIT_TELEGRAM_CHAT_ID"),
            enable_ai_analysis=_to_bool(
                os.getenv("COGNIT_ENABLE_AI_ANALYSIS"),
                default=True,
            ),
            enable_telegram_alerts=_to_bool(
                os.getenv("COGNIT_ENABLE_TELEGRAM_ALERTS"),
                default=True,
            ),
            enable_deduplication=_to_bool(
                os.getenv("COGNIT_ENABLE_DEDUPLICATION"),
                default=True,
            ),
            dedupe_window_seconds=_to_int(
                os.getenv("COGNIT_DEDUPE_WINDOW_SECONDS"),
                default=300,
            ),
            enable_rate_limiting=_to_bool(
                os.getenv("COGNIT_ENABLE_RATE_LIMITING"),
                default=True,
            ),
            telegram_alert_limit=_to_int(
                os.getenv("COGNIT_TELEGRAM_ALERT_LIMIT"),
                default=10,
            ),
            telegram_alert_window_seconds=_to_int(
                os.getenv("COGNIT_TELEGRAM_ALERT_WINDOW_SECONDS"),
                default=60,
            ),
            max_followup_context_chars=_to_int(
                os.getenv("COGNIT_MAX_FOLLOWUP_CONTEXT_CHARS"),
                default=6000,
            ),
            max_conversation_history_messages=_to_int(
                os.getenv("COGNIT_MAX_CONVERSATION_HISTORY_MESSAGES"),
                default=4,
            ),
            max_similar_incidents_for_followup=_to_int(
                os.getenv("COGNIT_MAX_SIMILAR_INCIDENTS_FOR_FOLLOWUP"),
                default=2,
            ),
            max_similar_incident_chars=_to_int(
                os.getenv("COGNIT_MAX_SIMILAR_INCIDENT_CHARS"),
                default=800,
            ),
            custom_redaction_patterns=_parse_list(os.getenv("COGNIT_REDACTION_PATTERNS")),
        )

    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> "CognitConfig":
        return cls.from_env(Path(path))
