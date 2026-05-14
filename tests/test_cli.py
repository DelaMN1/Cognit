from __future__ import annotations

from pathlib import Path

from cognit import cli
from cognit.integrations.telegram import TelegramClientError
from cognit.service_verification import ServiceCheckResult


def test_test_telegram_success_output(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.TelegramClient,
        "test_connection",
        lambda self, chat_id: "1",
    )

    exit_code = cli.main(["test-telegram", "--token", "token", "--chat-id", "chat-1"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Telegram setup test succeeded" in output


def test_test_telegram_failure_output_and_exit_code(monkeypatch, capsys):
    def fail(self, chat_id):
        raise TelegramClientError("invalid_token", "Telegram bot token is invalid.")

    monkeypatch.setattr(cli.TelegramClient, "test_connection", fail)

    exit_code = cli.main(["test-telegram", "--token", "bad-token", "--chat-id", "chat-1"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Telegram setup test failed: invalid token." in output


def test_test_telegram_uses_dotenv_backed_runtime_values(monkeypatch, tmp_path: Path):
    captured: dict[str, str | None] = {}

    class FakeTelegramClient:
        def __init__(self, *, token):
            captured["token"] = token

        def test_connection(self, chat_id):
            captured["chat_id"] = chat_id
            return "1"

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "COGNIT_TELEGRAM_BOT_TOKEN=dotenv-token",
                "COGNIT_TELEGRAM_CHAT_ID=dotenv-chat",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("COGNIT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("COGNIT_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("COGNIT_APP_NAME", raising=False)
    monkeypatch.delenv("COGNIT_ENVIRONMENT", raising=False)
    monkeypatch.delenv("COGNIT_ENABLE_CAPTURE", raising=False)
    monkeypatch.delenv("COGNIT_TAGS", raising=False)
    monkeypatch.setattr(cli, "TelegramClient", FakeTelegramClient)

    result = cli.run_test_telegram()

    assert result.ok is True
    assert captured == {
        "token": "dotenv-token",
        "chat_id": "dotenv-chat",
    }


def test_root_help_still_parses():
    parser = cli.build_parser()
    args = parser.parse_args([])

    assert args.command is None


def test_verify_services_success_output(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "verify_ai_provider_service",
        lambda config, provider=None: ("Gemini", ServiceCheckResult(ok=True, summary="Connected successfully")),
    )
    monkeypatch.setattr(
        cli,
        "verify_telegram_delivery_service",
        lambda config: ServiceCheckResult(ok=True, summary="Test message sent successfully"),
    )

    exit_code = cli.main(["verify-services", "--provider", "gemini"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Cognit service verification" in output
    assert "Gemini:" in output
    assert "\u2705 Connected successfully" in output
    assert "Telegram:" in output
    assert "\u2705 Test message sent successfully" in output


def test_verify_services_failure_output_and_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "verify_ai_provider_service",
        lambda config, provider=None: (
            "OpenAI",
            ServiceCheckResult(
                ok=False,
                category="invalid_openai_api_key",
                summary="Invalid API key.",
                fix="Update COGNIT_OPENAI_API_KEY in your .env file, then rerun `cognit verify-services`.",
            ),
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_telegram_delivery_service",
        lambda config: ServiceCheckResult(
            ok=False,
            category="wrong_telegram_chat_id",
            summary="Wrong chat ID or bot cannot message this chat.",
            fix="Open Telegram, send a message to your bot first, confirm COGNIT_TELEGRAM_CHAT_ID, then rerun `cognit test-telegram`.",
        ),
    )

    exit_code = cli.main(["verify-services"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "\u274c Invalid API key." in output
    assert "\u274c Wrong chat ID or bot cannot message this chat." in output
    assert "Fix: Update COGNIT_OPENAI_API_KEY" in output
    assert "Fix: Open Telegram, send a message to your bot first" in output


def test_verify_services_uses_dotenv_backed_runtime_values(monkeypatch, tmp_path: Path):
    captured: dict[str, str | None] = {}

    def fake_verify_ai(config, provider=None):
        captured["provider"] = provider or config.ai_provider
        captured["openai_api_key"] = config.openai_api_key
        captured["gemini_api_key"] = config.gemini_api_key
        captured["gemini_model"] = config.gemini_model
        return "Gemini", ServiceCheckResult(ok=True, summary="Connected successfully")

    def fake_verify_telegram(config):
        captured["telegram_bot_token"] = config.telegram_bot_token
        captured["telegram_chat_id"] = config.telegram_chat_id
        return ServiceCheckResult(ok=True, summary="Test message sent successfully")

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "COGNIT_AI_PROVIDER=gemini",
                "COGNIT_OPENAI_API_KEY=dotenv-openai-key",
                "COGNIT_GEMINI_API_KEY=dotenv-gemini-key",
                "COGNIT_GEMINI_MODEL=gemini-2.5-flash",
                "COGNIT_TELEGRAM_BOT_TOKEN=dotenv-token",
                "COGNIT_TELEGRAM_CHAT_ID=dotenv-chat",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("COGNIT_AI_PROVIDER", raising=False)
    monkeypatch.delenv("COGNIT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("COGNIT_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("COGNIT_GEMINI_MODEL", raising=False)
    monkeypatch.delenv("COGNIT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("COGNIT_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(cli, "verify_ai_provider_service", fake_verify_ai)
    monkeypatch.setattr(cli, "verify_telegram_delivery_service", fake_verify_telegram)

    result = cli.run_verify_services()

    assert result.ok is True
    assert result.ai_label == "Gemini"
    assert captured == {
        "provider": "gemini",
        "openai_api_key": "dotenv-openai-key",
        "gemini_api_key": "dotenv-gemini-key",
        "gemini_model": "gemini-2.5-flash",
        "telegram_bot_token": "dotenv-token",
        "telegram_chat_id": "dotenv-chat",
    }


def test_verify_services_honors_provider_override(monkeypatch):
    captured: dict[str, str | None] = {}

    def fake_verify_ai(config, provider=None):
        captured["provider"] = provider
        return "Gemini", ServiceCheckResult(ok=True, summary="Connected successfully")

    monkeypatch.setattr(cli, "verify_ai_provider_service", fake_verify_ai)
    monkeypatch.setattr(
        cli,
        "verify_telegram_delivery_service",
        lambda config: ServiceCheckResult(ok=True, summary="Telegram alerts are disabled. Verification skipped."),
    )

    result = cli.run_verify_services(provider="gemini")

    assert result.ok is True
    assert captured["provider"] == "gemini"


def test_run_bot_once_invokes_single_poll_cycle(monkeypatch, capsys):
    captured: dict[str, object] = {}

    class FakeBot:
        def __init__(self, *, config, poll_timeout):
            captured["config"] = config
            captured["poll_timeout"] = poll_timeout

        def process_updates_once(self):
            captured["processed"] = True

    monkeypatch.setattr(cli, "TelegramFollowUpBot", FakeBot)

    exit_code = cli.main(["run-bot", "--once", "--poll-timeout", "12"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert captured["poll_timeout"] == 12
    assert captured["processed"] is True
    assert "Processed one Telegram poll cycle." in output
