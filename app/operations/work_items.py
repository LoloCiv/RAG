"""Persistencia del trabajo comercial que requiere revision humana.

El registro separa propuesta y envio para que n8n nunca pueda interpretar un
borrador como permiso para comunicarse con un proveedor.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import WORK_ITEMS_DIR

_ACTIVE_STATUSES = {"needs_review", "approved", "sent", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_for(work_item_id: str, work_items_dir: Path) -> Path:
    return work_items_dir / f"{work_item_id}.json"


def _write(record: dict, work_items_dir: Path) -> dict:
    work_items_dir.mkdir(parents=True, exist_ok=True)
    record["updated_at"] = _now()
    _path_for(record["id"], work_items_dir).write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return record


def _audit(record: dict, event: str, actor: str, details: dict | None = None) -> None:
    record["audit"].append({"at": _now(), "event": event, "actor": actor, "details": details or {}})


def load_work_item(work_item_id: str, work_items_dir: Path = WORK_ITEMS_DIR) -> dict | None:
    path = _path_for(work_item_id, work_items_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def list_work_items(work_items_dir: Path = WORK_ITEMS_DIR) -> list[dict]:
    """Lista el trabajo reciente sin dejar que un archivo corrupto bloquee la bandeja."""
    work_items_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for path in work_items_dir.glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(records, key=lambda record: record.get("updated_at", ""), reverse=True)


def _find_existing(payload: dict, work_items_dir: Path) -> tuple[dict | None, bool]:
    thread_key = payload.get("thread_key") or f"{payload['channel']}:{payload['supplier_name']}:{payload.get('event_name', '')}"
    for record in list_work_items(work_items_dir):
        for message in record.get("messages", []):
            if message.get("message_id") == payload["message_id"]:
                return record, True
        if record.get("thread_key") == thread_key and record.get("status") != "sent":
            return record, False
    return None, False


def ingest_message(payload: dict, work_items_dir: Path = WORK_ITEMS_DIR) -> dict:
    """Normaliza eventos de n8n y abre o actualiza una oportunidad revisable."""
    required = {"message_id", "channel", "supplier_name", "text"}
    missing = required - payload.keys()
    if missing:
        raise ValueError("Faltan campos del mensaje: " + ", ".join(sorted(missing)))
    if payload["channel"] not in {"email", "whatsapp"}:
        raise ValueError("channel debe ser email o whatsapp")

    record, duplicate = _find_existing(payload, work_items_dir)
    if duplicate:
        return record
    message = {
        "message_id": payload["message_id"],
        "direction": "inbound",
        "channel": payload["channel"],
        "text": payload["text"],
        "received_at": payload.get("received_at") or _now(),
        "attachments": payload.get("attachments", []),
    }
    if record is None:
        record = {
            "id": uuid.uuid4().hex,
            "created_at": _now(),
            "updated_at": _now(),
            "status": "needs_review",
            "thread_key": payload.get("thread_key") or f"{payload['channel']}:{payload['supplier_name']}:{payload.get('event_name', '')}",
            "event_name": payload.get("event_name", ""),
            "supplier_name": payload["supplier_name"],
            "channel": payload["channel"],
            "messages": [message],
            "draft": None,
            "evidence": None,
            "analysis": None,
            "review": None,
            "approved_by": None,
            "rejection_reason": None,
            "delivery": None,
            "audit": [],
        }
        _audit(record, "created", "n8n", {"message_id": message["message_id"]})
    else:
        record["messages"].append(message)
        record["status"] = "needs_review"
        record["draft"] = None
        record["evidence"] = None
        record["analysis"] = None
        record["review"] = None
        record["approved_by"] = None
        record["rejection_reason"] = None
        record["delivery"] = None
        _audit(record, "message_received", "n8n", {"message_id": message["message_id"]})
    return _write(record, work_items_dir)


def set_draft(work_item_id: str, text: str, evidence: dict, work_items_dir: Path = WORK_ITEMS_DIR) -> dict:
    record = _require(work_item_id, work_items_dir)
    if record["status"] != "needs_review":
        raise ValueError("Solo se puede proponer un borrador para trabajo en revision")
    record["draft"] = {"text": text, "generated_at": _now()}
    record["evidence"] = evidence
    _audit(record, "draft_generated", "agent", {"query_id": evidence.get("query_id")})
    return _write(record, work_items_dir)


def set_analysis(work_item_id: str, classification: dict, fields: dict, work_items_dir: Path = WORK_ITEMS_DIR) -> dict:
    """Conserva la lectura estructurada para que la persona pueda corregirla despues."""
    record = _require(work_item_id, work_items_dir)
    if record["status"] != "needs_review":
        raise ValueError("Solo se puede analizar trabajo pendiente de revision")
    record["analysis"] = {"classification": classification, "fields": fields, "generated_at": _now()}
    _audit(record, "message_analyzed", "agent")
    return _write(record, work_items_dir)


def edit_draft(work_item_id: str, text: str, actor: str, work_items_dir: Path = WORK_ITEMS_DIR) -> dict:
    """Registra la edicion humana para distinguirla de lo que propuso el agente."""
    record = _require(work_item_id, work_items_dir)
    if record["status"] != "needs_review" or not record.get("draft"):
        raise ValueError("Solo se puede editar un borrador pendiente de revision")
    record["draft"]["text"] = text
    record["draft"]["edited_at"] = _now()
    _audit(record, "draft_edited", actor)
    return _write(record, work_items_dir)


def approve_work_item(
    work_item_id: str,
    actor: str,
    evidence_verified: bool = False,
    work_items_dir: Path = WORK_ITEMS_DIR,
) -> dict:
    record = _require(work_item_id, work_items_dir)
    if record["status"] != "needs_review":
        raise ValueError("Solo se puede aprobar trabajo pendiente de revision")
    if not (record.get("draft") or {}).get("text", "").strip():
        # Un item sin texto no es una comunicacion revisable y no debe llegar
        # a n8n como candidato de envio.
        raise ValueError("No se puede aprobar un work item sin borrador")
    if not evidence_verified:
        raise ValueError("Hay que confirmar la revision de evidencia antes de aprobar")
    record["status"] = "approved"
    record["approved_by"] = actor
    record["review"] = {"evidence_verified": True, "reviewed_at": _now(), "reviewed_by": actor}
    record["delivery"] = {"state": "pending", "requested_at": _now(), "external_message_id": None, "error": None}
    _audit(record, "approved", actor, {"evidence_verified": True})
    return _write(record, work_items_dir)


def reject_work_item(work_item_id: str, actor: str, reason: str, work_items_dir: Path = WORK_ITEMS_DIR) -> dict:
    record = _require(work_item_id, work_items_dir)
    if record["status"] != "needs_review":
        raise ValueError("Solo se puede rechazar trabajo pendiente de revision")
    record["status"] = "rejected"
    record["rejection_reason"] = reason
    _audit(record, "rejected", actor, {"reason": reason})
    return _write(record, work_items_dir)


def list_delivery_candidates(work_items_dir: Path = WORK_ITEMS_DIR) -> list[dict]:
    """n8n consulta solo elementos aprobados; esta funcion nunca entrega mensajes."""
    return [record for record in list_work_items(work_items_dir) if record["status"] == "approved" and record.get("delivery", {}).get("state") == "pending"]


def mark_delivery_sent(work_item_id: str, external_message_id: str, work_items_dir: Path = WORK_ITEMS_DIR) -> dict:
    record = _require(work_item_id, work_items_dir)
    if record["status"] != "approved" or record.get("delivery", {}).get("state") != "pending":
        raise ValueError("Solo se puede confirmar una entrega aprobada pendiente")
    record["status"] = "sent"
    record["delivery"].update({"state": "sent", "external_message_id": external_message_id, "sent_at": _now()})
    _audit(record, "sent", "n8n", {"external_message_id": external_message_id})
    return _write(record, work_items_dir)


def mark_delivery_failed(work_item_id: str, error: str, work_items_dir: Path = WORK_ITEMS_DIR) -> dict:
    record = _require(work_item_id, work_items_dir)
    if record["status"] != "approved":
        raise ValueError("Solo se puede registrar un fallo de entrega aprobada")
    record["delivery"].update({"state": "pending", "error": error})
    _audit(record, "delivery_failed", "n8n", {"error": error})
    return _write(record, work_items_dir)


def _require(work_item_id: str, work_items_dir: Path) -> dict:
    record = load_work_item(work_item_id, work_items_dir)
    if record is None:
        raise ValueError("No existe el work item")
    if record.get("status") not in _ACTIVE_STATUSES:
        raise ValueError("El work item tiene un estado invalido")
    return record
