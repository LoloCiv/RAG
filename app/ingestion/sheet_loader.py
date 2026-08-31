"""Ingesta de planillas (Google Sheets nativas y .xlsx subidos a Drive).

Cada tab de una planilla produce DOS artefactos (ver seccion "Ingesta de
Google Drive" del plan):

  1. Chunks de texto semanticos (resumen de columnas + una oracion por fila)
     -- para que search_knowledge_base la encuentre por significado
     ("que archivo tiene precios de catering").
  2. Un "table blob": la tabla cruda completa (columnas + filas como dicts)
     -- para que get_source_table le de a Claude los numeros exactos al
     armar un grafico. La busqueda semantica sola NO alcanza para esto:
     un chunk de texto es una aproximacion difusa, no una tabla exacta.

Ambos casos (Sheet nativa vs .xlsx) convergen en un pandas.DataFrame antes de
armar los dos artefactos, para no duplicar esa logica.
"""

import io
import logging
from dataclasses import dataclass, field

import pandas as pd

from app.config import MAX_TABLE_ROWS
from app.ingestion import drive_client
from app.ingestion.source_id import sheet_tab_source_id

logger = logging.getLogger(__name__)


@dataclass
class TabData:
    tab_name: str
    source_id: str
    text_chunks: list[str]
    columns: list[str]
    rows: list[dict] = field(repr=False)
    row_count: int
    truncated: bool


def load_native_sheet(spreadsheet_id: str, file_name: str) -> list[TabData]:
    """Google Sheet nativa: un tab a la vez via la Sheets API (el export CSV
    de Drive solo cubre un tab por vez, por eso no se usa aca)."""
    tabs = drive_client.get_sheet_tabs(spreadsheet_id)
    results = []
    for tab in tabs:
        tab_name = tab["title"]
        rows = drive_client.get_sheet_tab_values(spreadsheet_id, tab_name)
        if not rows:
            logger.warning("Tab '%s' de %s esta vacio, se saltea", tab_name, file_name)
            continue
        df = _rows_to_dataframe(rows)
        results.append(_dataframe_to_tab_data(df, spreadsheet_id, tab_name, file_name))
    return results


def load_uploaded_xlsx(xlsx_bytes: bytes, drive_file_id: str, file_name: str) -> list[TabData]:
    """.xlsx subido como binario a Drive: pandas.read_excel con sheet_name=None
    trae todos los tabs de una sola pasada (no hace falta Sheets API, es un
    archivo binario comun)."""
    sheets = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name=None)
    results = []
    for tab_name, df in sheets.items():
        if df.empty:
            logger.warning("Tab '%s' de %s esta vacio, se saltea", tab_name, file_name)
            continue
        results.append(_dataframe_to_tab_data(df, drive_file_id, tab_name, file_name))
    return results


def _rows_to_dataframe(rows: list[list]) -> pd.DataFrame:
    header, *data_rows = rows
    # Las filas de Sheets pueden venir mas cortas que el header (celdas
    # vacias al final se omiten) -- rellenamos para que todas las filas
    # tengan la misma cantidad de columnas que el header.
    normalized = [row + [""] * (len(header) - len(row)) for row in data_rows]
    return pd.DataFrame(normalized, columns=header)


def _dataframe_to_tab_data(df: pd.DataFrame, drive_file_id: str, tab_name: str, file_name: str) -> TabData:
    source_id = sheet_tab_source_id(drive_file_id, tab_name)
    total_rows = len(df)
    truncated = total_rows > MAX_TABLE_ROWS
    if truncated:
        logger.warning(
            "Tab '%s' de %s tiene %d filas, se trunca a %d para el table blob",
            tab_name,
            file_name,
            total_rows,
            MAX_TABLE_ROWS,
        )
        df = df.head(MAX_TABLE_ROWS)

    columns = [str(c) for c in df.columns]
    rows = df.astype(str).to_dict(orient="records")

    text_chunks = _build_text_chunks(tab_name, columns, rows)

    return TabData(
        tab_name=tab_name,
        source_id=source_id,
        text_chunks=text_chunks,
        columns=columns,
        rows=rows,
        row_count=total_rows,
        truncated=truncated,
    )


def _build_text_chunks(tab_name: str, columns: list[str], rows: list[dict]) -> list[str]:
    """Representacion textual pensada para embedding/busqueda semantica, no
    para calculo exacto (eso lo resuelve el table blob via get_source_table).
    """
    header_summary = f"Planilla '{tab_name}' con columnas: {', '.join(columns)}. {len(rows)} filas."
    chunks = [header_summary]

    row_sentences = []
    for i, row in enumerate(rows, start=1):
        parts = ", ".join(f"{col}={row.get(col, '')}" for col in columns)
        row_sentences.append(f"Fila {i}: {parts}")

    # Agrupamos varias filas por chunk (no una oracion por chunk) para no
    # generar miles de puntos diminutos en Qdrant en planillas grandes.
    batch_size = 20
    for start in range(0, len(row_sentences), batch_size):
        chunks.append("\n".join(row_sentences[start : start + batch_size]))

    return chunks
