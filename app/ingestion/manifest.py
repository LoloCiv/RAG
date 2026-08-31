"""Registro local de que se ingirio y cuando, para que el resync sea
idempotente: si un archivo de Drive no cambio (mismo modifiedTime), no lo
volvemos a embeber (ahorra costo de OpenAI y tiempo en cada demo).

Formato de data/manifest.json:
{
  "<drive_file_id>": {
    "file_name": str,
    "mime_type": str,
    "modified_time": str,   # ISO 8601, tal cual lo devuelve Drive
    "source_ids": [str],    # uno para PDF/Doc, uno por tab para sheets
    "last_ingested_at": str # ISO 8601, hora local de la ultima ingesta
  },
  ...
}
"""

import json
import logging
from datetime import datetime, timezone

from app.config import MANIFEST_PATH

logger = logging.getLogger(__name__)


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("manifest.json corrupto, se reinicia vacio")
        return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def needs_reingest(manifest: dict, drive_file_id: str, modified_time: str) -> bool:
    entry = manifest.get(drive_file_id)
    if entry is None:
        return True
    return entry.get("modified_time") != modified_time


def record_ingested(
    manifest: dict,
    drive_file_id: str,
    file_name: str,
    mime_type: str,
    modified_time: str,
    source_ids: list[str],
) -> None:
    manifest[drive_file_id] = {
        "file_name": file_name,
        "mime_type": mime_type,
        "modified_time": modified_time,
        "source_ids": source_ids,
        "last_ingested_at": datetime.now(timezone.utc).isoformat(),
    }
