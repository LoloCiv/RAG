"""El endpoint de correo solo incorpora memoria; nunca inicia un envio."""

from starlette.testclient import TestClient

from app import webhook_server


def _headers():
    return {"authorization": "Bearer pilot-secret"}


def _payload():
    return {
        "external_message_id": "gmail-123",
        "account_email": "sofia@auroraeventos.com",
        "thread_id": "thread-55",
        "sender": "ventas@buenamesa.com",
        "recipients": ["sofia@auroraeventos.com"],
        "cc": [],
        "subject": "Propuesta de catering",
        "body_text": "Adjuntamos la propuesta.",
        "labels": ["Evento/cena-anual"],
        "attachments": [],
        "received_at": "2026-09-03T12:00:00+00:00",
        "thread_url": "https://mail.google.com/mail/u/0/#all/thread-55",
    }


def test_email_inbound_requires_token(tmp_path, monkeypatch):
    monkeypatch.setattr(webhook_server, "COLLABORATION_DB_PATH", tmp_path / "collaboration.sqlite3")
    monkeypatch.setattr(webhook_server, "N8N_WEBHOOK_TOKEN", "pilot-secret")

    response = TestClient(webhook_server.app).post("/n8n/email/inbound", json=_payload())

    assert response.status_code == 401


def test_email_inbound_is_saved_as_shared_event_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(webhook_server, "COLLABORATION_DB_PATH", tmp_path / "collaboration.sqlite3")
    monkeypatch.setattr(webhook_server, "N8N_WEBHOOK_TOKEN", "pilot-secret")
    webhook_server.EventStore(tmp_path / "collaboration.sqlite3").create_event("Cena anual")

    response = TestClient(webhook_server.app).post("/n8n/email/inbound", json=_payload(), headers=_headers())

    assert response.status_code == 201
    assert response.json()["event_suggestion"]["state"] == "suggested"
