from __future__ import annotations

from types import SimpleNamespace

from cognit.ai import FallbackAnalyzer, OpenAIAnalyzer, analyze_with_fallback
from cognit.capture.event import LogEvent


def _event() -> LogEvent:
    return LogEvent(
        incident_id="cog_20260513_120000_abcdef",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message="request failed",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="app",
        function="explode",
        line_number=99,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="RuntimeError",
        exception_message="database down",
        traceback="Traceback...",
        fingerprint="fp-a",
    )


def test_missing_api_key_uses_fallback():
    analysis = analyze_with_fallback(
        _event(),
        analyzer=OpenAIAnalyzer(api_key=None),
        fallback=FallbackAnalyzer(),
    )

    assert analysis.severity == "high"
    assert "database down" in analysis.likely_cause
    assert analysis.suggested_steps


def test_missing_openai_package_uses_fallback(monkeypatch):
    def fake_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("missing openai")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fake_import)

    analysis = analyze_with_fallback(
        _event(),
        analyzer=OpenAIAnalyzer(api_key="test-key"),
        fallback=FallbackAnalyzer(),
    )

    assert analysis.summary.startswith("ERROR in demo")
    assert analysis.severity == "high"


def test_invalid_ai_response_uses_fallback():
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(output_text="not-json")
        )
    )

    analysis = analyze_with_fallback(
        _event(),
        analyzer=OpenAIAnalyzer(api_key="test-key", client=client),
        fallback=FallbackAnalyzer(),
    )

    assert analysis.likely_cause == "database down"
    assert analysis.follow_up_questions


def test_valid_ai_response_is_returned():
    payload = (
        '{"summary":"DB outage","likely_cause":"Pool exhausted","severity":"high",'
        '"affected_area":"orders","suggested_steps":["Check pool"],'
        '"possible_fix":"Increase pool size","similar_incidents_summary":null,'
        '"follow_up_questions":["Was traffic elevated?"]}'
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(output_text=payload)
        )
    )

    analysis = analyze_with_fallback(
        _event(),
        analyzer=OpenAIAnalyzer(api_key="test-key", client=client),
        fallback=FallbackAnalyzer(),
    )

    assert analysis.summary == "DB outage"
    assert analysis.likely_cause == "Pool exhausted"
    assert analysis.severity == "high"


def test_ai_prompt_is_redacted_before_provider_call():
    captured: dict[str, object] = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_text=(
                '{"summary":"Handled","likely_cause":"Input failed","severity":"high",'
                '"affected_area":"orders","suggested_steps":["Inspect logs"],'
                '"possible_fix":null,"similar_incidents_summary":null,'
                '"follow_up_questions":["Did config change?"]}'
            )
        )

    event = _event()
    event.message = "password=swordfish email=admin@example.com"
    event.exception_message = "redis://:secret@localhost:6379/0"
    client = SimpleNamespace(responses=SimpleNamespace(create=create))

    analysis = analyze_with_fallback(
        event,
        analyzer=OpenAIAnalyzer(api_key="test-key", client=client),
        fallback=FallbackAnalyzer(),
    )

    user_payload = captured["input"][1]["content"]
    assert "swordfish" not in user_payload
    assert "admin@example.com" not in user_payload
    assert "redis://:secret@localhost:6379/0" not in user_payload
    assert "[REDACTED_PASSWORD]" in user_payload
    assert "[REDACTED_EMAIL]" in user_payload
    assert "[REDACTED_DATABASE_URL]" in user_payload
    assert analysis.summary == "Handled"
