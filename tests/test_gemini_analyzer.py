from __future__ import annotations

from types import SimpleNamespace

from cognit.ai import FallbackAnalyzer, GeminiAnalyzer, analyze_with_fallback, build_analyzer
from cognit.capture.event import LogEvent
from cognit.config import CognitConfig


def _event() -> LogEvent:
    return LogEvent(
        incident_id="cog_20260513_120000_abcdef",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message="password=swordfish request failed",
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
        exception_message="redis://:secret@localhost:6379/0",
        traceback="Traceback...",
        fingerprint="fp-a",
    )


def test_missing_gemini_api_key_uses_fallback():
    analysis = analyze_with_fallback(
        _event(),
        analyzer=GeminiAnalyzer(api_key=""),
        fallback=FallbackAnalyzer(),
    )

    assert analysis.severity == "high"
    assert "request failed" in analysis.summary


def test_missing_gemini_package_uses_fallback(monkeypatch):
    def fake_import(name, *args, **kwargs):
        if name == "google":
            raise ImportError("missing google.genai")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fake_import)

    analysis = analyze_with_fallback(
        _event(),
        analyzer=GeminiAnalyzer(api_key="gemini-key"),
        fallback=FallbackAnalyzer(),
    )

    assert analysis.severity == "high"
    assert analysis.suggested_steps


def test_invalid_gemini_json_uses_fallback():
    client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kwargs: SimpleNamespace(text="not-json")
        )
    )

    analysis = analyze_with_fallback(
        _event(),
        analyzer=GeminiAnalyzer(api_key="gemini-key", client=client),
        fallback=FallbackAnalyzer(),
    )

    assert analysis.likely_cause == "[REDACTED_DATABASE_URL]"


def test_gemini_response_with_code_fence_is_parsed():
    payload = (
        "```json\n"
        '{"summary":"DB outage","likely_cause":"Pool exhausted","severity":"high",'
        '"affected_area":"orders","suggested_steps":["Check pool"],'
        '"possible_fix":"Increase pool size","similar_incidents_summary":null,'
        '"follow_up_questions":["Was traffic elevated?"]}\n'
        "```"
    )
    client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kwargs: SimpleNamespace(text=payload)
        )
    )

    analysis = analyze_with_fallback(
        _event(),
        analyzer=GeminiAnalyzer(api_key="gemini-key", client=client),
        fallback=FallbackAnalyzer(),
    )

    assert analysis.summary == "DB outage"
    assert analysis.likely_cause == "Pool exhausted"
    assert analysis.severity == "high"


def test_gemini_prompt_is_redacted_before_provider_call():
    captured: dict[str, object] = {}

    def generate_content(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            text=(
                '{"summary":"Handled","likely_cause":"Input failed","severity":"high",'
                '"affected_area":"orders","suggested_steps":["Inspect logs"],'
                '"possible_fix":null,"similar_incidents_summary":null,'
                '"follow_up_questions":["Did config change?"]}'
            )
        )

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

    analysis = analyze_with_fallback(
        _event(),
        analyzer=GeminiAnalyzer(api_key="gemini-key", client=client),
        fallback=FallbackAnalyzer(),
    )

    contents = captured["contents"]
    assert "swordfish" not in contents
    assert "redis://:secret@localhost:6379/0" not in contents
    assert "[REDACTED_PASSWORD]" in contents
    assert "[REDACTED_DATABASE_URL]" in contents
    assert analysis.summary == "Handled"


def test_build_analyzer_selects_gemini_provider():
    analyzer = build_analyzer(
        CognitConfig(
            ai_provider="gemini",
            gemini_api_key="gemini-key",
            gemini_model="gemini-2.5-flash",
        )
    )

    assert isinstance(analyzer, GeminiAnalyzer)


def test_build_analyzer_returns_none_for_fallback():
    analyzer = build_analyzer(CognitConfig(ai_provider="fallback"))

    assert analyzer is None
