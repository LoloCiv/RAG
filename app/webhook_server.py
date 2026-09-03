"""Contrato HTTP para n8n: ingresa mensajes y confirma entregas aprobadas.

El servidor no tiene conectores de correo o WhatsApp: n8n mantiene las
credenciales y ejecuta la entrega solo despues de leer un item aprobado.
"""

import hmac
import sys

import uvicorn
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.config import N8N_WEBHOOK_TOKEN, WORK_ITEMS_DIR, require_webhook_env
from app.operations import work_items


def _require_token(request: Request) -> None:
    expected = f"Bearer {N8N_WEBHOOK_TOKEN or ''}"
    if not N8N_WEBHOOK_TOKEN or not hmac.compare_digest(request.headers.get("authorization", ""), expected):
        raise HTTPException(401, "Token de webhook invalido")


async def inbound(request: Request) -> JSONResponse:
    _require_token(request)
    try:
        record = work_items.ingest_message(await request.json(), WORK_ITEMS_DIR)
    except (ValueError, TypeError) as error:
        raise HTTPException(422, str(error)) from error
    return JSONResponse(record, status_code=201)


async def outbox(request: Request) -> JSONResponse:
    _require_token(request)
    return JSONResponse({"items": work_items.list_delivery_candidates(WORK_ITEMS_DIR)})


async def sent(request: Request) -> JSONResponse:
    _require_token(request)
    try:
        payload = await request.json()
        record = work_items.mark_delivery_sent(request.path_params["work_item_id"], payload["external_message_id"], WORK_ITEMS_DIR)
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(422, str(error)) from error
    return JSONResponse(record)


async def failed(request: Request) -> JSONResponse:
    _require_token(request)
    try:
        payload = await request.json()
        record = work_items.mark_delivery_failed(request.path_params["work_item_id"], payload["error"], WORK_ITEMS_DIR)
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(422, str(error)) from error
    return JSONResponse(record)


app = Starlette(routes=[
    Route("/n8n/inbound", inbound, methods=["POST"]),
    Route("/n8n/outbox", outbox, methods=["GET"]),
    Route("/n8n/outbox/{work_item_id}/sent", sent, methods=["POST"]),
    Route("/n8n/outbox/{work_item_id}/failed", failed, methods=["POST"]),
])


def main() -> None:
    """Arranca separado de Streamlit para que n8n no comparta su ciclo de reruns."""
    missing = require_webhook_env()
    if missing:
        print("Faltan variables de entorno: " + ", ".join(missing), file=sys.stderr)
        raise SystemExit(1)
    uvicorn.run(app, host="127.0.0.1", port=8787)


if __name__ == "__main__":
    main()
