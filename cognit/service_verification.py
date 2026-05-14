"""Manual external service verification helpers."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Any, Callable

from cognit.config import CognitConfig
from cognit.integrations.telegram import TelegramClient, TelegramClientError
from cognit.redaction.patterns import DEFAULT_REDACTION_RULES

OpenAIClientFactory = Callable[..., Any]
GeminiClientFactory = Callable[..., Any]


@dataclass(slots=True)
class ServiceCheckResult:
    ok: bool
    summary: str
    category: str | None = None
    fix: str | None = None


def verify_ai_provider_service(
    config: CognitConfig,
    *,
    provider: str | None = None,
    openai_client_factory: OpenAIClientFactory | None = None,
    gemini_client_factory: GeminiClientFactory | None = None,
) -> tuple[str, ServiceCheckResult]:
    selected_provider = (provider or config.ai_provider or "openai").strip().lower()
    if selected_provider == "openai":
        return "OpenAI", verify_openai_service(config, client_factory=openai_client_factory)
    if selected_provider == "gemini":
        return "Gemini", verify_gemini_service(config, client_factory=gemini_client_factory)
    if selected_provider == "fallback":
        return (
            "AI Provider",
            ServiceCheckResult(
                ok=True,
                category="fallback_active",
                summary="Fallback mode is active. External AI provider verification skipped.",
            ),
        )
    return (
        "AI Provider",
        ServiceCheckResult(
            ok=False,
            category="invalid_ai_provider",
            summary=f"Unsupported AI provider: {selected_provider}.",
            fix="Set COGNIT_AI_PROVIDER to `openai`, `gemini`, or `fallback`, then rerun `cognit verify-services`.",
        ),
    )


def verify_openai_service(
    config: CognitConfig,
    *,
    client_factory: OpenAIClientFactory | None = None,
) -> ServiceCheckResult:
    if not config.openai_api_key:
        return ServiceCheckResult(
            ok=False,
            category="missing_openai_api_key",
            summary="Missing API key.",
            fix="Set COGNIT_OPENAI_API_KEY in your .env file, then rerun `cognit verify-services`.",
        )

    build_client = client_factory or _build_openai_client
    try:
        client = build_client(api_key=config.openai_api_key)
        _run_openai_verification_request(client, model=config.openai_model)
    except Exception as exc:
        return _openai_failure_result(exc, api_key=config.openai_api_key)

    return ServiceCheckResult(
        ok=True,
        summary="Connected successfully",
    )


def verify_gemini_service(
    config: CognitConfig,
    *,
    client_factory: GeminiClientFactory | None = None,
) -> ServiceCheckResult:
    if not config.gemini_api_key:
        return ServiceCheckResult(
            ok=False,
            category="missing_gemini_api_key",
            summary="Missing API key.",
            fix="Set COGNIT_GEMINI_API_KEY in your .env file, then rerun `cognit verify-services --provider gemini`.",
        )

    build_client = client_factory or _build_gemini_client
    try:
        client = build_client(api_key=config.gemini_api_key)
        client.models.generate_content(
            model=config.gemini_model,
            contents="Reply with exactly: ok",
        )
    except Exception as exc:
        return _gemini_failure_result(exc, api_key=config.gemini_api_key)

    return ServiceCheckResult(
        ok=True,
        summary="Connected successfully",
    )


def verify_telegram_delivery_service(
    config: CognitConfig,
    *,
    client_factory: Callable[..., TelegramClient] = TelegramClient,
) -> ServiceCheckResult:
    if not config.enable_telegram_alerts:
        return ServiceCheckResult(
            ok=True,
            category="telegram_disabled",
            summary="Telegram alerts are disabled. Verification skipped.",
        )

    if not config.telegram_bot_token:
        return ServiceCheckResult(
            ok=False,
            category="missing_telegram_bot_token",
            summary="Missing bot token.",
            fix="Set COGNIT_TELEGRAM_BOT_TOKEN in your .env file, then rerun `cognit verify-services`.",
        )

    if not config.telegram_chat_id:
        return ServiceCheckResult(
            ok=False,
            category="missing_telegram_chat_id",
            summary="Missing chat ID.",
            fix="Set COGNIT_TELEGRAM_CHAT_ID in your .env file, then rerun `cognit verify-services`.",
        )

    client = client_factory(token=config.telegram_bot_token)
    try:
        client.send_message(config.telegram_chat_id, "Cognit verify-services test.")
    except TelegramClientError as exc:
        return _telegram_failure_result(exc.category)

    return ServiceCheckResult(
        ok=True,
        summary="Test message sent successfully",
    )


def render_verify_services_report(
    ai_label: str,
    ai_result: ServiceCheckResult,
    telegram_result: ServiceCheckResult,
) -> str:
    return "\n".join(
        [
            "Cognit service verification",
            "",
            f"{ai_label}:",
            _render_service_line(ai_result),
            *(_render_fix(ai_result.fix)),
            "",
            "Telegram:",
            _render_service_line(telegram_result),
            *(_render_fix(telegram_result.fix)),
        ]
    )


def _render_service_line(result: ServiceCheckResult) -> str:
    prefix = _status_prefix(ok=result.ok)
    return f"{prefix} {result.summary}"


def _status_prefix(*, ok: bool) -> str:
    preferred = "\u2705" if ok else "\u274c"
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        preferred.encode(encoding)
    except UnicodeEncodeError:
        return "OK" if ok else "X"
    return preferred


def _render_fix(fix: str | None) -> list[str]:
    if not fix:
        return []
    return [f"Fix: {fix}"]


def _build_openai_client(*, api_key: str) -> Any:
    from openai import OpenAI  # type: ignore

    return OpenAI(api_key=api_key)


def _build_gemini_client(*, api_key: str) -> Any:
    from google import genai  # type: ignore

    return genai.Client(api_key=api_key)


def _run_openai_verification_request(client: Any, *, model: str) -> None:
    try:
        client.responses.create(
            model=model,
            input="Reply with exactly: ok",
            max_output_tokens=16,
        )
    except TypeError as exc:
        if _mentions_max_output_tokens(exc):
            client.responses.create(
                model=model,
                input="Reply with exactly: ok",
            )
            return
        raise


def _mentions_max_output_tokens(exc: TypeError) -> bool:
    message = str(exc).lower()
    return "max_output_tokens" in message or "unexpected keyword argument" in message


def _classify_openai_error(exc: Exception) -> str:
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "missing_openai_sdk"

    status_code = getattr(exc, "status_code", None)
    message = str(exc).lower()
    error_name = type(exc).__name__.lower()

    if status_code == 401 or error_name == "authenticationerror":
        return "invalid_openai_api_key"
    if any(
        term in message
        for term in (
            "incorrect api key",
            "invalid api key",
            "authentication",
            "unauthorized",
            "invalid_api_key",
        )
    ):
        return "invalid_openai_api_key"

    if status_code == 403 or error_name == "permissiondeniederror":
        return "openai_permission_or_billing_error"
    if "insufficient_quota" in message or "billing" in message or "permission" in message:
        return "openai_permission_or_billing_error"
    if "quota" in message and "rate limit" not in message:
        return "openai_permission_or_billing_error"

    if status_code == 404 or error_name == "notfounderror":
        if "model" in message or "does not exist" in message or "not found" in message:
            return "invalid_openai_model"
    if "invalid model" in message or "model" in message and "not found" in message:
        return "invalid_openai_model"
    if "model" in message and "does not exist" in message:
        return "invalid_openai_model"

    if status_code == 429 or error_name == "ratelimiterror":
        return "openai_rate_limit"
    if "rate limit" in message or "too many requests" in message:
        return "openai_rate_limit"

    if error_name in {"apitimeouterror", "timeout"} or isinstance(exc, TimeoutError):
        return "openai_timeout"
    if "timed out" in message or "timeout" in message:
        return "openai_timeout"

    if error_name == "apiconnectionerror":
        return "openai_network_failure"
    if any(
        term in message
        for term in (
            "connection",
            "network",
            "dns",
            "connection reset",
            "connection aborted",
        )
    ):
        return "openai_network_failure"

    return "unexpected_provider_error"


def _classify_gemini_error(exc: Exception) -> str:
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "missing_gemini_sdk"

    status_code = getattr(exc, "status_code", None)
    message = str(exc).lower()
    error_name = type(exc).__name__.lower()

    if status_code == 401 or "api key" in message or "unauthorized" in message or "authentication" in message:
        return "invalid_gemini_api_key"
    if status_code == 403 or "permission" in message or "quota" in message or "billing" in message:
        return "gemini_permission_or_quota_error"
    if status_code == 404 or "model" in message and any(
        term in message for term in ("not found", "invalid", "unsupported", "unavailable")
    ):
        return "invalid_gemini_model"
    if status_code == 429 or "rate limit" in message or "too many requests" in message:
        return "gemini_rate_limit"
    if isinstance(exc, TimeoutError) or error_name in {"apitimeouterror", "timeout"}:
        return "gemini_timeout"
    if "timeout" in message or "timed out" in message:
        return "gemini_timeout"
    if any(term in message for term in ("network", "connection", "dns", "socket")):
        return "gemini_network_failure"
    return "unexpected_provider_error"


def _openai_failure_result(exc: Exception, *, api_key: str) -> ServiceCheckResult:
    category = _classify_openai_error(exc)

    if category == "missing_openai_sdk":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="OpenAI SDK is not installed.",
            fix="Install the optional OpenAI dependency, then rerun `cognit verify-services`.",
        )
    if category == "invalid_openai_api_key":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Invalid API key or authentication failed.",
            fix="Update COGNIT_OPENAI_API_KEY in your .env file, then rerun `cognit verify-services`.",
        )
    if category == "openai_permission_or_billing_error":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Permission, billing, or project access error.",
            fix="Confirm your OpenAI account, project access, and billing status, then rerun `cognit verify-services`.",
        )
    if category == "invalid_openai_model":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Invalid model name or model access denied.",
            fix="Update COGNIT_OPENAI_MODEL to a valid model your account can access, then rerun `cognit verify-services`.",
        )
    if category == "openai_rate_limit":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Rate limited by OpenAI.",
            fix="Wait briefly, then rerun `cognit verify-services`.",
        )
    if category == "openai_timeout":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="OpenAI request timed out.",
            fix="Retry in a moment. If it persists, check your network path to OpenAI and rerun `cognit verify-services`.",
        )
    if category == "openai_network_failure":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="OpenAI network or API connection failure.",
            fix="Check your network access to OpenAI, then rerun `cognit verify-services`.",
        )

    sanitized = _sanitize_provider_message(str(exc), secret_values=[api_key])
    return ServiceCheckResult(
        ok=False,
        category=category,
        summary=f"Unexpected provider error ({type(exc).__name__}): {sanitized}",
        fix="Review the provider error above, then rerun `cognit verify-services`.",
    )


def _gemini_failure_result(exc: Exception, *, api_key: str) -> ServiceCheckResult:
    category = _classify_gemini_error(exc)

    if category == "missing_gemini_sdk":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Gemini SDK is not installed.",
            fix="Install the optional Gemini dependency, then rerun `cognit verify-services --provider gemini`.",
        )
    if category == "invalid_gemini_api_key":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Invalid API key or authentication failed.",
            fix="Update COGNIT_GEMINI_API_KEY in your .env file, then rerun `cognit verify-services --provider gemini`.",
        )
    if category == "gemini_permission_or_quota_error":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Permission, quota, or billing error.",
            fix="Confirm your Gemini project access, quota, and billing state, then rerun `cognit verify-services --provider gemini`.",
        )
    if category == "invalid_gemini_model":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Invalid model name or model access denied.",
            fix="Update COGNIT_GEMINI_MODEL to a valid Gemini model your account can access, then rerun `cognit verify-services --provider gemini`.",
        )
    if category == "gemini_rate_limit":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Rate limited by Gemini.",
            fix="Wait briefly, then rerun `cognit verify-services --provider gemini`.",
        )
    if category == "gemini_timeout":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Gemini request timed out.",
            fix="Retry in a moment. If it persists, check your network path to Gemini and rerun `cognit verify-services --provider gemini`.",
        )
    if category == "gemini_network_failure":
        return ServiceCheckResult(
            ok=False,
            category=category,
            summary="Gemini network or API connection failure.",
            fix="Check your network access to Gemini, then rerun `cognit verify-services --provider gemini`.",
        )

    sanitized = _sanitize_provider_message(str(exc), secret_values=[api_key])
    return ServiceCheckResult(
        ok=False,
        category=category,
        summary=f"Unexpected provider error ({type(exc).__name__}): {sanitized}",
        fix="Review the provider error above, then rerun `cognit verify-services --provider gemini`.",
    )


def _sanitize_provider_message(message: str, *, secret_values: list[str]) -> str:
    sanitized = message
    for secret in secret_values:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED_SECRET]")

    for rule in DEFAULT_REDACTION_RULES:
        sanitized = rule.compile().sub(rule.placeholder, sanitized)

    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    if not sanitized:
        return "No provider error message was returned."
    return sanitized


def _telegram_failure_result(category: str) -> ServiceCheckResult:
    if category == "missing_token":
        return ServiceCheckResult(
            ok=False,
            category="missing_telegram_bot_token",
            summary="Missing bot token.",
            fix="Set COGNIT_TELEGRAM_BOT_TOKEN in your .env file, then rerun `cognit verify-services`.",
        )
    if category == "missing_chat_id":
        return ServiceCheckResult(
            ok=False,
            category="missing_telegram_chat_id",
            summary="Missing chat ID.",
            fix="Set COGNIT_TELEGRAM_CHAT_ID in your .env file, then rerun `cognit verify-services`.",
        )
    if category == "invalid_token":
        return ServiceCheckResult(
            ok=False,
            category="invalid_telegram_bot_token",
            summary="Invalid bot token.",
            fix="Update COGNIT_TELEGRAM_BOT_TOKEN in your .env file, then rerun `cognit verify-services`.",
        )
    if category == "wrong_chat_id":
        return ServiceCheckResult(
            ok=False,
            category="wrong_telegram_chat_id",
            summary="Wrong chat ID or bot cannot message this chat.",
            fix="Open Telegram, send a message to your bot first, confirm COGNIT_TELEGRAM_CHAT_ID, then rerun `cognit test-telegram`.",
        )
    if category == "bot_blocked":
        return ServiceCheckResult(
            ok=False,
            category="bot_blocked",
            summary="Bot is blocked by this chat.",
            fix="Unblock the bot or add it back to the target chat, then rerun `cognit test-telegram`.",
        )
    if category == "rate_limit":
        return ServiceCheckResult(
            ok=False,
            category="telegram_rate_limit",
            summary="Rate limited by Telegram.",
            fix="Wait briefly, then rerun `cognit test-telegram` or `cognit verify-services`.",
        )
    if category == "network_failure":
        return ServiceCheckResult(
            ok=False,
            category="telegram_network_failure",
            summary="Network request failed.",
            fix="Check your network access to Telegram, then rerun `cognit verify-services`.",
        )
    return ServiceCheckResult(
        ok=False,
        category="unknown_provider_error",
        summary="Unknown provider error.",
        fix="Check the Telegram bot configuration and rerun `cognit verify-services`.",
    )
