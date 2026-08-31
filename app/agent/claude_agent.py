"""TODO (vos): el loop del agente -- ata tools.py a Claude via tool_runner.

--------------------------------------------------------------------------
Patron base (SDK oficial de Anthropic, Python):
--------------------------------------------------------------------------
    import anthropic
    client = anthropic.Anthropic()  # toma ANTHROPIC_API_KEY del entorno solo

    runner = client.beta.messages.tool_runner(
        model=CLAUDE_MODEL,               # app/config.py, default "claude-sonnet-5"
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        tools=[search_knowledge_base, get_source_table, CODE_EXECUTION_TOOL],
        messages=message_history,          # lista de dicts formato Anthropic
    )

    last = None
    for message in runner:                 # el runner ejecuta las tools solo
        last = message                      # y hace el loop hasta que Claude termina
    return last

--------------------------------------------------------------------------
Que tiene que hacer run_turn(message_history: list[dict]) -> dict
--------------------------------------------------------------------------
Recibe el historial de mensajes (formato Anthropic: [{"role": "user"/
"assistant", "content": ...}, ...], tal cual lo va armando streamlit_app.py)
y devuelve algo que la UI pueda renderizar, por ejemplo:

    {
        "response_content": ...,   # message.content del ULTIMO mensaje del
                                    # runner -- streamlit_app.py necesita
                                    # esto tal cual (no solo el texto) para
                                    # agregarlo al historial y no perder el
                                    # estado de los tool calls entre turnos
        "answer_text": "...",      # los bloques de texto concatenados, para
                                    # mostrar directo
        "sources": [...],          # ver mas abajo
        "chart_paths": [...],      # ver app/agent/files.py
    }

Cosas a resolver (quedan a tu criterio, son decisiones de diseno reales, no
detalles menores):

1. **Acumular "sources"**: el tool_runner no expone directamente los
   tool_result de cada llamada a search_knowledge_base a medida que itera.
   La forma mas simple es que la propia funcion search_knowledge_base (en
   tools.py) vaya guardando los sources que devuelve en algun lado que
   run_turn pueda leer despues (ej. una lista que le pasas por closure/
   parametro extra, o un atributo de modulo que reseteas al arrancar cada
   run_turn). Elegi el mecanismo que te resulte mas prolijo.

2. **pause_turn**: turnos largos de la tool server-side de codigo pueden
   cortar con stop_reason="pause_turn" -- el tool_runner de Python NO lo
   retoma solo (a diferencia del runner de TypeScript). Si te pasa en la
   practica durante el POC, hay que reiniciar el runner agregando el turno
   pausado al historial (patron documentado en la guia de tool use de
   Anthropic). Para el POC podes arrancar sin manejarlo y agregarlo si
   efectivamente lo ves aparecer con datos reales.

3. **Extraer texto final**: iterar el .content del ultimo message por
   bloques type == "text" y concatenar.

--------------------------------------------------------------------------
Punto de partida sugerido para SYSTEM_PROMPT (iteralo, es tuyo):
--------------------------------------------------------------------------
Sos un asistente de investigacion interno para una empresa de eventos.
Respondes preguntas usando el historial propio de eventos, presupuestos y
proveedores de la empresa.

- Usa search_knowledge_base para encontrar texto relevante (resumenes de
  eventos, clausulas de contratos, notas de proveedores) en PDFs, Google
  Docs y planillas.
- Si te piden un grafico, un total, un promedio o cualquier comparacion
  numerica exacta: NO la calcules a partir del texto de
  search_knowledge_base solo -- llama primero a get_source_table con el
  source_id correspondiente para tener las filas exactas, y despues usa la
  tool de ejecucion de codigo (pandas/matplotlib disponibles) para calcular
  y, si pidieron un grafico, graficarlo.
- Siempre cita el/los archivo(s) fuente que usaste.
- Si no encontras nada relevante, decilo claramente en vez de inventar.
"""

import anthropic
import logging

