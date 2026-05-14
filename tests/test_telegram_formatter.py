from __future__ import annotations

from cognit.ai.schemas import AIAnalysis
from cognit.capture.event import LogEvent
from cognit.formatting.telegram_formatter import format_telegram_alert


def test_alert_uses_plain_text_sections_and_numbered_steps():
    event = LogEvent(
        incident_id="cog_20260513_120000_abcdef",
        app_name="demo",
        environment="production",
        level="ERROR",
        levelno=40,
        message="request failed",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="orders",
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
    analysis = AIAnalysis(
        summary="DB outage",
        likely_cause="Connection pool exhausted",
        severity="high",
        affected_area="orders",
        suggested_steps=["Check pool metrics", "Review deploy diff", "Retry the failing query"],
        possible_fix="Increase pool size",
        similar_incidents_summary=None,
        follow_up_questions=["Was traffic elevated?"],
    )

    message = format_telegram_alert(event, analysis)

    assert "Cognit Incident Alert\n\nApp: demo" in message
    assert "\n\nError\ndatabase down\n\nLikely cause\nConnection pool exhausted\n\nAffected area\norders\n\nFirst debugging steps\n1. Check pool metrics\n2. Review deploy diff\n3. Retry the failing query\n\nFollow-up\n/cognit cog_20260513_120000_abcdef What caused this?" in message
    assert "Incident: cog_20260513_120000_abcdef" in message
    assert "Incident ID:" not in message
    assert "- " not in message


def test_alert_replaces_schema_placeholders_with_unknown():
    event = LogEvent(
        incident_id="cog_20260513_120000_placeholder",
        app_name="demo",
        environment="production",
        level="ERROR",
        levelno=40,
        message="request failed",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="orders",
        function="explode",
        line_number=99,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="RuntimeError",
        exception_message="request failed",
        traceback="Traceback...",
        fingerprint="fp-a",
    )
    analysis = AIAnalysis(
        summary="DB outage",
        likely_cause="<string>",
        severity="high",
        affected_area="<string>",
        suggested_steps=["string", "N/A", "<string>"],
        possible_fix=None,
        similar_incidents_summary=None,
        follow_up_questions=["Was traffic elevated?"],
    )

    message = format_telegram_alert(event, analysis)

    assert "\nLikely cause\nUnknown\n" in message
    assert "\nAffected area\nUnknown\n" in message
    assert "<string>" not in message
    assert "\n1. Inspect the failing location at /srv/app.py:99 in explode()." in message


def test_alert_redacts_sensitive_values_before_formatting():
    event = LogEvent(
        incident_id="cog_20260513_120000_secret",
        app_name="demo",
        environment="production",
        level="ERROR",
        levelno=40,
        message="request failed",
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="orders",
        function="explode",
        line_number=99,
        process_id=1,
        process_name="MainProcess",
        thread_id=2,
        thread_name="MainThread",
        exception_type="RuntimeError",
        exception_message="password=swordfish admin@example.com",
        traceback="Traceback...",
        fingerprint="fp-a",
    )
    analysis = AIAnalysis(
        summary="DB outage",
        likely_cause="redis://:secret@localhost:6379/0",
        severity="high",
        affected_area="orders",
        suggested_steps=["Rotate token gho_abcdefghijklmnopqrstuvwxyz123456"],
        possible_fix="Set password=hunter2",
        similar_incidents_summary=None,
        follow_up_questions=["Is admin@example.com affected?"],
    )

    message = format_telegram_alert(event, analysis)

    assert "swordfish" not in message
    assert "admin@example.com" not in message
    assert "redis://:secret@localhost:6379/0" not in message
    assert "gho_abcdefghijklmnopqrstuvwxyz123456" not in message
    assert "hunter2" not in message
    assert "[REDACTED_PASSWORD]" in message
    assert "[REDACTED_EMAIL]" in message
    assert "[REDACTED_DATABASE_URL]" in message
    assert "[REDACTED_TOKEN]" in message
