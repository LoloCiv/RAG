"""Autenticacion OAuth 2.0 ("installed app" / Desktop flow) contra Google.

Setup previo (una sola vez, en Google Cloud Console):
  1. Crear un proyecto (o usar uno existente).
  2. Habilitar "Google Drive API" y "Google Sheets API".
  3. Crear credenciales OAuth 2.0 de tipo "Desktop app".
  4. Descargar el JSON y guardarlo como `credentials.json` en la raiz del
     proyecto (events-rag-poc/credentials.json) -- esta gitignored.

La primera vez que corre get_credentials() se abre el navegador para que el
usuario apruebe el acceso de solo lectura a su Drive; el token resultante
queda cacheado en token.json y se refresca solo en corridas posteriores.
"""

import logging

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_SCOPES, GOOGLE_TOKEN_PATH

logger = logging.getLogger(__name__)


class DriveAuthError(RuntimeError):
    """Error claro para problemas de autenticacion (falta credentials.json,
    token invalido/revocado, etc.) en vez de dejar pasar la excepcion cruda
    de la libreria de Google hasta la UI."""


def get_credentials() -> Credentials:
    if not GOOGLE_CREDENTIALS_PATH.exists():
        raise DriveAuthError(
            f"No se encontro {GOOGLE_CREDENTIALS_PATH}. Descargalo desde "
            "Google Cloud Console (credenciales OAuth tipo 'Desktop app') "
            "y guardalo con ese nombre en la raiz del proyecto."
        )

    creds: Credentials | None = None

    if GOOGLE_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), GOOGLE_SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except RefreshError:
            logger.warning("El token de Google vencio y no se pudo refrescar; se vuelve a pedir login.")
            creds = None

    # No hay token valido: correr el flujo interactivo (abre el navegador).
    flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS_PATH), GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    return creds


def _save_token(creds: Credentials) -> None:
    GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Token de Google guardado en %s", GOOGLE_TOKEN_PATH)
