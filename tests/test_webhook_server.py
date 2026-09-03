"""El contrato n8n solo acepta eventos autenticados y nunca envia por si mismo."""

from starlette.testclient import TestClient

from app import webhook_server


def _headers():
    return {"authorization": "Bearer pilot-secret"}


def test_inbound_requires_bearer_token(tmp_path, monkeypatch):
    monkeypatch.setattr(webhook_server, "WORK_ITEMS_DIR", tmp_path)
    monkeypatch.setattr(webhook_server, "N8N_WEBHOOK_TOKEN", "pilot-secret")

    response = TestClient(webhook_server.app).post("/n8n/inbound", json={})

    assert response.status_code == 401


def test_inbound_approval_and_delivery_acknowledgement(tmp_path, monkeypatch):
    monkeypatch.setattr(webhook_server, "WORK_ITEMS_DIR", tmp_path)
    monkeypatch.setattr(webhook_server, "N8N_WEBHOOK_TOKEN", "pilot-secret")
    client = TestClient(webhook_server.app)
    payload = {
        "message_id": "gmail-1",
        "channel": "email",
        "supplier_name": "Buena Mesa",
        "event_name": "Cena anual",
        "text": "Mensaje entrante",
    }

    created = client.post("/n8n/inbound", json=payload, headers=_headers())
    work_item_id = created.json()["id"]
    webhook_server.work_items.set_draft(work_item_id, "Borrador aprobado", {"sources": []}, work_items_dir=tmp_path)
    webhook_server.work_items.approve_work_item(work_item_id, "laure", evidence_verified=True, work_items_dir=tmp_path)

    pending = client.get("/n8n/outbox", headers=_headers())
    sent = client.post(f"/n8n/outbox/{work_item_id}/sent", json={"external_message_id": "gmail-2"}, headers=_headers())

    assert pending.json()["items"][0]["id"] == work_item_id
    assert sent.json()["status"] == "sent"
