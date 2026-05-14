from __future__ import annotations

from cognit.integrations.telegram import (
    TelegramClient,
    TelegramClientError,
    _classify_payload_failure,
    split_telegram_message,
)


def test_send_long_message_splits_and_sends_all_chunks():
    sent_payloads: list[str] = []

    def transport(method, url, payload, timeout):
        del method, url, timeout
        sent_payloads.append(payload["text"])
        return {"ok": True, "result": {"message_id": len(sent_payloads)}}

    client = TelegramClient(token="token", transport=transport)
    message_ids = client.send_long_message("chat-1", "alpha beta gamma delta", max_chars=10)

    assert len(message_ids) == len(sent_payloads)
    assert len(sent_payloads) > 1
    assert "".join(chunk + " " for chunk in sent_payloads).replace("  ", " ").strip() == "alpha beta gamma delta"


def test_invalid_token_is_classified():
    def transport(method, url, payload, timeout):
        raise TelegramClientError("invalid_token", "Telegram bot token is invalid.")

    client = TelegramClient(token="bad", transport=transport)

    try:
        client.send_message("chat-1", "hello")
    except TelegramClientError as exc:
        assert exc.category == "invalid_token"
    else:
        raise AssertionError("Expected TelegramClientError.")


def test_wrong_chat_id_is_classified():
    def transport(method, url, payload, timeout):
        raise TelegramClientError("wrong_chat_id", "Telegram chat ID is invalid or the bot cannot access it.")

    client = TelegramClient(token="token", transport=transport)

    try:
        client.send_message("bad-chat", "hello")
    except TelegramClientError as exc:
        assert exc.category == "wrong_chat_id"
    else:
        raise AssertionError("Expected TelegramClientError.")


def test_network_failure_is_classified():
    def transport(method, url, payload, timeout):
        raise OSError("network down")

    client = TelegramClient(token="token", transport=transport)

    try:
        client.send_message("chat-1", "hello")
    except TelegramClientError as exc:
        assert exc.category == "network_failure"
    else:
        raise AssertionError("Expected TelegramClientError.")


def test_missing_token_and_chat_id_are_classified():
    client = TelegramClient(token=None)

    try:
        client.send_message("chat-1", "hello")
    except TelegramClientError as exc:
        assert exc.category == "missing_token"
    else:
        raise AssertionError("Expected TelegramClientError.")

    client = TelegramClient(token="token")
    try:
        client.send_message(None, "hello")
    except TelegramClientError as exc:
        assert exc.category == "missing_chat_id"
    else:
        raise AssertionError("Expected TelegramClientError.")


def test_splitter_preserves_content_across_chunks():
    chunks = split_telegram_message("line one\nline two\nline three", max_chars=12)

    assert len(chunks) >= 2
    assert " ".join(chunk.replace("\n", " ") for chunk in chunks).split() == [
        "line",
        "one",
        "line",
        "two",
        "line",
        "three",
    ]


def test_bot_blocked_rate_limit_and_unknown_errors_are_classified():
    blocked = _classify_payload_failure(
        {"description": "Forbidden: bot was blocked by the user"},
        403,
    )
    rate_limit = _classify_payload_failure(
        {"description": "Too Many Requests: retry after 5"},
        429,
    )
    unknown = _classify_payload_failure(
        {"description": "Bad Request: some other Telegram failure"},
        400,
    )

    assert blocked.category == "bot_blocked"
    assert rate_limit.category == "rate_limit"
    assert unknown.category == "unknown_api_error"
