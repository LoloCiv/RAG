"""Cliente delgado sobre las APIs de Google Drive y Sheets.

Encapsula las tres operaciones que necesita el pipeline de ingesta:
listar archivos de una carpeta, bajar los bytes crudos de un archivo, y
exportar un Google Doc a texto plano. La logica de "que hacer con esos
bytes" vive en los *_loader.py, no aca.
"""

import io
import logging

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app.ingestion.drive_auth import get_credentials

logger = logging.getLogger(__name__)

# MIME types que el pipeline sabe procesar (ver pipeline.py:LOADER_BY_MIMETYPE)
MIMETYPE_PDF = "application/pdf"
MIMETYPE_GDOC = "application/vnd.google-apps.document"
MIMETYPE_GSHEET = "application/vnd.google-apps.spreadsheet"
MIMETYPE_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DriveApiError(RuntimeError):
    """Error de alto nivel para fallos de la API de Drive/Sheets, ya
    clasificado (ver pipeline.py para como se usa cada campo)."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _drive_service():
    creds = get_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _sheets_service():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def list_folder_files(folder_id: str) -> list[dict]:
    """Lista todos los archivos (no carpetas) dentro de una carpeta de Drive.

    Cada item: {"id", "name", "mimeType", "modifiedTime"}.
    No recursivo (no baja a subcarpetas) -- alcanza para el POC.
    """
    service = _drive_service()
    files: list[dict] = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed=false"

    try:
        while True:
            response = (
                service.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                    pageToken=page_token,
                )
                .execute()
            )
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as e:
        raise DriveApiError(f"Error listando la carpeta de Drive {folder_id}: {e}", status_code=e.resp.status) from e

    return files


def download_bytes(file_id: str) -> bytes:
    """Baja el contenido crudo de un archivo binario (PDF, .xlsx subido)."""
    service = _drive_service()
    try:
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()
    except HttpError as e:
        raise DriveApiError(f"Error bajando el archivo {file_id}: {e}", status_code=e.resp.status) from e


def export_text(file_id: str) -> str:
    """Exporta un Google Doc nativo a texto plano."""
    service = _drive_service()
    try:
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        return content.decode("utf-8") if isinstance(content, bytes) else content
    except HttpError as e:
        raise DriveApiError(f"Error exportando el Google Doc {file_id}: {e}", status_code=e.resp.status) from e


def get_sheet_tabs(spreadsheet_id: str) -> list[dict]:
    """Devuelve las hojas (tabs) de una Google Sheet nativa: [{"title", ...}]."""
    service = _sheets_service()
    try:
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        return [sheet["properties"] for sheet in meta.get("sheets", [])]
    except HttpError as e:
        raise DriveApiError(f"Error leyendo tabs de la Sheet {spreadsheet_id}: {e}", status_code=e.resp.status) from e


def get_sheet_tab_values(spreadsheet_id: str, tab_title: str) -> list[list]:
    """Devuelve las filas crudas (lista de listas) de un tab, sin procesar."""
    service = _sheets_service()
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"'{tab_title}'!A1:ZZ100000")
            .execute()
        )
        return result.get("values", [])
    except HttpError as e:
        raise DriveApiError(
            f"Error leyendo valores del tab '{tab_title}' de {spreadsheet_id}: {e}", status_code=e.resp.status
        ) from e
