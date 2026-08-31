"""TODO (vos): las tools que le damos a Claude.

Dos tools custom (decoradas con @beta_tool, que genera el JSON schema solo a
partir de los type hints + docstring) mas la tool server-side de ejecucion
de codigo de Anthropic (esta ultima no se implementa, se declara nomas).

--------------------------------------------------------------------------
1) search_knowledge_base(query, top_k) -> dict
--------------------------------------------------------------------------
Busqueda semantica sobre la base de conocimiento (chunks de texto de PDFs/
Docs/resumenes de filas de sheets). Pasos:
  1. embeddings.embed_texts([query])[0] para embeber la pregunta
  2. store.search(query_vec, top_k, kind_filter="text_chunk") -- IMPORTANTE
     el filtro "text_chunk": no queremos que aparezcan blobs de tabla (JSON
     crudo) mezclados en resultados de busqueda semantica
  3. devolver {"contexts": [...], "sources": [...]} -- ese es el contrato
     JSON que ve Claude, sin cambios en la Fase 2. Lo que cambio (reranking,
     Fase 2) es el shape INTERNO de QdrantStorage.search(): ahora devuelve
     una lista correlacionada por chunk ([{"text","source_id","file_name",
     "score"}, ...], sin dedupear), y esta funcion arma contexts/sources a
     partir de ahi con QdrantStorage.dedup_source_ids().

--------------------------------------------------------------------------
2) get_source_table(source_id) -> dict
--------------------------------------------------------------------------
Trae la tabla EXACTA (no aproximada) de una planilla ya ingerida, dado un
source_id (los que devuelve "sources" de search_knowledge_base). El agente
la deberia usar SIEMPRE antes de calcular numeros exactos o armar un
grafico -- los chunks de texto de search_knowledge_base son una
aproximacion difusa pensada para busqueda, no para aritmetica.
  1. store.get_by_source_id(source_id)
  2. si no existe, devolver {"error": f"No hay tabla para source_id={source_id}"}
     (asi el agente puede reaccionar en vez de fallar la tool)
  3. si existe, devolver columns / row_count / table_json / truncated del
     payload

--------------------------------------------------------------------------
3) La tool de ejecucion de codigo (server-side, no se implementa)
--------------------------------------------------------------------------
No es una funcion Python: es un dict que se declara en la lista de tools
del tool_runner tal cual, Anthropic la corre en su propia infraestructura
(ya tiene pandas/matplotlib instalados). Se usa asi, en claude_agent.py:

    CODE_EXECUTION_TOOL = {"type": "code_execution_20260120", "name": "code_execution"}

get_source_table esta decorada con @beta_tool(allowed_callers=["code_execution_20260120"])
(palanca 2: programmatic tool calling) -- asi Claude puede invocarla desde
el codigo que corre dentro de code_execution en vez de como tool_use
directo, y la tabla completa nunca entra al contexto de la conversacion.

--------------------------------------------------------------------------
Como se conectan search_knowledge_base -> get_source_table -> code_execution
--------------------------------------------------------------------------
NO estan enganchadas entre si en el codigo -- es Claude el que decide llamar
una despues de la otra dentro del mismo turno, guiado por el system prompt
(ver claude_agent.py): busca texto, si necesita numeros exactos pide la
tabla, y si le pidieron un grafico escribe el codigo de matplotlib usando
esos datos (embebidos como literal en el script que genera, no hay
attachment/upload de por medio para este POC).

Pistas:
- El decorador es `from anthropic import beta_tool` (import exacto, no
  inventar otro path).
- Los type hints y el docstring de cada funcion SON el schema que ve
  Claude -- si el docstring es vago, Claude va a llamar mal la tool.
"""

import json
import logging

from anthropic import beta_tool  # noqa: F401 -- lo vas a necesitar para decorar

from app.rag import embeddings, vector_db  # noqa: F401
from app.config import EMBED_DIM, GRAPH_MAX_ANCHORS, GRAPH_MAX_EDGES, QDRANT_COLLECTION, QDRANT_URL  # noqa: F401
from app.graph import retrieval

