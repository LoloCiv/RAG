"""Persistencia de conversaciones (Fase 5 del roadmap de mejoras). Un JSON
por conversacion en CONVERSATIONS_DIR (app/config.py), mismo patron que
app/ingestion/manifest.py.

Guarda tanto api_messages (el historial en formato Anthropic que se le
manda a run_turn/run_turn_streaming en cada turno) como display_messages
(lo que renderiza streamlit_app.py -- texto, fuentes, charts, y el
feedback thumbs up/down de cada respuesta).

api_messages trae, en los turnos de assistant, bloques de contenido
TIPADOS del SDK de Anthropic (Pydantic, ver result["response_content"] en
app/agent/claude_agent.py) -- no son JSON-serializables directo con
json.dumps. _to_json_safe() los aplana a dicts planos con
.model_dump(mode="json") antes de guardar. Al cargar, json.load() ya
devuelve todo como dicts/listas planas -- el tool_runner del SDK acepta
ese shape igual que los objetos tipados (BetaMessageParam es un TypedDict,
no exige instancias de la clase).
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import CONVERSATIONS_DIR

_TITLE_MAX_LEN = 60


def new_conversation_id() -> str:
    return uuid.uuid4().hex


def _title_from_first_message(display_messages: list[dict]) -> str:
    for msg in display_messages:
        if msg.get("role") == "user" and msg.get("text"):
            text = msg["text"].strip()
            if len(text) > _TITLE_MAX_LEN:
                return text[:_TITLE_MAX_LEN].rstrip() + "…"
            return text
    return "Conversación sin título"


def _to_json_safe(value):
    """Convierte value a algo serializable con json.dumps. Ver docstring
    del modulo -- recorre listas/dicts recursivo, aplana objetos Pydantic
    (bloques de contenido del SDK) con .model_dump(mode="json"), y deja
    todo lo demas (str, int, None, bool...) tal cual.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_json_safe(v) for k, v in value.items()}
    return value


def _path_for(conversation_id: str, conversations_dir: Path) -> Path:
    return conversations_dir / f"{conversation_id}.json"


def save_conversation(
    conversation_id: str,
    api_messages: list[dict],
    display_messages: list[dict],
    conversations_dir: Path = CONVERSATIONS_DIR,
) -> None:
    """Guarda (crea o sobreescribe) una conversacion completa. created_at
    se preserva de una version anterior si existia -- solo updated_at
    cambia en cada guardado.
    """
    existing = load_conversation(conversation_id, conversations_dir=conversations_dir)
    created_at = existing["created_at"] if existing else datetime.now(timezone.utc).isoformat()

    data = {
        "id": conversation_id,
        "created_at": created_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "title": _title_from_first_message(display_messages),
        "api_messages": _to_json_safe(api_messages),
        "display_messages": _to_json_safe(display_messages),
    }

    conversations_dir.mkdir(parents=True, exist_ok=True)
    _path_for(conversation_id, conversations_dir).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_conversation(conversation_id: str, conversations_dir: Path = CONVERSATIONS_DIR) -> dict | None:
    """Devuelve la conversacion completa (incluye api_messages y
    display_messages), o None si no existe o el archivo esta corrupto.
    """
    path = _path_for(conversation_id, conversations_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def list_conversations(conversations_dir: Path = CONVERSATIONS_DIR) -> list[dict]:
    """Metadata liviana (id/title/updated_at) de todas las conversaciones,
    ordenadas por updated_at descendente (mas reciente primero) -- para el
    selector del sidebar, sin cargar los mensajes completos de cada una.
    Un archivo corrupto se saltea en vez de romper el listado entero.
    """
    conversations_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for path in conversations_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        items.append({"id": data["id"], "title": data.get("title", ""), "updated_at": data.get("updated_at", "")})
    items.sort(key=lambda c: c["updated_at"], reverse=True)
    return items
