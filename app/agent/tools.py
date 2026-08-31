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
  3. devolver {"contexts": [...], "sources": [...]} (mismo shape que ya
     devuelve QdrantStorage.search())

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

    CODE_EXECUTION_TOOL = {"type": "code_execution_20260521", "name": "code_execution"}

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

from anthropic import beta_tool  # noqa: F401 -- lo vas a necesitar para decorar

from app.rag import embeddings, vector_db  # noqa: F401
from app.config import EMBED_DIM, QDRANT_COLLECTION, QDRANT_URL  # noqa: F401

CODE_EXECUTION_TOOL = {"type": "code_execution_20260521", "name": "code_execution"}

# Estado global para pasar la store y acumular sources entre tool calls
_store: vector_db.QdrantStorage | None = None
_accumulated_sources: list[str] = []


def _init_tools(store: vector_db.QdrantStorage) -> None:
    """Inicializar los tools con una instancia de store y resetear el estado."""
    global _store, _accumulated_sources
    _store = store
    _accumulated_sources = []


def _get_store() -> vector_db.QdrantStorage:
    """Obtener la instancia de store (debe estar inicializada con _init_tools)."""
    if _store is None:
        raise RuntimeError(
            "Tools no inicializados. Llamar _init_tools(store) desde run_turn() "
            "al inicio de cada turno."
        )
    return _store


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
    ingestionados. Devuelve los fragmentos de texto más relevantes y sus
    fuentes.

    Args:
        query: La pregunta o término de búsqueda
        top_k: Cantidad máxima de resultados a devolver (default 5)

    Returns:
        JSON con "contexts" (lista de fragmentos de texto relevantes) y
        "sources" (lista de source_ids con los documentos/planillas encontrados)
    """
    store = _get_store()

    # input_type="query": los embeddings de Voyage son asimetricos
    # (document vs query se entrenaron con prompts internos distintos), asi
    # que hay que decirle cual es cual para que el retrieval funcione bien.
    query_vector = embeddings.embed_texts([query], input_type="query")[0]

    # Buscar solo chunks de texto, no blobs de tabla
    result = store.search(query_vector, top_k=top_k, kind_filter="text_chunk")

    # Acumular sources para el contexto final del turno
    global _accumulated_sources
    _accumulated_sources.extend([s for s in result["sources"] if s not in _accumulated_sources])

    return json.dumps(result, ensure_ascii=False)


@beta_tool
def get_source_table(source_id: str) -> str:
    """Obtener la tabla exacta de una planilla ingerida.

    Se usa SIEMPRE antes de hacer cálculos numericos, promedios, gráficos o
    comparaciones exactas -- los fragmentos de search_knowledge_base son una
    aproximación difusa, no datos exactos.

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