from app.agent.tools import search_knowledge_base, get_source_table, CODE_EXECUTION_TOOL, _init_tools
from app.agent import files
from app.config import CLAUDE_MODEL, QDRANT_URL, QDRANT_COLLECTION, EMBED_DIM
from app.graph.neo4j_client import Neo4jGraphStore
from app.rag import vector_db

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sos un asistente de investigacion interno para una empresa de eventos.
Respondes preguntas usando el historial propio de eventos, presupuestos y proveedores de la empresa.

- Usa search_knowledge_base para encontrar texto relevante (resumenes de eventos, clausulas de contratos, notas de proveedores) en PDFs, Google Docs y planillas.
- Si te piden un grafico, un total, un promedio o cualquier comparacion numerica exacta: NO la calcules a partir del texto de search_knowledge_base solo -- llama primero a get_source_table con el source_id correspondiente para tener las filas exactas, y despues usa la tool de ejecucion de codigo (pandas/matplotlib disponibles) para calcular y, si pidieron un grafico, graficarlo.
- Siempre cita el/los archivo(s) fuente que usaste.
- Si no encontras nada relevante, decilo claramente en vez de inventar."""


def run_turn(message_history: list[dict]) -> dict:
    """Ejecutar un turno del agente con Claude.
    
    Args:
        message_history: Historial de mensajes en formato Anthropic
        
    Returns:
        dict con:
            - response_content: Los bloques de contenido del último mensaje (para el historial)
            - answer_text: Texto concatenado de la respuesta (para mostrar)
            - sources: Lista de source_ids usados en búsquedas
            - chart_paths: Paths locales de gráficos generados
    """
    store = vector_db.QdrantStorage(url=QDRANT_URL, collection=QDRANT_COLLECTION, dim=EMBED_DIM)

    # El grafo es una mejora, no un requisito: si Neo4j esta caido, el
    # agente sigue funcionando solo con busqueda vectorial (igual que antes
    # de este sub-proyecto). Mismo criterio que el sidebar de Streamlit.
    try:
        graph_store = Neo4jGraphStore()
    except Exception:  # noqa: BLE001 - el grafo es una mejora, nunca un requisito:
        # cualquier fallo construyendo Neo4jGraphStore() (contenedor caido,
        # ConnectionError, pero tambien fallos mas angostos como permisos o
        # restricciones del server al crear el constraint en _ensure_schema)
        # tiene que degradar a busqueda solo vectorial, no tirar abajo el turno.
        # Mismo criterio que el sidebar de Streamlit (streamlit_app.py).
        logger.exception("Grafo no disponible, el agente sigue solo con busqueda vectorial")
        graph_store = None

    _init_tools(store, graph_store)

    client = anthropic.Anthropic()

    try:
        # cache_control: el contenido de tool results se reenvia completo en
        # cada round-trip (la API es stateless). Medido en el baseline: el
        # 79% de los tokens facturados en una pregunta compleja eran
        # contenido repetido de vueltas anteriores. Este parametro activa
        # caching automatico, que coloca el breakpoint en el ultimo bloque
        # cacheable y lo va corriendo a medida que crece la conversacion.
        runner = client.beta.messages.tool_runner(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            cache_control={"type": "ephemeral"},
            system=SYSTEM_PROMPT,
            tools=[search_knowledge_base, get_source_table, CODE_EXECUTION_TOOL],
            messages=message_history,
        )

        last_message = None
        for message in runner:
            last_message = message

        if last_message is None:
            return {
                "response_content": [],
                "answer_text": "",
                "sources": [],
                "chart_paths": [],
            }

        answer_text = _extract_text_from_content(last_message.content)
        chart_paths = files.save_generated_files(client, last_message.content)

        from app.agent import tools
        accumulated_sources = list(set(tools._accumulated_sources))

        return {
            "response_content": last_message.content,
            "answer_text": answer_text,
            "sources": accumulated_sources,
            "chart_paths": chart_paths,
        }
    finally:
        if graph_store is not None:
            graph_store.close()


def _extract_text_from_content(content_blocks: list) -> str:
    """Extraer y concatenar todos los bloques de texto de una respuesta."""
    texts = []
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            texts.append(block.text)
    return "\n".join(texts)