logger = logging.getLogger(__name__)

# Se usa code_execution_20260120 por decision de diseno explicita del
# sub-proyecto 2 (ver spec), no porque 20260521 carezca de soporte para
# allowed_callers -- el SDK instalado (anthropic 1.2.0) acepta
# allowed_callers en ambas variantes.
CODE_EXECUTION_TOOL = {"type": "code_execution_20260120", "name": "code_execution"}

# Estado global para pasar las stores y acumular sources entre tool calls
_store: vector_db.QdrantStorage | None = None
_graph_store = None  # Neo4jGraphStore | None -- import perezoso, ver search_knowledge_base
_accumulated_sources: list[str] = []
# norm_names de las entidades ancla ya mostradas en el mapa DURANTE ESTE
# TURNO. Cuando el mismo turno dispara 2+ search_knowledge_base en paralelo
# sobre entidades solapadas (el SDK ya paraleliza esto), cada llamada
# arrastraba su propia copia casi identica del mapa -- puro gasto de
# tokens, sin informacion nueva. Se resetea en cada _init_tools (turno
# nuevo, mapa desde cero), igual que _accumulated_sources.
_mapa_anchors_shown: set[str] = set()


def _init_tools(store: vector_db.QdrantStorage, graph_store=None) -> None:
    """Inicializar los tools con las stores y resetear el estado."""
    global _store, _graph_store, _accumulated_sources, _mapa_anchors_shown
    _store = store
    _graph_store = graph_store
    _accumulated_sources = []
    _mapa_anchors_shown = set()


def _get_store() -> vector_db.QdrantStorage:
    """Obtener la instancia de store (debe estar inicializada con _init_tools)."""
    if _store is None:
        raise RuntimeError(
            "Tools no inicializados. Llamar _init_tools(store) desde run_turn() "
            "al inicio de cada turno."
        )
    return _store


def _graph_context_for(graph_store, source_ids: list[str]) -> str:
    """Arma el mapa de grafo para una busqueda, a partir de los source_ids
    que ya devolvio Qdrant. Aislada de search_knowledge_base para poder
    testearla con un graph_store falso.

    Dedupe entre llamadas del mismo turno: si una ancla ya se mostro en una
    busqueda anterior de este turno (_mapa_anchors_shown), no se repite --
    si no queda ninguna ancla nueva que aportar, devuelve "" (mismo
    significado que "sin contexto de grafo" que ya maneja el system
    prompt). Ojo: format_graph_context puede a su vez cortar alguna de
    estas anclas por presupuesto de caracteres (GRAPH_MAX_CHARS) -- una
    ancla que se pidio pero no llego a aparecer en el texto final NO debe
    marcarse como mostrada, para que una llamada posterior con menos
    competencia por espacio todavia pueda mostrarla. Por eso se marca
    comparando contra el texto devuelto (via retrieval.anchor_header), no
    contra la lista de anclas que se le paso a format_graph_context.

    Nunca propaga una excepcion: un fallo de Neo4j aca degrada a "sin mapa",
    no rompe la busqueda semantica -- mismo criterio que _sync_graph_safe
    en app/ingestion/pipeline.py.
    """
    global _mapa_anchors_shown
    if graph_store is None or not source_ids:
        return ""
    try:
        anchors = graph_store.anchors_by_source_ids(source_ids, limit=GRAPH_MAX_ANCHORS)
        anchors = [a for a in anchors if a["norm_name"] not in _mapa_anchors_shown]
        if not anchors:
            return ""
        norm_names = [a["norm_name"] for a in anchors]
        edges = graph_store.neighborhood(norm_names, limit=GRAPH_MAX_EDGES)
        text = retrieval.format_graph_context(anchors, edges)
        shown_now = {a["norm_name"] for a in anchors if retrieval.anchor_header(a) in text}
        _mapa_anchors_shown.update(shown_now)
        return text
    except Exception:
        logger.exception("No se pudo enriquecer con el grafo, sigo solo con busqueda vectorial")
        return ""


