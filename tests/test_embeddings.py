from __future__ import annotations

import sqlite3

from cognit.capture.event import LogEvent
from cognit.embeddings import LocalHashEmbedder, SimilarIncidentRetriever, build_embedding_text
from cognit.storage.sqlite_store import SQLiteStore


def _event(incident_id: str, fingerprint: str, *, app_name: str = "demo", environment: str = "test", message: str) -> LogEvent:
    return LogEvent(
        incident_id=incident_id,
        app_name=app_name,
        environment=environment,
        level="ERROR",
        levelno=40,
        message=message,
        logger_name="demo",
        timestamp="2026-05-13T12:00:00.000000Z",
        pathname="/srv/app.py",
        filename="app.py",
        module="app",
        function="explode",
        line_number=10,
        process_id=123,
        process_name="MainProcess",
        thread_id=456,
        thread_name="MainThread",
        exception_type="RuntimeError",
        exception_message="database connection timeout",
        traceback="Traceback...",
        fingerprint=fingerprint,
    )


def test_local_hash_embeddings_are_stable():
    embedder = LocalHashEmbedder(dimensions=256)

    first = embedder.embed("Database connection timeout in orders service")
    second = embedder.embed("Database connection timeout in orders service")

    assert first == second
    assert len(first) == 256


def test_related_texts_score_higher_than_unrelated_texts():
    embedder = LocalHashEmbedder(dimensions=256)

    anchor = embedder.embed("database timeout while reading orders table")
    related = embedder.embed("orders database timeout and connection retry")
    unrelated = embedder.embed("user profile avatar upload completed successfully")

    related_score = sum(a * b for a, b in zip(anchor, related))
    unrelated_score = sum(a * b for a, b in zip(anchor, unrelated))

    assert related_score > unrelated_score


def test_similar_incident_retrieval_prefers_same_app_and_environment(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    embedder = LocalHashEmbedder(dimensions=256)
    retriever = SimilarIncidentRetriever(store, limit=3)

    anchor_event = _event("cog_anchor", "fp-anchor", message="orders database timeout while fetching invoice")
    same_env_event = _event("cog_same", "fp-same", message="invoice database timeout in orders flow")
    other_env_event = _event(
        "cog_other",
        "fp-other",
        app_name="other-app",
        environment="prod",
        message="invoice database timeout in orders flow",
    )
    unrelated_event = _event("cog_unrelated", "fp-unrelated", message="image resize completed successfully")

    for event in (anchor_event, same_env_event, other_env_event, unrelated_event):
        store.save_incident(event)
        text = build_embedding_text(event)
        store.save_embedding(event.incident_id, embedder.embed(text), embedder.text_hash(text))

    query = embedder.embed(build_embedding_text(anchor_event))
    results = retriever.find_similar(anchor_event, query, incident_id="cog_anchor")

    assert [incident.incident_id for incident in results][:2] == ["cog_same", "cog_other"]
    assert "cog_anchor" not in [incident.incident_id for incident in results]


def test_corrupt_embeddings_are_skipped(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    embedder = LocalHashEmbedder(dimensions=256)
    query_event = _event("cog_query", "fp-query", message="database timeout in orders")
    valid_event = _event("cog_valid", "fp-valid", message="orders database timeout while processing payment")
    corrupt_event = _event("cog_corrupt", "fp-corrupt", message="orders database timeout while processing payment")

    for event in (query_event, valid_event, corrupt_event):
        store.save_incident(event)

    valid_text = build_embedding_text(valid_event)
    store.save_embedding("cog_valid", embedder.embed(valid_text), embedder.text_hash(valid_text))

    with sqlite3.connect(tmp_path / "cognit.db") as connection:
        connection.execute(
            "INSERT INTO embeddings (incident_id, embedding, dimensions, text_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            ("cog_corrupt", "not-json", 256, "broken", "2026-05-13T12:00:00.000000Z"),
        )
        connection.commit()

    results = store.find_similar_incidents(
        embedder.embed(build_embedding_text(query_event)),
        exclude_incident_id="cog_query",
        app_name="demo",
        environment="test",
    )

    assert [incident.incident_id for incident in results] == ["cog_valid"]


def test_wrong_dimension_embeddings_are_skipped(tmp_path):
    store = SQLiteStore(tmp_path / "cognit.db")
    embedder = LocalHashEmbedder(dimensions=256)
    query_event = _event("cog_query", "fp-query", message="database timeout in orders")
    wrong_dim_event = _event("cog_wrong", "fp-wrong", message="orders database timeout while processing payment")

    for event in (query_event, wrong_dim_event):
        store.save_incident(event)

    with sqlite3.connect(tmp_path / "cognit.db") as connection:
        connection.execute(
            "INSERT INTO embeddings (incident_id, embedding, dimensions, text_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            ("cog_wrong", "[0.1, 0.2, 0.3]", 3, "wrong-dim", "2026-05-13T12:00:00.000000Z"),
        )
        connection.commit()

    results = store.find_similar_incidents(
        embedder.embed(build_embedding_text(query_event)),
        exclude_incident_id="cog_query",
        app_name="demo",
        environment="test",
    )

    assert results == []
