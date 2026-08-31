"""Esquema de source_id y de IDs de punto deterministicos para Qdrant.

Ver la seccion "Ingesta de Google Drive" del plan
(C:\\Users\\Laure\\.claude\\plans\\me-gustaria-hacer-la-mutable-pixel.md) para
el razonamiento completo. Resumen:

- source_id de un PDF o Google Doc: "gdrive:{drive_file_id}"
- source_id de un tab de una Sheet/Excel: "gdrive:{drive_file_id}:{tab_name}"
  (cada tab es su propia unidad semantica, ej. "Proveedores" vs "Presupuesto Q3")

- Los IDs de punto en Qdrant son uuid5 deterministicos, namespaced por tipo de
  contenido (chunk de texto vs blob de tabla), para que:
  (a) re-ingerir el mismo archivo sin cambios produzca los mismos IDs
      (upsert idempotente, no duplica puntos), y
  (b) un chunk de texto y el blob de tabla del mismo source_id nunca choquen
      de ID entre si.
"""

import uuid

_NAMESPACE = uuid.NAMESPACE_URL


def pdf_or_doc_source_id(drive_file_id: str) -> str:
    return f"gdrive:{drive_file_id}"


def sheet_tab_source_id(drive_file_id: str, tab_name: str) -> str:
    return f"gdrive:{drive_file_id}:{tab_name}"


def drive_view_url(source_id: str) -> str | None:
    """Link a Drive del archivo duenio de un source_id (Fase 3 del roadmap
    de mejoras -- "fuentes legibles" en la UI). Un tab de sheet no tiene
    URL propia: apunta al archivo (spreadsheet) completo, mismo
    drive_file_id que cualquier otro tab de ese archivo.

    None si source_id no tiene el prefijo "gdrive:" esperado -- defensivo,
    para que la UI no muestre un link roto ante un formato inesperado.
    """
    if not source_id.startswith("gdrive:"):
        return None
    drive_file_id = source_id.split(":")[1]
    return f"https://drive.google.com/file/d/{drive_file_id}/view"


def text_chunk_point_id(source_id: str, chunk_index: int) -> str:
    """ID deterministico para un punto de tipo 'text_chunk' en Qdrant."""
    return str(uuid.uuid5(_NAMESPACE, f"{source_id}:chunk:{chunk_index}"))


def table_blob_point_id(source_id: str) -> str:
    """ID deterministico para el (unico) punto 'table_data' de un source_id."""
    return str(uuid.uuid5(_NAMESPACE, f"{source_id}:table"))
