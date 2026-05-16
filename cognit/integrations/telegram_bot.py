"""Telegram follow-up bot for Cognit incidents."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from cognit.ai import FallbackAnalyzer, answer_follow_up_with_fallback, build_analyzer
from cognit.config import CognitConfig
from cognit.embeddings import (
    SimilarIncidentRetriever,
    build_embedder,
    build_stored_incident_embedding_text,
)
from cognit.formatting.telegram_formatter import format_follow_up_response
from cognit.integrations.telegram import TelegramClient, TelegramClientError
from cognit.redaction.redactor import Redactor
from cognit.storage.base import BaseStore
from cognit.storage.models import ChatContext, StoredConversationMessage, StoredIncident
from cognit.storage.sqlite_store import SQLiteStore
from cognit.utils.time import parse_utc_timestamp, utc_now


USAGE_MESSAGE = (
    "Usage: /cognit <incident_id> <question>\n"
    "Example: /cognit cog_20260509_143522_a8f29c What caused this?"
)
NO_CONTEXT_MESSAGE = (
    "No active incident for this chat. Use /cognit <incident_id> <question> or wait for a new alert."
)


@dataclass(slots=True)
class ParsedCommand:
    name: str
    incident_id: str | None
    question: str | None


class TelegramFollowUpBot:
    """Poll Telegram for `/cognit` commands and answer follow-up questions."""

    def __init__(
        self,
        *,
        config: CognitConfig | None = None,
        store: BaseStore | None = None,
        telegram_client: TelegramClient | None = None,
        analyzer: Any | None = None,
        fallback_analyzer: FallbackAnalyzer | None = None,
        embedder: Any | None = None,
        similar_retriever: SimilarIncidentRetriever | None = None,
        poll_timeout: int = 30,
        active_context_ttl_seconds: int = 1800,
        max_followup_chars: int = 500,
    ) -> None:
        self.config = config or CognitConfig.from_env()
        self.redactor = Redactor(custom_patterns=self.config.custom_redaction_patterns)
        self.store = store
        if self.store is None:
            try:
                self.store = SQLiteStore()
            except Exception:
                self.store = None
        self.telegram_client = telegram_client or TelegramClient(token=self.config.telegram_bot_token)
        self.analyzer = analyzer if analyzer is not None else self._build_analyzer()
        self.fallback_analyzer = fallback_analyzer or FallbackAnalyzer()
        self.embedder = embedder if embedder is not None else self._build_embedder()
        self.similar_retriever = similar_retriever or self._build_similar_retriever()
        self.poll_timeout = poll_timeout
        self.active_context_ttl_seconds = active_context_ttl_seconds
        self.max_followup_chars = max_followup_chars

    def run_forever(self) -> None:
        offset: int | None = None
        while True:
            try:
                offset = self.process_updates_once(offset=offset)
            except KeyboardInterrupt:
                raise
            except Exception:
                time.sleep(1.0)

    def process_updates_once(self, *, offset: int | None = None) -> int | None:
        try:
            updates = self.telegram_client.get_updates(offset=offset, timeout=self.poll_timeout)
        except TelegramClientError:
            return offset

        next_offset = offset
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                candidate_offset = update_id + 1
                if next_offset is None or candidate_offset > next_offset:
                    next_offset = candidate_offset
            try:
                self.handle_update(update)
            except Exception:
                continue
        return next_offset

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return

        text = message.get("text")
        if not isinstance(text, str):
            return

        chat_id = self._extract_chat_id(message)
        if chat_id is None:
            return

        parsed = self._parse_command(text)
        if parsed.name == "cognit":
            if not parsed.incident_id or not parsed.question:
                self._safe_reply(chat_id, USAGE_MESSAGE)
                return
            self._handle_follow_up(chat_id, parsed.incident_id, parsed.question, source="explicit")
            return
        if parsed.name == "current":
            self._handle_current_command(chat_id)
            return
        if parsed.name == "clear":
            self._handle_clear_command(chat_id)
            return
        if text.startswith("/"):
            self._safe_reply(chat_id, "Unknown command. Use /cognit <incident_id> <question>.")
            return
        self._handle_natural_follow_up(chat_id, text)

    def _handle_follow_up(
        self,
        chat_id: str,
        incident_id: str,
        question: str,
        *,
        source: str,
    ) -> None:
        if self.store is None:
            self._safe_reply(chat_id, "Cognit could not access SQLite incident storage.")
            return

        try:
            incident = self.store.get_incident(incident_id)
        except Exception:
            self._safe_reply(chat_id, "Cognit could not load incidents from SQLite right now.")
            return
        if incident is None:
            self._safe_reply(chat_id, f"Incident {incident_id} was not found.")
            return

        conversation_history = self._safe_get_conversation(incident_id)
        similar_incidents = self._safe_get_similar_incidents(incident)

        safe_question = self._prepare_follow_up_text(question)
        self._safe_save_conversation(incident_id, "user", safe_question, source=source)

        answer = answer_follow_up_with_fallback(
            incident,
            safe_question,
            analyzer=self.analyzer,
            fallback=self.fallback_analyzer,
            similar_incidents=similar_incidents,
            conversation_history=conversation_history,
        )
        if not answer.strip():
            answer = self.fallback_analyzer.answer_follow_up(
                self.redactor.redact_stored_incident(incident),
                safe_question,
                similar_incidents=[self.redactor.redact_stored_incident(item) for item in similar_incidents],
                conversation_history=[
                    StoredConversationMessage(
                        incident_id=item.incident_id,
                        role=item.role,
                        content=self.redactor.redact_text(item.content) or "",
                        created_at=item.created_at,
                    )
                    for item in conversation_history
                ],
            )
        safe_answer = format_follow_up_response(
            incident,
            safe_question,
            answer,
            similar_incidents=similar_incidents,
        )
        self._safe_save_conversation(incident_id, "assistant", safe_answer, source=source)
        self._safe_set_active_incident(chat_id, incident_id)
        self._safe_reply(chat_id, safe_answer)

    def _handle_natural_follow_up(self, chat_id: str, text: str) -> None:
        if self.store is None:
            self._safe_reply(chat_id, NO_CONTEXT_MESSAGE)
            return
        incident_id = self._safe_get_active_incident(chat_id)
        if incident_id is None:
            self._safe_reply(chat_id, NO_CONTEXT_MESSAGE)
            return
        self._handle_follow_up(chat_id, incident_id, text, source="natural")

    def _handle_current_command(self, chat_id: str) -> None:
        context = self._safe_get_chat_context(chat_id)
        if context is None or self.store is None:
            self._safe_reply(chat_id, "No active incident for this chat.")
            return
        incident = self._safe_get_incident(context.active_incident_id)
        if incident is None:
            self._safe_reply(chat_id, "No active incident for this chat.")
            return

        ttl_line = self._format_ttl_remaining(context)
        summary = self.redactor.redact_text(incident.message) or "Unknown incident"
        self._safe_reply(
            chat_id,
            "\n".join(
                [
                    f"Active incident: {incident.incident_id}",
                    summary,
                    f"Expires: {ttl_line}",
                    "",
                    "Use /clear to reset, or just reply with your question.",
                ]
            ),
        )

    def _handle_clear_command(self, chat_id: str) -> None:
        if self.store is None:
            self._safe_reply(chat_id, "No active incident for this chat.")
            return
        try:
            self.store.clear_chat_context(chat_id)
        except Exception:
            self._safe_reply(chat_id, "Cognit could not clear the active incident right now.")
            return
        self._safe_reply(chat_id, "Active incident cleared for this chat.")

    def _safe_get_conversation(self, incident_id: str) -> list[StoredConversationMessage]:
        if self.store is None:
            return []
        try:
            limit = max(0, self.config.max_conversation_history_messages)
            return self.store.get_conversation(incident_id, limit=limit) if limit else []
        except Exception:
            return []

    def _safe_get_similar_incidents(self, incident: StoredIncident) -> list[StoredIncident]:
        if self.store is None or self.embedder is None:
            return []
        try:
            limit = max(0, self.config.max_similar_incidents_for_followup)
            if limit == 0:
                return []
            embedding = self.embedder.embed(build_stored_incident_embedding_text(incident))
            return self.store.find_similar_incidents(
                embedding,
                exclude_incident_id=incident.incident_id,
                app_name=incident.app_name,
                environment=incident.environment,
                limit=limit,
            )
        except Exception:
            return []

    def _safe_save_conversation(
        self,
        incident_id: str,
        role: str,
        content: str,
        *,
        source: str,
    ) -> None:
        if self.store is None:
            return
        try:
            self.store.save_conversation_message(incident_id, role, content, source=source)
        except Exception:
            return

    def _safe_set_active_incident(self, chat_id: str, incident_id: str) -> None:
        if self.store is None:
            return
        try:
            self.store.set_active_incident(
                chat_id,
                incident_id,
                ttl_seconds=self.active_context_ttl_seconds,
            )
        except Exception:
            return

    def _safe_get_chat_context(self, chat_id: str) -> ChatContext | None:
        if self.store is None:
            return None
        try:
            return self.store.get_chat_context(chat_id)
        except Exception:
            return None

    def _safe_get_active_incident(self, chat_id: str) -> str | None:
        if self.store is None:
            return None
        try:
            return self.store.get_active_incident(chat_id)
        except Exception:
            return None

    def _safe_get_incident(self, incident_id: str) -> StoredIncident | None:
        if self.store is None:
            return None
        try:
            return self.store.get_incident(incident_id)
        except Exception:
            return None

    def _safe_reply(self, chat_id: str, text: str) -> None:
        try:
            self.telegram_client.send_long_message(chat_id, text)
        except Exception:
            return

    def _parse_command(self, text: str) -> ParsedCommand:
        pieces = text.strip().split(maxsplit=2)
        raw_command = pieces[0].lower() if pieces else ""
        command = raw_command[1:].split("@", 1)[0] if raw_command.startswith("/") else raw_command
        incident_id = pieces[1].strip() if len(pieces) >= 2 and pieces[1].strip() else None
        question = pieces[2].strip() if len(pieces) >= 3 and pieces[2].strip() else None
        return ParsedCommand(name=command, incident_id=incident_id, question=question)

    def _extract_chat_id(self, message: dict[str, Any]) -> str | None:
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return None
        chat_id = chat.get("id")
        if chat_id is None:
            return None
        return str(chat_id)

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

    def _prepare_follow_up_text(self, text: str) -> str:
        safe_text = self.redactor.redact_text(text) or ""
        if len(safe_text) <= self.max_followup_chars:
            return safe_text
        truncated = safe_text[: self.max_followup_chars].rstrip()
        return f"{truncated}\n[TRUNCATED]"

    def _format_ttl_remaining(self, context: ChatContext) -> str:
        remaining = parse_utc_timestamp(context.expires_at) - utc_now()
        if remaining <= timedelta(minutes=1):
            return "in less than 1 minute"

        total_minutes = int(remaining.total_seconds() // 60)
        if total_minutes < 60:
            return f"in {total_minutes} minute{'s' if total_minutes != 1 else ''}"

        total_hours = int(remaining.total_seconds() // 3600)
        if total_hours < 24:
            return f"in {total_hours} hour{'s' if total_hours != 1 else ''}"

        total_days = int(remaining.total_seconds() // 86400)
        return f"in {total_days} day{'s' if total_days != 1 else ''}"
