"""Log append-only del buzon: un JSON independiente por consulta.

``raw_messages`` se conserva porque los bloques exactos del runner fueron
indispensables para diagnosticar fallos de multi-round-trip. Es material de
auditoria y nunca se reenvia a la API: el buzon es single-shot por diseno.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import QUERIES_DIR

_TITLE_MAX_LEN = 60


def new_query_id() -> str:
    return uuid.uuid4().hex


def _title_from_question(question: str) -> str:
    text = question.strip()
    return text[:_TITLE_MAX_LEN].rstrip() + "…" if len(text) > _TITLE_MAX_LEN else text


def _to_json_safe(value):
    """Aplana bloques Pydantic porque el SDK no entrega JSON plano."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_json_safe(item) for key, item in value.items()}
    return value


def _path_for(query_id: str, queries_dir: Path) -> Path:
    return queries_dir / f"{query_id}.json"


def save_query(query_id: str, question: str, result: dict, references: list[str] | None = None, queries_dir: Path = QUERIES_DIR) -> dict:
    """Mapea el contrato del agente en un unico punto y persiste el registro."""
    record = {
        "id": query_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": _title_from_question(question),
        "question": question,
        "references": list(references or []),
        "answer_text": result.get("answer_text", ""),
        "sources": result.get("sources", []),
        "chart_paths": result.get("chart_paths", []),
        "feedback": None,
        "raw_messages": _to_json_safe(result.get("new_messages", [])),
        # Conservamos la espera observada por la persona para comparar los
        # modos rápido/profundo y detectar regresiones del agente.
        "elapsed_ms": result.get("elapsed_ms"),
    }
    queries_dir.mkdir(parents=True, exist_ok=True)
    _path_for(query_id, queries_dir).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def load_query(query_id: str, queries_dir: Path = QUERIES_DIR) -> dict | None:
    """Tolera archivos ausentes o corruptos para no romper todo el buzon."""
    path = _path_for(query_id, queries_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def list_queries(queries_dir: Path = QUERIES_DIR) -> list[dict]:
    """Devuelve metadata liviana, mas reciente primero."""
    queries_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for path in queries_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        items.append({"id": data["id"], "title": data.get("title", ""), "created_at": data.get("created_at", "")})
    return sorted(items, key=lambda item: item["created_at"], reverse=True)


def set_feedback(query_id: str, feedback: str | None, queries_dir: Path = QUERIES_DIR) -> None:
    """Limita la unica mutacion posterior al campo de feedback."""
    record = load_query(query_id, queries_dir)
    if record is None:
        return
    record["feedback"] = feedback
    _path_for(query_id, queries_dir).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
