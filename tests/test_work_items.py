"""El piloto conserva cada decision comercial como un registro durable."""

from app.operations.work_items import (
    approve_work_item,
    ingest_message,
    list_delivery_candidates,
    load_work_item,
    mark_delivery_sent,
    edit_draft,
    reject_work_item,
    set_draft,
)
import pytest


def _inbound(**overrides):
    data = {
        "message_id": "gmail-123",
        "channel": "email",
        "supplier_name": "Catering Buena Mesa",
        "event_name": "Cena anual",
        "text": "Podemos enviar una propuesta el viernes.",
        "received_at": "2026-09-03T12:00:00+00:00",
    }
    data.update(overrides)
    return data


def test_ingest_message_creates_a_reviewable_work_item(tmp_path):
    record = ingest_message(_inbound(), work_items_dir=tmp_path)

    assert record["status"] == "needs_review"
    assert record["supplier_name"] == "Catering Buena Mesa"
    assert record["messages"][0]["direction"] == "inbound"
    assert record["audit"][0]["event"] == "created"


def test_ingest_message_deduplicates_external_message_id(tmp_path):
    first = ingest_message(_inbound(), work_items_dir=tmp_path)
    second = ingest_message(_inbound(text="duplicado"), work_items_dir=tmp_path)

    assert second["id"] == first["id"]
    assert len(second["messages"]) == 1


def test_approval_creates_a_delivery_candidate_without_sending(tmp_path):
    record = ingest_message(_inbound(), work_items_dir=tmp_path)
    set_draft(record["id"], "Borrador para enviar", {"sources": []}, work_items_dir=tmp_path)

    approved = approve_work_item(record["id"], "laure", evidence_verified=True, work_items_dir=tmp_path)

    assert approved["status"] == "approved"
    assert approved["approved_by"] == "laure"
    assert approved["review"]["evidence_verified"] is True
    assert approved["delivery"]["state"] == "pending"
    assert [item["id"] for item in list_delivery_candidates(tmp_path)] == [record["id"]]


def test_rejected_item_never_enters_delivery_queue(tmp_path):
    record = ingest_message(_inbound(), work_items_dir=tmp_path)

    rejected = reject_work_item(record["id"], "laure", "Falta confirmar fecha", work_items_dir=tmp_path)

    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "Falta confirmar fecha"
    assert list_delivery_candidates(tmp_path) == []


def test_n8n_confirmation_marks_item_as_sent_and_audits_it(tmp_path):
    record = ingest_message(_inbound(), work_items_dir=tmp_path)
    set_draft(record["id"], "Borrador para enviar", {"sources": []}, work_items_dir=tmp_path)
    approve_work_item(record["id"], "laure", evidence_verified=True, work_items_dir=tmp_path)

    sent = mark_delivery_sent(record["id"], "gmail-out-456", work_items_dir=tmp_path)

    assert sent["status"] == "sent"
    assert sent["delivery"]["external_message_id"] == "gmail-out-456"
    assert sent["audit"][-1]["event"] == "sent"
    assert load_work_item(record["id"], work_items_dir=tmp_path)["status"] == "sent"


def test_human_can_edit_draft_before_approval(tmp_path):
    record = ingest_message(_inbound(), work_items_dir=tmp_path)
    set_draft(record["id"], "borrador inicial", {"sources": []}, work_items_dir=tmp_path)
    updated = edit_draft(record["id"], "borrador corregido", "laure", work_items_dir=tmp_path)

    assert updated["draft"]["text"] == "borrador corregido"
    assert updated["audit"][-1]["event"] == "draft_edited"


def test_item_without_draft_cannot_be_approved_for_delivery(tmp_path):
    record = ingest_message(_inbound(), work_items_dir=tmp_path)

    with pytest.raises(ValueError, match="borrador"):
        approve_work_item(record["id"], "laure", work_items_dir=tmp_path)


def test_item_requires_evidence_review_before_approval(tmp_path):
    record = ingest_message(_inbound(), work_items_dir=tmp_path)
    set_draft(record["id"], "Borrador", {"sources": []}, work_items_dir=tmp_path)

    with pytest.raises(ValueError, match="evidencia"):
        approve_work_item(record["id"], "laure", work_items_dir=tmp_path)
