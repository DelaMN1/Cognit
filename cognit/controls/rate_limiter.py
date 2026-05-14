"""Database-backed rate limiting for outbound alerts."""

from __future__ import annotations

from dataclasses import dataclass

from cognit.storage.base import BaseStore


@dataclass(slots=True)
class RateLimitDecision:
    should_send_alert: bool
    sent_count: int
    remaining: int
    suppressed_reason: str | None = None


class RateLimiter:
    """Enforce a database-backed alert rate limit."""

    def __init__(
        self,
        store: BaseStore,
        *,
        enable_rate_limiting: bool = True,
        telegram_alert_limit: int = 10,
        telegram_alert_window_seconds: int = 60,
        channel: str = "telegram",
    ) -> None:
        self.store = store
        self.enable_rate_limiting = enable_rate_limiting
        self.telegram_alert_limit = telegram_alert_limit
        self.telegram_alert_window_seconds = telegram_alert_window_seconds
        self.channel = channel

    def evaluate(self, channel: str | None = None) -> RateLimitDecision:
        resolved_channel = channel or self.channel
        sent_count = self.store.count_recent_sent_alert_events(
            resolved_channel,
            self.telegram_alert_window_seconds,
        )
        if not self.enable_rate_limiting:
            return RateLimitDecision(
                should_send_alert=True,
                sent_count=sent_count,
                remaining=max(0, self.telegram_alert_limit - sent_count),
            )
        if sent_count >= self.telegram_alert_limit:
            return RateLimitDecision(
                should_send_alert=False,
                sent_count=sent_count,
                remaining=0,
                suppressed_reason="rate_limit",
            )
        return RateLimitDecision(
            should_send_alert=True,
            sent_count=sent_count,
            remaining=max(0, self.telegram_alert_limit - sent_count),
        )

    def consume(self, fingerprint: str, incident_id: str, channel: str | None = None) -> RateLimitDecision:
        resolved_channel = channel or self.channel
        decision = self.evaluate(channel=resolved_channel)
        if decision.should_send_alert:
            self.store.save_alert_event(fingerprint, incident_id, resolved_channel, True, None)
            return decision

        self.store.increment_suppressed_count(incident_id)
        self.store.save_alert_event(
            fingerprint,
            incident_id,
            resolved_channel,
            False,
            decision.suppressed_reason,
        )
        return decision
