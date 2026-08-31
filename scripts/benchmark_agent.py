"""Arnes de medicion del agente: corre las mismas dos preguntas usadas para
congelar el baseline (ver spec del sub-proyecto 2) y compara tiempo,
round-trips, tool calls y tokens contra ese baseline.

Uso:
    python -m scripts.benchmark_agent                  # las dos preguntas
    python -m scripts.benchmark_agent planificacion     # solo una

Requiere Qdrant, Neo4j (si esta arriba, mejor -- si no, el agente sigue
funcionando solo con busqueda vectorial) y ANTHROPIC_API_KEY/VOYAGE_API_KEY
configurados. Gasta llamadas reales a Claude y Voyage.
"""

import sys
import time

# BASELINE congelado (ver docs/superpowers/specs/2026-08-31-optimizacion-agente-design.md).
# No editar estos numeros salvo que se vuelva a medir el agente SIN ninguna
# palanca aplicada -- son el punto de comparacion de todo este sub-proyecto.
BASELINE: dict[str, dict] = {
    "planificacion": {
        "elapsed_s": 43.3,
        "round_trips": 3,
        "tool_calls": 6,
        "tokens_in": 65499,
        "cache_read": 0,
        "total_in": 65499,
        "cache_creation": 0,
        "tokens_out": 0,  # no se capturaron output tokens al congelar el baseline -- su cambio no es significativo
    },
    "proveedor": {
        "elapsed_s": 87.8,
        "round_trips": 3,
        "tool_calls": 4,
        "tokens_in": 43783,
        "cache_read": 0,
        "total_in": 43783,
        "cache_creation": 0,
        "tokens_out": 0,  # no se capturaron output tokens al congelar el baseline -- su cambio no es significativo
    },
}

QUESTIONS: dict[str, str] = {
    "planificacion": (
        "Estoy planificando un casamiento de 150 invitados con presupuesto "
        "ajustado. Que me sirve de eventos pasados? Que proveedores me "
        "recomendas y cuanto costaron?"
    ),
    "proveedor": (
        "Como viene funcionando el proveedor Catering Buena Mesa? En que "
        "eventos participo y que se dijo de el?"
    ),
}


def format_comparison(label: str, baseline: dict, current: dict) -> str:
    """Compara dos mediciones (mismo shape que BASELINE[...]) y arma un
    reporte legible. Funcion pura: no llama a nada, solo formatea."""

    def pct_change(base: float, cur: float) -> str:
        if base == 0:
            return "n/a"
        change = (cur - base) / base * 100
        sign = "+" if change >= 0 else ""
        return f"{sign}{change:.0f}%"

    lines = [f"=== {label} ===", f"{'metrica':15s} {'baseline':>12s} {'actual':>12s} {'cambio':>8s}"]
    for key, fmt in [
        ("elapsed_s", "{:.1f}s"),
        ("round_trips", "{:d}"),
        ("tool_calls", "{:d}"),
        ("tokens_in", "{:,d}"),
        ("total_in", "{:,d}"),
        ("cache_read", "{:,d}"),
        ("cache_creation", "{:,d}"),
        ("tokens_out", "{:,d}"),
    ]:
        b, c = baseline.get(key, 0), current.get(key, 0)
        lines.append(
            f"{key:15s} {fmt.format(b):>12s} {fmt.format(c):>12s} {pct_change(b, c):>8s}"
        )
    return "\n".join(lines)


def run_question(question: str) -> dict:
    """Corre el agente real contra una pregunta y mide lo mismo que el
    baseline. Depende de servicios vivos -- no se testea con pytest."""
    import anthropic

    from app.agent.claude_agent import SYSTEM_PROMPT, _tool_runner_kwargs
    from app.agent.tools import CODE_EXECUTION_TOOL, _init_tools, get_source_table, search_knowledge_base
    from app.config import EMBED_DIM, QDRANT_COLLECTION, QDRANT_URL
    from app.graph.neo4j_client import Neo4jGraphStore
    from app.rag import vector_db

    store = vector_db.QdrantStorage(url=QDRANT_URL, collection=QDRANT_COLLECTION, dim=EMBED_DIM)

    # El grafo es una mejora, no un requisito: si Neo4j esta caido, el
    # agente sigue funcionando solo con busqueda vectorial (igual que antes
    # de este sub-proyecto).
    try:
        graph_store = Neo4jGraphStore()
    except Exception:  # noqa: BLE001 - el grafo es una mejora, nunca un requisito:
        # cualquier fallo construyendo Neo4jGraphStore() (contenedor caido,
        # ConnectionError, pero tambien fallos mas angostos como permisos o
        # restricciones del server al crear el constraint en _ensure_schema)
        # tiene que degradar a busqueda solo vectorial, no tirar abajo la
        # medicion. Mismo criterio que run_turn() en app/agent/claude_agent.py:
        # este arnes mide ese mismo camino de codigo y tiene que degradar igual.
        graph_store = None
    _init_tools(store, graph_store)

    client = anthropic.Anthropic()
    t0 = time.time()
    runner = client.beta.messages.tool_runner(
        **_tool_runner_kwargs([{"role": "user", "content": question}])
    )

    round_trips = 0
    tool_calls = 0
    tokens_in = 0
    cache_read = 0
    cache_creation = 0
    tokens_out = 0
    try:
        for message in runner:
            round_trips += 1
            usage = getattr(message, "usage", None)
            if usage:
                tokens_in += getattr(usage, "input_tokens", 0) or 0
                cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
                cache_creation += getattr(usage, "cache_creation_input_tokens", 0) or 0
                tokens_out += getattr(usage, "output_tokens", 0) or 0
            for block in message.content:
                if getattr(block, "type", None) in ("tool_use", "server_tool_use"):
                    tool_calls += 1
    finally:
        if graph_store is not None:
            graph_store.close()

    # total_in = tokens_in + cache_read + cache_creation es la unica columna
    # comparable manzana-a-manzana contra el baseline (medido sin cache
    # alguna): tokens_in solo cuenta lo NO cacheado, asi que compararlo solo
    # contra el baseline exagera la mejora. Ojo: total_in es un conteo de
    # tokens, no una cifra de costo -- las escrituras de cache (cache_creation)
    # se facturan a un precio premium sobre el input normal.
    total_in = tokens_in + cache_read + cache_creation

    return {
        "elapsed_s": time.time() - t0,
        "round_trips": round_trips,
        "tool_calls": tool_calls,
        "tokens_in": tokens_in,
        "total_in": total_in,
        "cache_read": cache_read,
        "cache_creation": cache_creation,
        "tokens_out": tokens_out,
    }


def main() -> None:
    labels = sys.argv[1:] or list(QUESTIONS.keys())
    for label in labels:
        if label not in QUESTIONS:
            print(f"Pregunta desconocida: {label} (opciones: {list(QUESTIONS.keys())})")
            continue
        current = run_question(QUESTIONS[label])
        print(format_comparison(label, BASELINE[label], current))
        print()


if __name__ == "__main__":
    main()
