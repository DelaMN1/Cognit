"""Thread-safe SQLite storage backend for Cognit incidents."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterator

from cognit.capture.event import LogEvent
from cognit.exceptions import CognitStorageError
from cognit.storage.base import BaseStore
from cognit.storage.models import (
    StoredConversationMessage,
    StoredIncident,
)
from cognit.utils.json import make_json_safe
from cognit.utils.time import format_utc_timestamp, utc_now


DEFAULT_DB_PATH = Path(".cognit") / "cognit.db"


class SQLiteStore(BaseStore):
    """Persist Cognit incidents in a local SQLite database."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._initialize_database()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL;")
            connection.execute("PRAGMA busy_timeout=5000;")
            yield connection
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self._write_lock:
            with self._connect() as connection:
                try:
                    with connection:
                        connection.executescript(_SCHEMA_SQL)
                        connection.executescript(_INDEX_SQL)
                except sqlite3.Error as exc:
                    raise CognitStorageError("Failed to initialize SQLite storage.") from exc

    def save_incident(self, event: LogEvent) -> StoredIncident:
        now = self._now()
        payload = (
            event.incident_id,
            event.app_name,
            event.environment,
            event.level,
            event.levelno,
            event.message,
            event.logger_name,
            event.timestamp,
            event.pathname,
            event.filename,
            event.module,
            event.function,
            event.line_number,
            event.process_id,
            event.process_name,
            event.thread_id,
            event.thread_name,
            event.exception_type,
            event.exception_message,
            event.traceback,
            event.fingerprint,
            self._dump_json(event.tags),
            self._dump_json(event.extra),
            now,
            now,
            now,
            now,
        )

        with self._write_lock:
            with self._connect() as connection:
                try:
                    with connection:
                        connection.execute(_INSERT_INCIDENT_SQL, payload)
                        connection.execute(
                            """
                            INSERT INTO logs (
                                incident_id,
                                level,
                                message,
                                created_at
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (event.incident_id, event.level, event.message, now),
                        )
                except sqlite3.Error as exc:
                    raise CognitStorageError("Failed to save incident.") from exc

        stored = self.get_incident(event.incident_id)
        if stored is None:
            raise CognitStorageError("Incident was not persisted.")
        return stored

    def save_ai_analysis(self, incident_id: str, analysis: Any) -> None:
        payload = self._normalize_analysis(analysis)
        now = self._now()

        with self._write_lock:
            with self._connect() as connection:
                try:
                    with connection:
                        connection.execute(
                            """
                            UPDATE incidents
                            SET ai_summary = ?,
                                ai_likely_cause = ?,
                                ai_severity = ?,
                                ai_affected_area = ?,
                                ai_suggested_steps = ?,
                                ai_possible_fix = ?,
                                ai_similar_incidents_summary = ?,
                                ai_follow_up_questions = ?,
                                ai_raw_response = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                payload.get("summary"),
                                payload.get("likely_cause"),
                                payload.get("severity"),
                                payload.get("affected_area"),
                                self._dump_json(payload.get("suggested_steps", [])),
                                payload.get("possible_fix"),
                                payload.get("similar_incidents_summary"),
                                self._dump_json(payload.get("follow_up_questions", [])),
                                payload.get("raw_response"),
                                now,
                                incident_id,
                            ),
                        )
                except sqlite3.Error as exc:
                    raise CognitStorageError("Failed to save AI analysis.") from exc

    def save_embedding(self, incident_id: str, embedding: list[float], text_hash: str) -> None:
        now = self._now()
        with self._write_lock:
            with self._connect() as connection:
                try:
                    with connection:
                        connection.execute(
                            """
                            INSERT INTO embeddings (
                                incident_id,
                                embedding,
                                dimensions,
                                text_hash,
                                created_at
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                incident_id,
                                self._dump_json(embedding),
                                len(embedding),
                                text_hash,
                                now,
                            ),
                        )
                except sqlite3.Error as exc:
                    raise CognitStorageError("Failed to save embedding.") from exc

    def get_incident(self, incident_id: str) -> StoredIncident | None:
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT * FROM incidents WHERE id = ?",
                    (incident_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise CognitStorageError("Failed to load incident.") from exc
        if row is None:
            return None
        return self._row_to_incident(row)

    def get_recent_incident_by_fingerprint(
        self,
        fingerprint: str,
        within_seconds: int,
    ) -> StoredIncident | None:
        cutoff = self._now_minus_seconds(within_seconds)
        with self._connect() as connection:
            try:
                row = connection.execute(
                    """
                    SELECT *
                    FROM incidents
                    WHERE fingerprint = ?
                      AND last_seen_at > ?
                    ORDER BY last_seen_at DESC
                    LIMIT 1
                    """,
                    (fingerprint, cutoff),
                ).fetchone()
            except sqlite3.Error as exc:
                raise CognitStorageError("Failed to load recent incident by fingerprint.") from exc
        if row is None:
            return None
        return self._row_to_incident(row)

    def increment_occurrence(self, incident_id: str) -> None:
        now = self._now()
        self._write(
            """
            UPDATE incidents
            SET occurrence_count = occurrence_count + 1,
                last_seen_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, incident_id),
            "Failed to update incident occurrence count.",
        )

    def increment_suppressed_count(self, incident_id: str) -> None:
        now = self._now()
        self._write(
            """
            UPDATE incidents
            SET suppressed_count = suppressed_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (now, incident_id),
            "Failed to update incident suppressed count.",
        )

    def count_recent_sent_alert_events(self, channel: str, window_seconds: int) -> int:
        cutoff = self._now_minus_seconds(window_seconds)
        with self._connect() as connection:
            try:
                row = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM alert_events
                    WHERE channel = ?
                      AND sent = 1
                      AND created_at > ?
                    """,
                    (channel, cutoff),
                ).fetchone()
            except sqlite3.Error as exc:
                raise CognitStorageError("Failed to count recent alert events.") from exc
        return int(row[0]) if row is not None else 0

    def list_recent_incidents(self, limit: int = 20) -> list[StoredIncident]:
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM incidents
                    ORDER BY last_seen_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            except sqlite3.Error as exc:
                raise CognitStorageError("Failed to list incidents.") from exc
        return [self._row_to_incident(row) for row in rows]

    def find_similar_incidents(
        self,
        embedding: list[float],
        *,
        exclude_incident_id: str,
        app_name: str,
        environment: str,
        limit: int = 3,
    ) -> list[StoredIncident]:
        expected_dimensions = len(embedding)
        if expected_dimensions == 0:
            return []

        with self._connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT incidents.*, embeddings.embedding, embeddings.dimensions
                    FROM embeddings
                    INNER JOIN incidents ON incidents.id = embeddings.incident_id
                    WHERE incidents.id != ?
                    """,
                    (exclude_incident_id,),
                ).fetchall()
            except sqlite3.Error as exc:
                raise CognitStorageError("Failed to load similar incidents.") from exc

        scored: dict[str, tuple[StoredIncident, tuple[float, int, int, int, str]]] = {}
        for row in rows:
            dimensions = row["dimensions"]
            if dimensions != expected_dimensions:
                continue

            candidate_embedding = self._load_embedding_vector(row["embedding"], expected_dimensions)
            if candidate_embedding is None:
                continue

            score = _cosine_similarity(embedding, candidate_embedding)
            incident = self._row_to_incident(row)
            ranking = (
                score,
                int(incident.app_name == app_name and incident.environment == environment),
                int(incident.app_name == app_name),
                int(incident.environment == environment),
                incident.last_seen_at,
            )
            existing = scored.get(incident.incident_id)
            if existing is None or ranking > existing[1]:
                scored[incident.incident_id] = (incident, ranking)

        ordered = sorted(scored.values(), key=lambda item: item[1], reverse=True)
        return [incident for incident, _ in ordered[:limit]]

    def save_telegram_message(self, incident_id: str, chat_id: str, message_id: str) -> None:
        self._write(
            """
            INSERT INTO telegram_messages (
                incident_id,
                chat_id,
                message_id,
                created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (incident_id, chat_id, message_id, self._now()),
            "Failed to save Telegram message metadata.",
        )

    def save_alert_event(
        self,
        fingerprint: str,
        incident_id: str,
        channel: str,
        sent: bool,
        suppressed_reason: str | None,
    ) -> None:
        self._write(
            """
            INSERT INTO alert_events (
                fingerprint,
                incident_id,
                channel,
                sent,
                suppressed_reason,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fingerprint,
                incident_id,
                channel,
                int(sent),
                suppressed_reason,
                self._now(),
            ),
            "Failed to save alert event.",
        )

    def save_conversation_message(self, incident_id: str, role: str, content: str) -> None:
        self._write(
            """
            INSERT INTO conversations (
                incident_id,
                role,
                content,
                created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (incident_id, role, content, self._now()),
            "Failed to save conversation message.",
        )

    def get_conversation(self, incident_id: str, limit: int = 20) -> list[StoredConversationMessage]:
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT incident_id, role, content, created_at
                    FROM conversations
                    WHERE incident_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (incident_id, limit),
                ).fetchall()
            except sqlite3.Error as exc:
                raise CognitStorageError("Failed to load conversation history.") from exc
        messages = [
            StoredConversationMessage(
                incident_id=row["incident_id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
        return list(reversed(messages))

    def _write(self, sql: str, params: tuple[Any, ...], error_message: str) -> None:
        with self._write_lock:
            with self._connect() as connection:
                try:
                    with connection:
                        connection.execute(sql, params)
                except sqlite3.Error as exc:
                    raise CognitStorageError(error_message) from exc

    def _row_to_incident(self, row: sqlite3.Row) -> StoredIncident:
        analysis = None
        if any(
            row[field] is not None
            for field in (
                "ai_summary",
                "ai_likely_cause",
                "ai_severity",
                "ai_affected_area",
                "ai_possible_fix",
                "ai_similar_incidents_summary",
                "ai_raw_response",
            )
        ) or row["ai_suggested_steps"] or row["ai_follow_up_questions"]:
            analysis = {
                "summary": row["ai_summary"],
                "likely_cause": row["ai_likely_cause"],
                "severity": row["ai_severity"],
                "affected_area": row["ai_affected_area"],
                "suggested_steps": self._load_json(row["ai_suggested_steps"], []),
                "possible_fix": row["ai_possible_fix"],
                "similar_incidents_summary": row["ai_similar_incidents_summary"],
                "follow_up_questions": self._load_json(row["ai_follow_up_questions"], []),
                "raw_response": row["ai_raw_response"],
            }

        return StoredIncident(
            incident_id=row["id"],
            app_name=row["app_name"],
            environment=row["environment"],
            level=row["level"],
            levelno=row["levelno"],
            message=row["message"],
            logger_name=row["logger_name"],
            timestamp=row["timestamp"],
            pathname=row["pathname"],
            filename=row["filename"],
            module=row["module"],
            function=row["function"],
            line_number=row["line_number"],
            process_id=row["process_id"],
            process_name=row["process_name"],
            thread_id=row["thread_id"],
            thread_name=row["thread_name"],
            exception_type=row["exception_type"],
            exception_message=row["exception_message"],
            traceback=row["traceback"],
            fingerprint=row["fingerprint"],
            tags=self._load_json(row["tags"], {}),
            extra=self._load_json(row["extra"], {}),
            occurrence_count=row["occurrence_count"],
            suppressed_count=row["suppressed_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            ai_analysis=analysis,
        )

    def _normalize_analysis(self, analysis: Any) -> dict[str, Any]:
        if analysis is None:
            return {}
        if isinstance(analysis, dict):
            return dict(analysis)
        if is_dataclass(analysis):
            return asdict(analysis)

        fields = (
            "summary",
            "likely_cause",
            "severity",
            "affected_area",
            "suggested_steps",
            "possible_fix",
            "similar_incidents_summary",
            "follow_up_questions",
            "raw_response",
        )
        return {
            field: getattr(analysis, field, None)
            for field in fields
            if hasattr(analysis, field)
        }

    def _dump_json(self, value: Any) -> str:
        return json.dumps(make_json_safe(value), sort_keys=True)

    def _load_json(self, raw: str | None, default: Any) -> Any:
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    def _load_embedding_vector(self, raw: str | None, expected_dimensions: int) -> list[float] | None:
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, list) or len(payload) != expected_dimensions:
            return None

        vector: list[float] = []
        for item in payload:
            if not isinstance(item, (int, float)):
                return None
            vector.append(float(item))
        return vector

    def _now(self) -> str:
        return format_utc_timestamp(utc_now())

    def _now_minus_seconds(self, seconds: int) -> str:
        return format_utc_timestamp(utc_now() - timedelta(seconds=seconds))


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    app_name TEXT NOT NULL,
    environment TEXT NOT NULL,
    level TEXT NOT NULL,
    levelno INTEGER NOT NULL,
    message TEXT NOT NULL,
    logger_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    pathname TEXT NOT NULL,
    filename TEXT NOT NULL,
    module TEXT NOT NULL,
    function TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    process_id INTEGER NOT NULL,
    process_name TEXT NOT NULL,
    thread_id INTEGER NOT NULL,
    thread_name TEXT NOT NULL,
    exception_type TEXT,
    exception_message TEXT,
    traceback TEXT,
    fingerprint TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '{}',
    extra TEXT NOT NULL DEFAULT '{}',
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    suppressed_count INTEGER NOT NULL DEFAULT 0,
    ai_summary TEXT,
    ai_likely_cause TEXT,
    ai_severity TEXT,
    ai_affected_area TEXT,
    ai_suggested_steps TEXT,
    ai_possible_fix TEXT,
    ai_similar_incidents_summary TEXT,
    ai_follow_up_questions TEXT,
    ai_raw_response TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    embedding TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telegram_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    sent INTEGER NOT NULL,
    suppressed_reason TEXT,
    created_at TEXT NOT NULL
);
"""

_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint
ON incidents(fingerprint);

CREATE INDEX IF NOT EXISTS idx_alert_events_fingerprint
ON alert_events(fingerprint);

CREATE INDEX IF NOT EXISTS idx_alert_events_channel_created_at
ON alert_events(channel, created_at);

CREATE INDEX IF NOT EXISTS idx_conversations_incident_id
ON conversations(incident_id);

CREATE INDEX IF NOT EXISTS idx_embeddings_incident_id
ON embeddings(incident_id);

CREATE INDEX IF NOT EXISTS idx_telegram_messages_incident_id
ON telegram_messages(incident_id);
"""

_INSERT_INCIDENT_SQL = """
INSERT INTO incidents (
    id,
    app_name,
    environment,
    level,
    levelno,
    message,
    logger_name,
    timestamp,
    pathname,
    filename,
    module,
    function,
    line_number,
    process_id,
    process_name,
    thread_id,
    thread_name,
    exception_type,
    exception_message,
    traceback,
    fingerprint,
    tags,
    extra,
    created_at,
    updated_at,
    first_seen_at,
    last_seen_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    app_name = excluded.app_name,
    environment = excluded.environment,
    level = excluded.level,
    levelno = excluded.levelno,
    message = excluded.message,
    logger_name = excluded.logger_name,
    timestamp = excluded.timestamp,
    pathname = excluded.pathname,
    filename = excluded.filename,
    module = excluded.module,
    function = excluded.function,
    line_number = excluded.line_number,
    process_id = excluded.process_id,
    process_name = excluded.process_name,
    thread_id = excluded.thread_id,
    thread_name = excluded.thread_name,
    exception_type = excluded.exception_type,
    exception_message = excluded.exception_message,
    traceback = excluded.traceback,
    fingerprint = excluded.fingerprint,
    tags = excluded.tags,
    extra = excluded.extra,
    updated_at = excluded.updated_at,
    last_seen_at = excluded.last_seen_at
"""


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)
