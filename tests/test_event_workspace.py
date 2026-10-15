"""La organización conserva evidencia y separa antecedentes de correo actual."""

import json
import sqlite3

import pytest

from app.agent import queries
from app.collaboration.store import EventStore
from tests.test_event_store import _email


@pytest.fixture
def workspace(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    event = store.create_event("Cena anual")
    return store, event


def _confirmed(store, event, identifier, **fields):
    message = store.ingest_email(_email(external_message_id=identifier, **fields))
    store.confirm_event_message(event["id"], message["id"], "reviewer@company.com")
    return message


def test_conversations_group_by_account_and_thread_and_sort_actual_instants(workspace):
    store, event = workspace
    _confirmed(store, event, "a", received_at="2026-09-03T12:00:00+00:00")
    _confirmed(store, event, "b", received_at="2026-09-03T10:00:00-03:00")
    _confirmed(store, event, "c", account_email="other@company.com", received_at="2026-09-03T12:30:00+00:00")
    page = store.list_conversations(event["id"])
    assert page["total"] == 2
    assert [m["external_message_id"] for m in page["items"][0]["messages"]] == ["a", "b"]
    assert page["items"][1]["account_email"] == "other@company.com"


def test_filters_select_threads_but_preserve_full_conversation(workspace):
    store, event = workspace
    _confirmed(store, event, "a", subject="Catering", body_text="Menú vegetariano", sender="chef@example.com")
    _confirmed(store, event, "b", subject="Respuesta", body_text="Confirmado", sender="team@example.com", received_at="2026-09-04T12:00:00Z")
    _confirmed(store, event, "c", thread_id="other", subject="Música", body_text="DJ")
    page = store.list_conversations(event["id"], search="VEGETARIANO", sender="chef@example.com", account_email="sofia@auroraeventos.com", date_from="2026-09-03", date_to="2026-09-03")
    assert page["total"] == 1
    assert len(page["items"][0]["messages"]) == 2
    assert store.list_conversations(event["id"], search="no existe")["total"] == 0
    assert store.list_conversations(event["id"], date_from="2026-09-06")["total"] == 0


def test_conversations_are_paginated_and_event_scoped(workspace):
    store, event = workspace
    for number in range(21):
        _confirmed(store, event, str(number), thread_id=f"thread-{number}")
    other = store.create_event("Otro")
    _confirmed(store, other, "outside")
    store.ingest_email(_email(external_message_id="pending"))
    first = store.list_conversations(event["id"])
    second = store.list_conversations(event["id"], page=2)
    assert first["total"] == 21
    assert len(first["items"]) == 20
    assert len(second["items"]) == 1
    assert not ({i["thread_id"] for i in first["items"]} & {i["thread_id"] for i in second["items"]})
    assert store.event_counts(event["id"]) == {"confirmed": 21, "pending": 1, "references": 0}


def test_pending_general_and_event_pages_and_reassignment(workspace):
    store, event = workspace
    unassigned = store.ingest_email(_email(external_message_id="unassigned", labels=[]))
    suggested = store.ingest_email(_email(external_message_id="suggested"))
    assert store.list_pending_messages()["items"][0]["id"] == unassigned["id"]
    assert store.list_pending_messages(event["id"])["items"][0]["id"] == suggested["id"]
    other = store.create_event("Otro")
    store.confirm_event_message(other["id"], suggested["id"], "reviewer")
    assert store.list_pending_messages(event["id"])["total"] == 0
    assert store.list_conversations(event["id"])["total"] == 0
    assert store.list_conversations(other["id"])["total"] == 1
    for number in range(20):
        store.ingest_email(_email(external_message_id=f"free-{number}", labels=[]))
    assert len(store.list_pending_messages()["items"]) == 20
    assert len(store.list_pending_messages(page=2)["items"]) == 1


def test_links_are_idempotent_audited_and_can_span_events(workspace, tmp_path):
    store, event = workspace
    folder = tmp_path / "queries"
    query = queries.save_query(queries.new_query_id(), "Presupuesto histórico", {"answer_text": "Respuesta", "sources": [{"file_name": "costos.xlsx"}]}, queries_dir=folder)
    other = store.create_event("Otro")
    store.link_query(event["id"], query["id"], "first", queries_dir=folder)
    store.link_query(event["id"], query["id"], "second", queries_dir=folder)
    store.link_query(other["id"], query["id"], "second", queries_dir=folder)
    links = store.list_query_links(event["id"])
    assert len(links) == 1
    assert links[0]["saved_by"] == "first"
    assert store.event_counts(event["id"])["references"] == 1
    store.unlink_query(event["id"], query["id"], "first")
    assert store.list_query_links(event["id"]) == []
    assert queries.load_query(query["id"], folder) == query
    assert len(store.list_query_links(other["id"])) == 1
    with sqlite3.connect(store.db_path) as connection:
        audit = connection.execute("SELECT event_name, details_json FROM audit_events WHERE event_name LIKE 'query_%'").fetchall()
    assert [row[0] for row in audit] == ["query_linked", "query_linked", "query_unlinked"]
    assert json.loads(audit[0][1])["query_id"] == query["id"]


def test_links_reject_missing_queries_and_survive_missing_files(workspace, tmp_path):
    store, event = workspace
    folder = tmp_path / "queries"
    with pytest.raises(ValueError):
        store.link_query(event["id"], "missing", "actor", queries_dir=folder)
    with pytest.raises(ValueError):
        store.link_query(event["id"], "../outside", "actor", queries_dir=folder)
    query = queries.save_query(queries.new_query_id(), "Pregunta", {}, queries_dir=folder)
    store.link_query(event["id"], query["id"], "actor", queries_dir=folder)
    (folder / f"{query['id']}.json").unlink()
    assert len(store.list_query_links(event["id"])) == 1
    store.unlink_query(event["id"], query["id"], "actor")
    assert store.list_query_links(event["id"]) == []


def test_archived_event_keeps_history_but_rejects_new_associations(workspace, tmp_path):
    store, event = workspace
    message = _confirmed(store, event, "confirmed")
    query = queries.save_query(queries.new_query_id(), "Pregunta", {}, queries_dir=tmp_path)
    store.link_query(event["id"], query["id"], "actor", queries_dir=tmp_path)
    store.archive_event(event["id"], "actor")
    assert store.list_conversations(event["id"])["total"] == 1
    assert len(store.list_query_links(event["id"])) == 1
    with pytest.raises(ValueError):
        store.confirm_event_message(event["id"], message["id"], "actor")
    with pytest.raises(ValueError):
        store.link_query(event["id"], query["id"], "actor", queries_dir=tmp_path)


def test_additive_migration_preserves_legacy_events_and_mail(workspace):
    store, event = workspace
    _confirmed(store, event, "legacy")
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("DROP TABLE IF EXISTS event_query_links")
    migrated = EventStore(store.db_path)
    assert migrated.list_events() == [event]
    assert migrated.list_event_messages(event["id"])[0]["external_message_id"] == "legacy"
    assert migrated.list_query_links(event["id"]) == []
