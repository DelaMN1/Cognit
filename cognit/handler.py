"""Logging handler entrypoint for Cognit."""

from __future__ import annotations

import logging
import threading
from typing import Any

from cognit.ai import FallbackAnalyzer, analyze_with_fallback, build_analyzer
from cognit.capture.event import LogEvent
from cognit.capture.record_builder import build_log_event
from cognit.config import CognitConfig
from cognit.controls.dedupe import Deduplicator
from cognit.controls.rate_limiter import RateLimiter
from cognit.embeddings import SimilarIncidentRetriever, build_embedder, build_embedding_text
from cognit.formatting.telegram_formatter import format_telegram_alert
from cognit.integrations.telegram import TelegramClient
from cognit.redaction.redactor import Redactor
from cognit.storage.base import BaseStore
from cognit.storage.sqlite_store import SQLiteStore


class CognitHandler(logging.Handler):
    """Capture log records as structured Cognit events."""

    def __init__(
        self,
        app_name: str | None = None,
        environment: str | None = None,
        *,
        config: CognitConfig | None = None,
        store: BaseStore | None = None,
        deduplicator: Deduplicator | None = None,
        rate_limiter: RateLimiter | None = None,
        analyzer: Any | None = None,
        fallback_analyzer: FallbackAnalyzer | None = None,
        embedder: Any | None = None,
        similar_retriever: SimilarIncidentRetriever | None = None,
        telegram_client: TelegramClient | None = None,
        level: int = logging.NOTSET,
    ) -> None:
        super().__init__(level=level)
        self.config = config or CognitConfig.from_env()
        if app_name is not None:
            self.config.app_name = app_name
        if environment is not None:
            self.config.environment = environment
        self.redactor = Redactor(custom_patterns=self.config.custom_redaction_patterns)
        self.last_event = None
        self.last_analysis = None
        self._state = threading.local()
        self.store = store
        if self.store is None:
            try:
                self.store = SQLiteStore()
            except Exception:
                self.store = None
        self.deduplicator = deduplicator or self._build_deduplicator()
        self.rate_limiter = rate_limiter or self._build_rate_limiter()
        self.analyzer = analyzer if analyzer is not None else self._build_analyzer()
        self.fallback_analyzer = fallback_analyzer or FallbackAnalyzer()
        self.embedder = embedder if embedder is not None else self._build_embedder()
        self.similar_retriever = similar_retriever or self._build_similar_retriever()
        self.telegram_client = telegram_client or TelegramClient(token=self.config.telegram_bot_token)

    def emit(self, record: logging.LogRecord) -> None:
        if not self.config.enable_capture:
            return
        if getattr(self._state, "in_emit", False):
            return

        self._state.in_emit = True
        try:
            safe_event = self._build_safe_event(record)
            self.last_event = safe_event
            self._process_event(safe_event)
        except Exception:
            self.handleError(record)
        finally:
            self._state.in_emit = False

    def get_last_event(self) -> Any:
        return self.last_event

    def _build_safe_event(self, record: logging.LogRecord) -> LogEvent:
        event = build_log_event(
            record,
            app_name=self.config.app_name,
            environment=self.config.environment,
            tags=self.config.tags,
        )
        return self.redactor.redact_event(event)

    def _process_event(self, event: LogEvent) -> None:
        incident_id = event.incident_id
        should_send_alert = self.config.enable_telegram_alerts
        stored_incident = None
        similar_incidents = []
        analysis = None
        rate_suppressed_reason: str | None = None

        try:
            if self.deduplicator is not None:
                dedupe_decision = self.deduplicator.process(event)
                incident_id = dedupe_decision.incident_id
                stored_incident = dedupe_decision.incident
                if dedupe_decision.is_duplicate:
                    return
            elif self.store is not None:
                stored_incident = self.store.save_incident(event)
                incident_id = stored_incident.incident_id
        except Exception:
            stored_incident = None

        query_embedding: list[float] | None = None
        if self.embedder is not None and self.similar_retriever is not None:
            try:
                embedding_text = build_embedding_text(event)
                query_embedding = self.embedder.embed(embedding_text)
                similar_incidents = self.similar_retriever.find_similar(
                    event,
                    query_embedding,
                    incident_id=incident_id,
                )
            except Exception:
                similar_incidents = []
                query_embedding = None

        if self.config.enable_ai_analysis:
            analysis = analyze_with_fallback(
                event,
                analyzer=self.analyzer,
                fallback=self.fallback_analyzer,
                similar_incidents=similar_incidents,
            )
        else:
            analysis = self.fallback_analyzer.analyze(event, similar_incidents=similar_incidents)
            analysis = self.redactor.redact_analysis(analysis)
        self.last_analysis = analysis

        if self.store is not None:
            try:
                self.store.save_ai_analysis(incident_id, analysis)
            except Exception:
                pass

        if self.store is not None and query_embedding is not None:
            try:
                self.store.save_embedding(
                    incident_id,
                    query_embedding,
                    self.embedder.text_hash(build_embedding_text(event)),
                )
            except Exception:
                pass

        if should_send_alert and self.rate_limiter is not None:
            try:
                rate_decision = self.rate_limiter.evaluate()
                if not rate_decision.should_send_alert:
                    rate_suppressed_reason = rate_decision.suppressed_reason or "rate_limit"
                    should_send_alert = False
                    if self.store is not None:
                        self.store.increment_suppressed_count(incident_id)
                        self.store.save_alert_event(
                            event.fingerprint,
                            incident_id,
                            "telegram",
                            False,
                            rate_suppressed_reason,
                        )
            except Exception:
                pass

        if not should_send_alert:
            return

        try:
            message = format_telegram_alert(event, analysis)
            message_ids = self.telegram_client.send_long_message(self.config.telegram_chat_id, message)
        except Exception:
            if self.store is not None:
                try:
                    self.store.save_alert_event(
                        event.fingerprint,
                        incident_id,
                        "telegram",
                        False,
                        "telegram_error",
                    )
                except Exception:
                    pass
            return

        if self.store is not None:
            try:
                for message_id in message_ids:
                    self.store.save_telegram_message(
                        incident_id,
                        self.config.telegram_chat_id or "",
                        message_id,
                    )
                self.store.save_alert_event(
                    event.fingerprint,
                    incident_id,
                    "telegram",
                    True,
                    None,
                )
            except Exception:
                pass

    def _build_deduplicator(self) -> Deduplicator | None:
        if self.store is None:
            return None
        return Deduplicator(
            self.store,
            enable_deduplication=self.config.enable_deduplication,
            dedupe_window_seconds=self.config.dedupe_window_seconds,
        )

    def _build_rate_limiter(self) -> RateLimiter | None:
        if self.store is None:
            return None
        return RateLimiter(
            self.store,
            enable_rate_limiting=self.config.enable_rate_limiting,
            telegram_alert_limit=self.config.telegram_alert_limit,
            telegram_alert_window_seconds=self.config.telegram_alert_window_seconds,
        )

    def _build_analyzer(self) -> Any | None:
        if not self.config.enable_ai_analysis:
            return None
        return build_analyzer(self.config)

    def _build_embedder(self) -> Any | None:
        try:
            return build_embedder(self.config)
        except Exception:
            return None

    def _build_similar_retriever(self) -> SimilarIncidentRetriever | None:
        if self.store is None:
            return None
        return SimilarIncidentRetriever(self.store)
