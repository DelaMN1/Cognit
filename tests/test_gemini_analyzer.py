from __future__ import annotations

from types import SimpleNamespace

from cognit.ai import FallbackAnalyzer, GeminiAnalyzer, analyze_with_fallback, build_analyzer
from cognit.ai.prompts import build_follow_up_user_prompt
from cognit.capture.event import LogEvent
from cognit.config import CognitConfig
from cognit.storage.models import StoredConversationMessage, StoredIncident


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


def test_follow_up_prompt_includes_latest_user_question():
    captured: dict[str, object] = {}

    def generate_content(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text="Direct answer")

    incident = StoredIncident(
        incident_id="cog_followup",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message='payment parser rejected amount "GHS 250"',
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/manual_bot_test.py",
        filename="manual_bot_test.py",
        module="manual_bot_test",
        function="explode",
        line_number=42,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="ValueError",
        exception_message='invalid literal for int() with base 10: "GHS 250"',
        traceback="Traceback...",
        fingerprint="fp-followup",
        ai_analysis={
            "likely_cause": 'The amount value was "GHS 250", and the code attempted int("GHS 250"), causing a ValueError.'
        },
    )
    analyzer = GeminiAnalyzer(
        api_key="gemini-key",
        client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
    )

    answer = analyzer.answer_follow_up(
        incident,
        "What should I inspect first?",
        conversation_history=[
            StoredConversationMessage(
                incident_id=incident.incident_id,
                role="user",
                content="What caused this?",
                created_at="2026-05-13T12:05:00.000000Z",
                source="natural",
            )
        ],
    )

    assert answer == "Direct answer"
    assert "LATEST USER QUESTION:" in captured["contents"]
    assert "What should I inspect first?" in captured["contents"]
    assert "Do not repeat the generic incident summary" in captured["contents"]


def test_compact_follow_up_prompt_stays_under_limit_and_uses_traceback_tail():
    incident = StoredIncident(
        incident_id="cog_compact",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message="payment parser failed for password=[REDACTED_PASSWORD]",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/manual_bot_test.py",
        filename="manual_bot_test.py",
        module="manual_bot_test",
        function="explode",
        line_number=42,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="ValueError",
        exception_message='invalid literal for int() with base 10: "GHS 250"',
        traceback="\n".join([f"line-{index}" for index in range(20)]),
        fingerprint="fp-compact",
        ai_analysis={
            "summary": "Payment parsing failure",
            "likely_cause": 'The amount value was "GHS 250", and the code attempted int("GHS 250"), causing a ValueError.',
            "suggested_steps": ["Check parsing", "Validate inputs", "Review normalization"],
        },
    )
    similar = [
        StoredIncident(
            incident_id=f"cog_sim_{index}",
            app_name="demo",
            environment="test",
            level="ERROR",
            levelno=40,
            message=f"similar incident {index} with [REDACTED_TOKEN]",
            logger_name="demo",
            timestamp="2026-05-13T12:00:00.000000Z",
            pathname="/srv/worker.py",
            filename="worker.py",
            module="worker",
            function="run",
            line_number=10 + index,
            process_id=1,
            process_name="MainProcess",
            thread_id=2,
            thread_name="MainThread",
            exception_type="RuntimeError",
            exception_message="timeout",
            traceback="traceback",
            fingerprint=f"fp-{index}",
        )
        for index in range(4)
    ]
    history = [
        StoredConversationMessage(
            incident_id=incident.incident_id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"history message {index} password=[REDACTED_PASSWORD]",
            created_at=f"2026-05-13T12:0{index}:00.000000Z",
            source="natural",
        )
        for index in range(6)
    ]

    prompt = build_follow_up_user_prompt(
        incident,
        "What caused this?",
        similar_incidents=similar,
        conversation_history=history,
        max_context_chars=700,
        max_history_messages=4,
        max_similar_incidents=2,
        max_similar_incident_chars=120,
    )

    assert len(prompt) <= 700
    assert "line-0" not in prompt
    assert "line-19" in prompt
    assert prompt.count("cog_sim_") <= 2
    assert prompt.count("history message") <= 4
    assert "swordfish" not in prompt


def test_sensitive_question_prompt_skips_unnecessary_similar_incidents():
    incident = StoredIncident(
        incident_id="cog_sensitive",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message="password=[REDACTED_PASSWORD] token=[REDACTED_TOKEN]",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="app",
        function="explode",
        line_number=42,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="RuntimeError",
        exception_message="[REDACTED_DATABASE_URL]",
        traceback="Traceback with [REDACTED_PASSWORD]",
        fingerprint="fp-sensitive",
        ai_analysis={"summary": "Handled"},
    )

    prompt = build_follow_up_user_prompt(
        incident,
        "Was any sensitive data exposed?",
        similar_incidents=[
            incident,
            incident,
        ],
        conversation_history=[],
    )

    assert "REDACTION EVIDENCE:" in prompt
    assert "SIMILAR INCIDENTS:" not in prompt


def test_inspect_question_prompt_includes_debugging_steps():
    incident = StoredIncident(
        incident_id="cog_inspect",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message="payment parser failed",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/manual_bot_test.py",
        filename="manual_bot_test.py",
        module="manual_bot_test",
        function="explode",
        line_number=42,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="ValueError",
        exception_message="bad amount",
        traceback="tail-a\ntail-b",
        fingerprint="fp-inspect",
        ai_analysis={
            "affected_area": "payments",
            "suggested_steps": [
                "Check the payment amount parsing code.",
                "Confirm whether strings are passed into int().",
            ],
        },
    )

    prompt = build_follow_up_user_prompt(incident, "What should I inspect first?")

    assert "Affected area: payments" in prompt
    assert "Debugging steps:" in prompt
    assert "Check the payment amount parsing code." in prompt


def test_cause_question_prompt_includes_exception_and_likely_cause():
    incident = StoredIncident(
        incident_id="cog_cause",
        app_name="demo",
        environment="test",
        level="ERROR",
        levelno=40,
        message="payment parser failed",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/manual_bot_test.py",
        filename="manual_bot_test.py",
        module="manual_bot_test",
        function="explode",
        line_number=42,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="ValueError",
        exception_message='invalid literal for int() with base 10: "GHS 250"',
        traceback="line-a\nline-b",
        fingerprint="fp-cause",
        ai_analysis={
            "summary": "Payment parsing failure",
            "likely_cause": 'The amount value was "GHS 250", and the code attempted int("GHS 250"), causing a ValueError.',
        },
    )

    prompt = build_follow_up_user_prompt(incident, "What caused this?")

    assert 'Exception: ValueError: invalid literal for int() with base 10: "GHS 250"' in prompt
    assert 'Likely cause: The amount value was "GHS 250", and the code attempted int("GHS 250"), causing a ValueError.' in prompt
