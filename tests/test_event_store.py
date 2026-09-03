"""La memoria compartida conserva correos sin depender de n8n ni de un LLM."""

from app.collaboration.store import EventStore


def _email(**overrides):
    payload = {
        "external_message_id": "gmail-123",
        "account_email": "sofia@auroraeventos.com",
        "thread_id": "thread-55",
        "sender": "ventas@buenamesa.com",
        "recipients": ["sofia@auroraeventos.com"],
        "cc": [],
        "subject": "Propuesta de catering",
        "body_text": "Adjuntamos la propuesta para la cena anual.",
        "labels": ["Evento/cena-anual"],
        "attachments": [],
        "received_at": "2026-09-03T12:00:00+00:00",
        "thread_url": "https://mail.google.com/mail/u/0/#all/thread-55",
    }
    payload.update(overrides)
    return payload


def test_ingest_email_suggests_event_from_event_label(tmp_path):
    store = EventStore(tmp_path / "collaboration.sqlite3")
    event = store.create_event("Cena anual")

    message = store.ingest_email(_email())

    assert message["external_message_id"] == "gmail-123"
    assert message["event_suggestion"] == {
        "event_id": event["id"],
        "state": "suggested",
        "reason": "gmail_label",
    }
    assert store.list_event_messages(event["id"]) == []


def test_confirmed_email_is_visible_in_event_timeline(tmp_path):
    store = EventStore(tmp_path / "collaboration.sqlite3")
    event = store.create_event("Cena anual")
    message = store.ingest_email(_email())

    store.confirm_event_message(event["id"], message["id"], actor_email="laure@auroraeventos.com")

    timeline = store.list_event_messages(event["id"])
    assert [item["subject"] for item in timeline] == ["Propuesta de catering"]
    assert timeline[0]["association_state"] == "confirmed"
    assert timeline[0]["thread_url"].endswith("thread-55")


def test_suggested_message_can_be_listed_before_confirmation(tmp_path):
    store = EventStore(tmp_path / "collaboration.sqlite3")
    event = store.create_event("Cena anual")
    store.ingest_email(_email())

    pending = store.list_suggested_messages(event["id"])

    assert len(pending) == 1
    assert pending[0]["association_state"] == "suggested"


def test_repeated_external_message_is_idempotent(tmp_path):
    store = EventStore(tmp_path / "collaboration.sqlite3")
    store.create_event("Cena anual")

    first = store.ingest_email(_email())
    second = store.ingest_email(_email(body_text="reintento"))

    assert second["id"] == first["id"]
    assert store.count_messages() == 1


def test_archived_event_is_hidden_from_active_list_but_keeps_history(tmp_path):
    store = EventStore(tmp_path / "collaboration.sqlite3")
    event = store.create_event("Cena anual")
    store.archive_event(event["id"], actor_email="laure@auroraeventos.com")

    assert store.list_events() == []
    assert store.list_events(include_archived=True)[0]["id"] == event["id"]
