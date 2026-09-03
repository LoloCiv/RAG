"""Configuracion de logging para todo el proyecto.

Nivel POC: un solo logger por modulo (logging.getLogger(__name__)), todo a
stderr. Esto preserva stdout para el protocolo JSON-RPC del servidor MCP.
INFO para progreso normal (ingesta, tool calls), WARNING para
archivos salteados/no soportados, ERROR para fallos que abortaron algo.
No hace falta logging estructurado/JSON a esta escala (un solo proceso
local).
"""

import logging


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Las librerias de Google suelen ser muy verbosas en DEBUG/INFO; las bajamos.
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)
