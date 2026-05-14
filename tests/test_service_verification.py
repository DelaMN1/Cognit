from __future__ import annotations

from dataclasses import dataclass

from cognit.config import CognitConfig
from cognit.service_verification import (
    ServiceCheckResult,
    render_verify_services_report,
    verify_ai_provider_service,
    verify_gemini_service,
    verify_openai_service,
    verify_telegram_delivery_service,
)


def test_verify_openai_service_success_with_max_output_tokens():
    calls: list[dict[str, object]] = []
    client_kwargs: list[dict[str, object]] = []

    class ResponsesClient:
        def create(self, **kwargs):
            calls.append(kwargs)
            return {"id": "resp_1"}

    class FakeClient:
        responses = ResponsesClient()

    config = CognitConfig(openai_api_key="sk-test-secret", openai_model="gpt-4.1-mini")
    result = verify_openai_service(
        config,
        client_factory=lambda **kwargs: client_kwargs.append(kwargs) or FakeClient(),
    )

    assert result.ok is True
    assert result.summary == "Connected successfully"
    assert client_kwargs == [{"api_key": "sk-test-secret"}]
    assert calls[0]["max_output_tokens"] >= 16


def test_verify_openai_service_retries_without_max_output_tokens_when_unsupported():
    calls: list[dict[str, object]] = []

    class ResponsesClient:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise TypeError("create() got an unexpected keyword argument 'max_output_tokens'")
            return {"id": "resp_2"}

    class FakeClient:
        responses = ResponsesClient()

    config = CognitConfig(openai_api_key="sk-test-secret", openai_model="gpt-4.1-mini")
    result = verify_openai_service(config, client_factory=lambda **kwargs: FakeClient())

    assert result.ok is True
    assert calls[0]["max_output_tokens"] >= 16
    assert calls[1] == {
        "model": "gpt-4.1-mini",
        "input": "Reply with exactly: ok",
    }


def test_verify_openai_service_classifies_missing_sdk():
    config = CognitConfig(openai_api_key="sk-test-secret")
    result = verify_openai_service(
        config,
        client_factory=lambda **kwargs: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'openai'")),
    )

    assert result.ok is False
    assert result.category == "missing_openai_sdk"
    assert result.summary == "OpenAI SDK is not installed."


def test_verify_gemini_service_success():
    calls: list[dict[str, object]] = []

    class ModelsClient:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return {"text": "ok"}

    class FakeClient:
        models = ModelsClient()

    config = CognitConfig(gemini_api_key="gemini-key", gemini_model="gemini-2.5-flash")
    result = verify_gemini_service(config, client_factory=lambda **kwargs: FakeClient())

    assert result.ok is True
    assert calls == [
        {
            "model": "gemini-2.5-flash",
            "contents": "Reply with exactly: ok",
        }
    ]


def test_verify_gemini_service_classifies_missing_sdk():
    config = CognitConfig(gemini_api_key="gemini-key")
    result = verify_gemini_service(
        config,
        client_factory=lambda **kwargs: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'google.genai'")),
    )

    assert result.category == "missing_gemini_sdk"
    assert result.summary == "Gemini SDK is not installed."


def test_verify_gemini_service_classifies_authentication_error():
    class AuthError(Exception):
        status_code = 401

    config = CognitConfig(gemini_api_key="gemini-key")
    result = verify_gemini_service(
        config,
        client_factory=lambda **kwargs: _gemini_client_raising(AuthError("invalid api key")),
    )

    assert result.category == "invalid_gemini_api_key"
    assert result.summary == "Invalid API key or authentication failed."


def test_verify_gemini_service_classifies_permission_error():
    class PermissionError(Exception):
        status_code = 403

    config = CognitConfig(gemini_api_key="gemini-key")
    result = verify_gemini_service(
        config,
        client_factory=lambda **kwargs: _gemini_client_raising(PermissionError("quota exceeded")),
    )

    assert result.category == "gemini_permission_or_quota_error"
    assert result.summary == "Permission, quota, or billing error."


def test_verify_gemini_service_classifies_model_error():
    class NotFoundError(Exception):
        status_code = 404

    config = CognitConfig(gemini_api_key="gemini-key", gemini_model="bad-model")
    result = verify_gemini_service(
        config,
        client_factory=lambda **kwargs: _gemini_client_raising(NotFoundError("model not found")),
    )

    assert result.category == "invalid_gemini_model"
    assert result.summary == "Invalid model name or model access denied."


def test_verify_gemini_service_classifies_rate_limit():
    class RateLimitError(Exception):
        status_code = 429

    config = CognitConfig(gemini_api_key="gemini-key")
    result = verify_gemini_service(
        config,
        client_factory=lambda **kwargs: _gemini_client_raising(RateLimitError("rate limit exceeded")),
    )

    assert result.category == "gemini_rate_limit"
    assert result.summary == "Rate limited by Gemini."


def test_verify_gemini_service_classifies_timeout():
    config = CognitConfig(gemini_api_key="gemini-key")
    result = verify_gemini_service(
        config,
        client_factory=lambda **kwargs: _gemini_client_raising(TimeoutError("request timed out")),
    )

    assert result.category == "gemini_timeout"
    assert result.summary == "Gemini request timed out."


def test_verify_gemini_service_classifies_network_failure():
    config = CognitConfig(gemini_api_key="gemini-key")
    result = verify_gemini_service(
        config,
        client_factory=lambda **kwargs: _gemini_client_raising(RuntimeError("network connection failure")),
    )

    assert result.category == "gemini_network_failure"
    assert result.summary == "Gemini network or API connection failure."


def test_verify_gemini_service_reports_unexpected_error_with_sanitized_message():
    config = CognitConfig(gemini_api_key="gemini-secret-key")
    result = verify_gemini_service(
        config,
        client_factory=lambda **kwargs: _gemini_client_raising(
            RuntimeError("provider exploded for gemini-secret-key and sk-anothersecretvalue1234567890")
        ),
    )

    assert result.category == "unexpected_provider_error"
    assert result.summary.startswith("Unexpected provider error (RuntimeError): ")
    assert "gemini-secret-key" not in result.summary
    assert "sk-anothersecretvalue1234567890" not in result.summary
    assert "[REDACTED_SECRET]" in result.summary
    assert "[REDACTED_API_KEY]" in result.summary


def test_verify_ai_provider_service_skips_in_fallback_mode():
    label, result = verify_ai_provider_service(CognitConfig(ai_provider="fallback"))

    assert label == "AI Provider"
    assert result.ok is True
    assert "Fallback mode is active" in result.summary


def test_verify_telegram_delivery_service_skips_when_disabled():
    result = verify_telegram_delivery_service(CognitConfig(enable_telegram_alerts=False))

    assert result.ok is True
    assert result.category == "telegram_disabled"


def test_render_verify_services_report_uses_provider_label():
    report = render_verify_services_report(
        "Gemini",
        ServiceCheckResult(ok=True, summary="Connected successfully"),
        ServiceCheckResult(ok=True, summary="Test message sent successfully"),
    )

    assert "Gemini:" in report
    assert "Telegram:" in report


@dataclass
class _GeminiRaisingClient:
    error: Exception

    @property
    def models(self):
        return _GeminiRaisingModels(self.error)


@dataclass
class _GeminiRaisingModels:
    error: Exception

    def generate_content(self, **kwargs):
        del kwargs
        raise self.error


def _gemini_client_raising(error: Exception) -> _GeminiRaisingClient:
    return _GeminiRaisingClient(error=error)
