"""Command-line interface for Cognit."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence

from cognit import __version__
from cognit.config import CognitConfig
from cognit.integrations.telegram import TelegramClient, TelegramClientError
from cognit.integrations.telegram_bot import TelegramFollowUpBot
from cognit.service_verification import (
    ServiceCheckResult,
    render_verify_services_report,
    verify_ai_provider_service,
    verify_telegram_delivery_service,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cognit",
        description="Capture Python logging incidents with Cognit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    test_telegram = subparsers.add_parser(
        "test-telegram",
        help="Send a Telegram test message using the configured bot token and chat ID.",
    )
    test_telegram.add_argument(
        "--token",
        default=None,
        help="Override COGNIT_TELEGRAM_BOT_TOKEN for this command.",
    )
    test_telegram.add_argument(
        "--chat-id",
        default=None,
        help="Override COGNIT_TELEGRAM_CHAT_ID for this command.",
    )
    verify_services = subparsers.add_parser(
        "verify-services",
        help="Verify the configured AI provider and Telegram services with safe manual checks.",
    )
    verify_services.add_argument(
        "--provider",
        choices=("openai", "gemini", "fallback"),
        default=None,
        help="Override COGNIT_AI_PROVIDER for this command.",
    )
    run_bot = subparsers.add_parser(
        "run-bot",
        help="Poll Telegram for /cognit follow-up commands.",
    )
    run_bot.add_argument(
        "--poll-timeout",
        type=int,
        default=30,
        help="Telegram long-poll timeout in seconds.",
    )
    run_bot.add_argument(
        "--once",
        action="store_true",
        help="Process a single Telegram poll cycle and exit.",
    )
    return parser


@dataclass(slots=True)
class TelegramTestCommandResult:
    ok: bool
    message: str
    category: str | None = None


@dataclass(slots=True)
class VerifyServicesCommandResult:
    ok: bool
    ai_label: str
    ai: ServiceCheckResult
    telegram: ServiceCheckResult
    message: str


@dataclass(slots=True)
class RunBotCommandResult:
    ok: bool
    message: str


def run_test_telegram(
    token: str | None = None,
    chat_id: str | None = None,
) -> TelegramTestCommandResult:
    config = CognitConfig.from_env()
    resolved_token = token if token is not None else config.telegram_bot_token
    resolved_chat_id = chat_id if chat_id is not None else config.telegram_chat_id
    client = TelegramClient(token=resolved_token)

    try:
        client.test_connection(resolved_chat_id)
    except TelegramClientError as exc:
        category = exc.category.replace("_", " ")
        return TelegramTestCommandResult(
            ok=False,
            category=exc.category,
            message=f"Telegram setup test failed: {category}. {exc}",
        )

    return TelegramTestCommandResult(
        ok=True,
        message="Telegram setup test succeeded. Cognit sent a test message to the configured chat.",
    )


def run_verify_services(provider: str | None = None) -> VerifyServicesCommandResult:
    config = CognitConfig.from_env()
    ai_label, ai_result = verify_ai_provider_service(config, provider=provider)
    telegram_result = verify_telegram_delivery_service(config)
    ok = ai_result.ok and telegram_result.ok
    return VerifyServicesCommandResult(
        ok=ok,
        ai_label=ai_label,
        ai=ai_result,
        telegram=telegram_result,
        message=render_verify_services_report(ai_label, ai_result, telegram_result),
    )


def run_bot_command(*, poll_timeout: int = 30, once: bool = False) -> RunBotCommandResult:
    bot = TelegramFollowUpBot(
        config=CognitConfig.from_env(),
        poll_timeout=poll_timeout,
    )
    if once:
        bot.process_updates_once()
        return RunBotCommandResult(ok=True, message="Processed one Telegram poll cycle.")

    try:
        bot.run_forever()
    except KeyboardInterrupt:
        return RunBotCommandResult(ok=True, message="Telegram follow-up bot stopped.")
    return RunBotCommandResult(ok=True, message="Telegram follow-up bot stopped.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "test-telegram":
        result = run_test_telegram(token=args.token, chat_id=args.chat_id)
        print(result.message)
        return 0 if result.ok else 1
    if args.command == "verify-services":
        result = run_verify_services(provider=args.provider)
        print(result.message)
        return 0 if result.ok else 1
    if args.command == "run-bot":
        result = run_bot_command(
            poll_timeout=args.poll_timeout,
            once=args.once,
        )
        print(result.message)
        return 0 if result.ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
