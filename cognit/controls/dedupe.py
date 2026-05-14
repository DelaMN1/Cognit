"""Incident deduplication control."""

from __future__ import annotations

from dataclasses import dataclass

from cognit.capture.event import LogEvent
from cognit.storage.base import BaseStore
from cognit.storage.models import StoredIncident


@dataclass(slots=True)
class DedupeDecision:
    incident_id: str
    incident: StoredIncident
    should_send_alert: bool
    is_duplicate: bool
    suppressed_reason: str | None = None


class Deduplicator:
    """Use incident fingerprints to suppress duplicate alerts."""

    def __init__(
        self,
        store: BaseStore,
        *,
        enable_deduplication: bool = True,
        dedupe_window_seconds: int = 300,
        alert_channel: str = "telegram",
    ) -> None:
        self.store = store
        self.enable_deduplication = enable_deduplication
        self.dedupe_window_seconds = dedupe_window_seconds
        self.alert_channel = alert_channel

    def process(self, event: LogEvent) -> DedupeDecision:
        if not self.enable_deduplication:
            stored = self.store.save_incident(event)
            return DedupeDecision(
                incident_id=stored.incident_id,
                incident=stored,
                should_send_alert=True,
                is_duplicate=False,
            )

        existing = self.store.get_recent_incident_by_fingerprint(
            event.fingerprint,
            self.dedupe_window_seconds,
        )
        if existing is None:
            stored = self.store.save_incident(event)
            return DedupeDecision(
                incident_id=stored.incident_id,
                incident=stored,
                should_send_alert=True,
                is_duplicate=False,
            )

        self.store.increment_occurrence(existing.incident_id)
        self.store.increment_suppressed_count(existing.incident_id)
        self.store.save_alert_event(
            event.fingerprint,
            existing.incident_id,
            self.alert_channel,
            False,
            "duplicate",
        )
        updated = self.store.get_incident(existing.incident_id) or existing
        return DedupeDecision(
            incident_id=updated.incident_id,
            incident=updated,
            should_send_alert=False,
            is_duplicate=True,
            suppressed_reason="duplicate",
        )
