from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from cognit.config import CognitConfig


def _clear_cognit_env(monkeypatch) -> None:
    for key in (
        "COGNIT_APP_NAME",
        "COGNIT_ENVIRONMENT",
        "COGNIT_ENABLE_CAPTURE",
        "COGNIT_TAGS",
        "COGNIT_AI_PROVIDER",
        "COGNIT_TELEGRAM_BOT_TOKEN",
        "COGNIT_TELEGRAM_CHAT_ID",
        "COGNIT_OPENAI_API_KEY",
        "COGNIT_OPENAI_MODEL",
        "COGNIT_OPENAI_EMBEDDING_MODEL",
        "COGNIT_GEMINI_API_KEY",
        "COGNIT_GEMINI_MODEL",
        "COGNIT_ENABLE_AI_ANALYSIS",
        "COGNIT_ENABLE_TELEGRAM_ALERTS",
        "COGNIT_DEDUPE_WINDOW_SECONDS",
        "COGNIT_ENABLE_DEDUPLICATION",
        "COGNIT_ENABLE_RATE_LIMITING",
        "COGNIT_TELEGRAM_ALERT_LIMIT",
        "COGNIT_TELEGRAM_ALERT_WINDOW_SECONDS",
        "COGNIT_REDACTION_PATTERNS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_config_uses_defaults_when_env_missing(monkeypatch, tmp_path: Path):
    _clear_cognit_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    config = CognitConfig.from_env()

    assert config.app_name == "cognit-app"
    assert config.environment == "development"
    assert config.enable_capture is True
    assert config.tags == {}
    assert config.ai_provider == "openai"
    assert config.telegram_bot_token is None
    assert config.openai_api_key is None
    assert config.openai_embedding_model == "text-embedding-3-small"
    assert config.gemini_api_key is None
    assert config.gemini_model == "gemini-2.5-flash"
    assert config.enable_telegram_alerts is True


def test_config_loads_from_dotenv_path(tmp_path: Path, monkeypatch):
    _clear_cognit_env(monkeypatch)

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "COGNIT_APP_NAME=payments",
                "COGNIT_ENVIRONMENT=production",
                "COGNIT_ENABLE_CAPTURE=false",
                "COGNIT_TAGS=team:platform,service:billing",
                "COGNIT_AI_PROVIDER=gemini",
                "COGNIT_TELEGRAM_BOT_TOKEN=dotenv-token",
                "COGNIT_TELEGRAM_CHAT_ID=dotenv-chat",
                "COGNIT_OPENAI_API_KEY=dotenv-openai-key",
                "COGNIT_OPENAI_MODEL=gpt-5-mini",
                "COGNIT_GEMINI_API_KEY=dotenv-gemini-key",
                "COGNIT_GEMINI_MODEL=gemini-2.5-flash",
                "COGNIT_ENABLE_TELEGRAM_ALERTS=false",
                "COGNIT_DEDUPE_WINDOW_SECONDS=120",
            ]
        ),
        encoding="utf-8",
    )

    config = CognitConfig.from_path(dotenv_path)

    assert config.app_name == "payments"
    assert config.environment == "production"
    assert config.enable_capture is False
    assert config.tags == {"team": "platform", "service": "billing"}
    assert config.ai_provider == "gemini"
    assert config.telegram_bot_token == "dotenv-token"
    assert config.telegram_chat_id == "dotenv-chat"
    assert config.openai_api_key == "dotenv-openai-key"
    assert config.openai_model == "gpt-5-mini"
    assert config.gemini_api_key == "dotenv-gemini-key"
    assert config.gemini_model == "gemini-2.5-flash"
    assert config.enable_telegram_alerts is False
    assert config.dedupe_window_seconds == 120


def test_dotenv_is_not_loaded_at_import_time(tmp_path: Path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "COGNIT_TELEGRAM_BOT_TOKEN=import-time-token\n",
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("COGNIT_TELEGRAM_BOT_TOKEN", None)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(repo_root) if not existing_pythonpath else os.pathsep.join([str(repo_root), existing_pythonpath])
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import cognit.cli; print(os.getenv('COGNIT_TELEGRAM_BOT_TOKEN', ''))",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == ""