# OJO: @beta_tool exige que la funcion devuelva str (o una lista de content
# blocks) -- BetaFunctionToolResultType = Union[str, Iterable[BetaContent]]
# en el SDK (anthropic/lib/tools/_beta_functions.py). El tool_runner mete el
# valor de retorno TAL CUAL en el campo "content" del tool_result, sin
# serializar nada -- devolver un dict Python ahi rompe la request con un
# 400 ("tool_result content must either be a string or a list of content
# blocks"). Por eso ambas tools devuelven json.dumps(...) del resultado, no
# el dict directo.


@beta_tool
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """Buscar información relevante en la base de conocimiento.

    Realiza una búsqueda semántica sobre PDFs, Google Docs y planillas
    ingestionados. Devuelve los fragmentos de texto más relevantes, sus
    fuentes, y un mapa del grafo de conocimiento con las entidades y
    relaciones que conectan esos documentos (campo "mapa" -- vacío si no
    hay contexto de grafo disponible).

    Args:
        query: La pregunta o término de búsqueda
        top_k: Cantidad máxima de resultados a devolver (default 5)

    Returns:
        JSON con "contexts" (fragmentos de texto), "sources" (source_ids) y
        "mapa" (texto con entidades y relaciones del grafo relacionadas a
        esos documentos -- usalo para saber que otros eventos/proveedores
        estan conectados sin tener que buscarlos por separado)
    """
    store = _get_store()

    # input_type="query": los embeddings de Voyage son asimetricos
    # (document vs query se entrenaron con prompts internos distintos), asi
    # que hay que decirle cual es cual para que el retrieval funcione bien.
    query_vector = embeddings.embed_texts([query], input_type="query")[0]

    # Buscar solo chunks de texto, no blobs de tabla. Lista correlacionada
    # por chunk (text/source_id/file_name/score, sin dedupear) desde la
    # Fase 2 -- dedup_source_ids arma "sources" a nivel documento a partir
    # de ahi, igual que antes hacia QdrantStorage.search() internamente.
    chunks = store.search(query_vector, top_k=top_k, kind_filter="text_chunk")
    sources = vector_db.QdrantStorage.dedup_source_ids(chunks)

    # Acumular sources para el contexto final del turno
    global _accumulated_sources
    _accumulated_sources.extend([s for s in sources if s not in _accumulated_sources])

    result = {
        "contexts": [c["text"] for c in chunks],
        "sources": sources,
        "mapa": _graph_context_for(_graph_store, sources),
    }

    return json.dumps(result, ensure_ascii=False)


@beta_tool(allowed_callers=["code_execution_20260120"])
def get_source_table(source_id: str) -> str:
    """Obtener la tabla exacta de una planilla ingerida.

    Se usa SIEMPRE antes de hacer cálculos numericos, promedios, gráficos o
    comparaciones exactas -- los fragmentos de search_knowledge_base son una
    aproximación difusa, no datos exactos. Se llama desde el codigo que
    escribis en code_execution (no directo): asi la tabla completa nunca
    entra al contexto de la conversacion, solo el resultado que tu codigo
    calcule.

    Args:
        source_id: El identificador del tab de planilla (devuelto por search_knowledge_base)

    Returns:
        JSON con "columns", "row_count", "table_json" (JSON string de las filas) y
        "truncated" (bool indicando si la tabla fue recortada por tamaño)
        Si el source_id no existe, devuelve JSON con "error".
    """
    store = _get_store()

    payload = store.get_by_source_id(source_id)
    if payload is None:
        return json.dumps({"error": f"No hay tabla para source_id={source_id}"})

    return json.dumps(
        {
            "columns": payload.get("columns"),
            "row_count": payload.get("row_count"),
            "table_json": payload.get("table_json"),
            "truncated": payload.get("truncated"),
        },
        ensure_ascii=False,
    )

