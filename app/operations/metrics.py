"""Metricas locales del piloto para evaluar seguridad y utilidad operativa."""

from collections import Counter
from datetime import datetime
from typing import Iterable


def _as_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _event_at(record: dict, name: str) -> datetime | None:
    for entry in record.get("audit", []):
        if entry.get("event") == name:
            return _as_datetime(entry.get("at"))
    return None


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _was_sent_without_approval(record: dict) -> bool:
    """Busca violaciones en el log, incluso si un archivo fue alterado a mano."""
    approved = False
    for entry in record.get("audit", []):
        if entry.get("event") == "approved":
            approved = True
        if entry.get("event") == "sent" and not approved:
            return True
    return False


def summarize_work_items(records: Iterable[dict]) -> dict:
    """Resume tiempos y controles desde los registros persistidos del piloto.

    No infiere calidad semantica: los errores de fuente se revisan sobre la
    evidencia guardada. Asi se evita presentar una estimacion automatica como
    validacion humana de una respuesta comercial.
    """
    records = list(records)
    statuses = Counter(record.get("status", "unknown") for record in records)
    draft_times: list[float] = []
    resolution_times: list[float] = []
    approvals = 0
    approvals_without_edit = 0

    for record in records:
        created = _event_at(record, "created") or _as_datetime(record.get("created_at"))
        drafted = _event_at(record, "draft_generated")
        if created and drafted:
            draft_times.append((drafted - created).total_seconds())

        resolved = _event_at(record, "sent") or _event_at(record, "rejected")
        if created and resolved:
            resolution_times.append((resolved - created).total_seconds())

        approved_at = _event_at(record, "approved")
        if approved_at:
            approvals += 1
            edited_before_approval = any(
                entry.get("event") == "draft_edited"
                and (_as_datetime(entry.get("at")) or approved_at) <= approved_at
                for entry in record.get("audit", [])
            )
            if not edited_before_approval:
                approvals_without_edit += 1

    return {
        "total": len(records),
        "by_status": dict(sorted(statuses.items())),
        "average_seconds_to_draft": _average(draft_times),
        "average_seconds_to_resolution": _average(resolution_times),
        "approval_without_edit_rate": (approvals_without_edit / approvals) if approvals else None,
        "external_actions_without_approval": sum(_was_sent_without_approval(record) for record in records),
    }
