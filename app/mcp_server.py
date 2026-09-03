"""Servidor MCP stdio que expone una unica consulta stateless."""

import base64
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from app.agent import inbox
from app.config import require_query_env
from app.logging_conf import setup_logging

logger = logging.getLogger(__name__)
mcp = FastMCP("events-rag")


def _to_mcp_content(record: dict) -> list:
    """Embebe charts porque un path local no sirve al cliente MCP remoto."""
    text = record.get("answer_text", "")
    sources = record.get("sources", [])
    if sources:
        lines = ["", "Fuentes:"]
        for source in sources:
            line = f"- {source['file_name']}"
            if source.get("drive_url"):
                line += f" ({source['drive_url']})"
            lines.append(line)
        text += "\n".join(lines)
    content = [TextContent(type="text", text=text)]
    for chart_path in record.get("chart_paths", []):
        path = Path(chart_path)
        if not path.exists():
            logger.warning("Chart ya no esta en disco, se saltea: %s", chart_path)
            continue
        content.append(ImageContent(type="image", data=base64.b64encode(path.read_bytes()).decode("ascii"), mimeType="image/png"))
    return content


def query_events_kb(question: str) -> list:
    """Responde preguntas sobre eventos, presupuestos y proveedores de la empresa."""
    return _to_mcp_content(inbox.ask(question))


mcp.tool()(query_events_kb)


def main() -> None:
    """Protege stdout porque en stdio es el canal JSON-RPC del protocolo."""
    missing = require_query_env()
    if missing:
        print("Faltan variables de entorno: " + ", ".join(missing), file=sys.stderr)
        raise SystemExit(1)
    setup_logging()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
