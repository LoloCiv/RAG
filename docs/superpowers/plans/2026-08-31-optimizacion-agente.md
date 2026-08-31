# Optimización del agente (sub-proyecto 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reducir tokens de entrada y latencia del agente de chat sin perder
calidad de respuesta, mediante tres palancas medibles: prompt caching,
programmatic tool calling, y enriquecimiento de `search_knowledge_base` con
el grafo de conocimiento del sub-proyecto 1.

**Architecture:** Tres cambios aditivos e independientes sobre
`app/agent/claude_agent.py` y `app/agent/tools.py`, más dos métodos de
lectura nuevos en `app/graph/neo4j_client.py` y un módulo nuevo
`app/graph/retrieval.py` de funciones puras. Un arnés de benchmark
(`scripts/benchmark_agent.py`) mide cada palanca contra un baseline
congelado, corrido tras cada una.

**Tech Stack:** Python 3.12, SDK `anthropic` 1.2.0 (`tool_runner`,
`@beta_tool`), Neo4j 5 (driver `neo4j` 6.x), Qdrant, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-optimizacion-agente-design.md`

## Global Constraints

- No se toca la ingesta ni `app/ingestion/pipeline.py` (sub-proyecto 1
  queda intacto).
- No se introduce ningún modelo local ni se cambia `CLAUDE_MODEL`
  (`claude-sonnet-5`, en `app/config.py`).
- No se agrega ninguna tool nueva al agente (`explore_entity` queda fuera de
  alcance, ver spec).
- Todas las funciones de `app/graph/retrieval.py` son puras: sin I/O, sin
  importar `neo4j` ni `anthropic`.
- Todo lo que hable con Neo4j o Qdrant debe fallar con gracia: si el grafo
  no está disponible, el agente sigue funcionando solo con búsqueda
  vectorial (igual que hoy).
- Baseline congelado a batir (agente actual, sin ninguna palanca):

  | Pregunta | Tiempo | Round-trips | Tool calls | Tokens in |
  |---|---|---|---|---|
  | Planificación | 43,3 s | 3 | 6 | 65.499 |
  | Proveedor | 87,8 s | 3 | 4 | 43.783 |

---

## File Structure

```
app/
  agent/
    claude_agent.py     # MODIFICAR: cache_control, Neo4jGraphStore lifecycle, system prompt
    tools.py             # MODIFICAR: _init_tools, CODE_EXECUTION_TOOL, get_source_table,
                          #            _graph_context_for, search_knowledge_base
  graph/
    neo4j_client.py      # MODIFICAR: sumar anchors_by_source_ids, neighborhood
    retrieval.py         # NUEVO: format_graph_context (funcion pura)
  config.py               # MODIFICAR: GRAPH_MAX_ANCHORS, GRAPH_MAX_EDGES
scripts/
  benchmark_agent.py    # NUEVO: arnes de medicion, corre las 2 preguntas del baseline
tests/
  test_benchmark_format.py       # NUEVO
  test_claude_agent_caching.py   # NUEVO
  test_tools_ptc.py              # NUEVO
  test_graph_retrieval.py        # NUEVO
  test_tools_graph_context.py    # NUEVO
```

---

### Task 1: Arnés de medición (`scripts/benchmark_agent.py`)

Sin esto no se puede atribuir mejora a ninguna palanca. Va primero.

**Files:**
- Create: `scripts/benchmark_agent.py`
- Test: `tests/test_benchmark_format.py`

**Interfaces:**
- Produces: `format_comparison(label: str, baseline: dict, current: dict) -> str`
  — función pura, usada también por tareas futuras si hiciera falta
  formatear resultados. `baseline`/`current` son dicts con claves
  `elapsed_s: float`, `round_trips: int`, `tool_calls: int`,
  `tokens_in: int`, `cache_read: int` (0 si no aplica).
- Produces: `run_question(question: str) -> dict` — ejecuta el agente real
  (`app.agent.claude_agent.run_turn`) y devuelve el mismo shape de arriba.
  Depende de Qdrant/Neo4j/Claude vivos; no se testea automáticamente.
- Produces: `BASELINE: dict[str, dict]` — el baseline congelado de la tabla
  de arriba, indexado por label (`"planificacion"`, `"proveedor"`).
- Produces: `QUESTIONS: dict[str, str]` — las dos preguntas del baseline,
  mismo texto exacto usado para medirlo.

- [ ] **Step 1: Escribir el test de `format_comparison` (falla)**

Crear `tests/test_benchmark_format.py`:

```python
"""format_comparison es pura: se testea con dicts armados a mano, sin
Qdrant/Neo4j/Claude vivos. run_question() en cambio SI llama al agente real
-- no se testea automaticamente, se corre a mano entre cada palanca (ver
plan de implementacion, Task 1 en adelante)."""

from scripts.benchmark_agent import format_comparison


def test_muestra_mejora_como_porcentaje_negativo():
    baseline = {"elapsed_s": 43.3, "round_trips": 3, "tool_calls": 6, "tokens_in": 65499, "cache_read": 0}
    current = {"elapsed_s": 20.0, "round_trips": 3, "tool_calls": 6, "tokens_in": 20000, "cache_read": 40000}

    texto = format_comparison("planificacion", baseline, current)

    assert "planificacion" in texto
    assert "65,499" in texto or "65499" in texto
    assert "20,000" in texto or "20000" in texto
    # tokens_in bajo un 69%: tiene que quedar visible como mejora
    assert "-69" in texto or "-70" in texto or "69%" in texto or "70%" in texto


def test_cache_read_en_cero_no_rompe_el_formato():
    baseline = {"elapsed_s": 1.0, "round_trips": 1, "tool_calls": 0, "tokens_in": 100, "cache_read": 0}
    current = {"elapsed_s": 1.0, "round_trips": 1, "tool_calls": 0, "tokens_in": 100, "cache_read": 0}

    texto = format_comparison("sin cambios", baseline, current)

    assert "sin cambios" in texto


def test_empeora_se_marca_como_positivo_no_como_mejora():
    baseline = {"elapsed_s": 10.0, "round_trips": 1, "tool_calls": 1, "tokens_in": 1000, "cache_read": 0}
    current = {"elapsed_s": 15.0, "round_trips": 1, "tool_calls": 1, "tokens_in": 1500, "cache_read": 0}

    texto = format_comparison("peor", baseline, current)

    assert "+50%" in texto or "+50.0%" in texto
```

- [ ] **Step 2: Correr el test, confirmar que falla**

Run: `pytest tests/test_benchmark_format.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'scripts'` o
`ImportError: cannot import name 'format_comparison'`.

- [ ] **Step 3: Crear `scripts/__init__.py` vacío**

```python
```

(Archivo vacío: convierte `scripts/` en paquete importable para que
`from scripts.benchmark_agent import ...` funcione tanto en el test como
al correr `python -m scripts.benchmark_agent`.)

- [ ] **Step 4: Implementar `scripts/benchmark_agent.py`**

```python
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
    },
    "proveedor": {
        "elapsed_s": 87.8,
        "round_trips": 3,
        "tool_calls": 4,
        "tokens_in": 43783,
        "cache_read": 0,
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
        ("cache_read", "{:,d}"),
    ]:
        b, c = baseline[key], current[key]
        lines.append(
            f"{key:15s} {fmt.format(b):>12s} {fmt.format(c):>12s} {pct_change(b, c):>8s}"
        )
    return "\n".join(lines)


def run_question(question: str) -> dict:
    """Corre el agente real contra una pregunta y mide lo mismo que el
    baseline. Depende de servicios vivos -- no se testea con pytest."""
    import anthropic

    from app.agent.claude_agent import SYSTEM_PROMPT
    from app.agent.tools import CODE_EXECUTION_TOOL, _init_tools, get_source_table, search_knowledge_base
    from app.config import CLAUDE_MODEL, EMBED_DIM, QDRANT_COLLECTION, QDRANT_URL
    from app.graph.neo4j_client import Neo4jGraphStore
    from app.rag import vector_db

    store = vector_db.QdrantStorage(url=QDRANT_URL, collection=QDRANT_COLLECTION, dim=EMBED_DIM)
    try:
        graph_store = Neo4jGraphStore()
    except ConnectionError:
        graph_store = None
    _init_tools(store, graph_store)

    client = anthropic.Anthropic()
    t0 = time.time()
    runner = client.beta.messages.tool_runner(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        cache_control={"type": "ephemeral"},
        system=SYSTEM_PROMPT,
        tools=[search_knowledge_base, get_source_table, CODE_EXECUTION_TOOL],
        messages=[{"role": "user", "content": question}],
    )

    round_trips = 0
    tool_calls = 0
    tokens_in = 0
    cache_read = 0
    for message in runner:
        round_trips += 1
        usage = getattr(message, "usage", None)
        if usage:
            tokens_in += getattr(usage, "input_tokens", 0) or 0
            cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        for block in message.content:
            if getattr(block, "type", None) in ("tool_use", "server_tool_use"):
                tool_calls += 1

    if graph_store is not None:
        graph_store.close()

    return {
        "elapsed_s": time.time() - t0,
        "round_trips": round_trips,
        "tool_calls": tool_calls,
        "tokens_in": tokens_in,
        "cache_read": cache_read,
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
```

- [ ] **Step 5: Correr el test, confirmar que pasa**

Run: `pytest tests/test_benchmark_format.py -v`
Expected: 3 passed.

- [ ] **Step 6: Reproducir el baseline (verificación manual, gasta API real)**

Con Qdrant y Neo4j corriendo (`docker ps` debe mostrarlos):

```bash
python -m scripts.benchmark_agent
```

Confirmar que la columna "actual" da valores parecidos a los de "baseline"
(no van a ser idénticos, la API no es determinística, pero el orden de
magnitud de tokens y round-trips tiene que coincidir). Si algo se disparó
100x, hay un bug en el arnés, no en el agente — revisar antes de seguir.

- [ ] **Step 7: Commit**

```bash
git add scripts/ tests/test_benchmark_format.py
git commit -m "feat: arnes de medicion del agente (benchmark_agent.py)"
```

---

### Task 2: Palanca 1 — prompt caching

**Files:**
- Modify: `app/agent/claude_agent.py`
- Test: `tests/test_claude_agent_caching.py`

**Interfaces:**
- Consumes: nada nuevo de otras tasks.
- Produces: ningún símbolo nuevo — `run_turn` mantiene su firma
  `run_turn(message_history: list[dict]) -> dict`.

- [ ] **Step 1: Escribir el test (falla)**

Crear `tests/test_claude_agent_caching.py`:

```python
"""run_turn() en produccion habla con Qdrant/Neo4j/Claude reales -- este
test reemplaza los tres con fakes para verificar UNA cosa puntual: que el
tool_runner se llama con cache_control (la palanca 1 del sub-proyecto 2),
sin gastar ninguna llamada real."""

from app.agent import claude_agent


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5
    cache_read_input_tokens = 0


class _FakeMessage:
    def __init__(self):
        self.content = []
        self.usage = _FakeUsage()


class _FakeToolRunner:
    def __init__(self, captured_kwargs: dict, **kwargs):
        captured_kwargs.update(kwargs)

    def __iter__(self):
        return iter([_FakeMessage()])


class _FakeBetaMessages:
    def __init__(self, captured_kwargs: dict):
        self._captured = captured_kwargs

    def tool_runner(self, **kwargs):
        return _FakeToolRunner(self._captured, **kwargs)


class _FakeBeta:
    def __init__(self, captured_kwargs: dict):
        self.messages = _FakeBetaMessages(captured_kwargs)


class _FakeAnthropicClient:
    last_captured_kwargs: dict = {}

    def __init__(self, *args, **kwargs):
        _FakeAnthropicClient.last_captured_kwargs = {}
        self.beta = _FakeBeta(_FakeAnthropicClient.last_captured_kwargs)


class _FakeQdrantStorage:
    def __init__(self, *args, **kwargs):
        pass


class _FakeGraphStore:
    def __init__(self, *args, **kwargs):
        pass

    def close(self) -> None:
        pass


def test_run_turn_pasa_cache_control_al_tool_runner(monkeypatch):
    monkeypatch.setattr(claude_agent.anthropic, "Anthropic", _FakeAnthropicClient)
    monkeypatch.setattr(claude_agent.vector_db, "QdrantStorage", _FakeQdrantStorage)
    monkeypatch.setattr(claude_agent, "Neo4jGraphStore", _FakeGraphStore)

    claude_agent.run_turn([{"role": "user", "content": "hola"}])

    assert _FakeAnthropicClient.last_captured_kwargs.get("cache_control") == {"type": "ephemeral"}
```

- [ ] **Step 2: Correr el test, confirmar que falla**

Run: `pytest tests/test_claude_agent_caching.py -v`
Expected: FAIL. En este punto del proyecto, `claude_agent.py` todavía no
importa `Neo4jGraphStore` ni pasa `cache_control` — puede fallar con
`AttributeError: module 'app.agent.claude_agent' has no attribute
'Neo4jGraphStore'` (el monkeypatch del Step 1 falla porque el símbolo no
existe todavía) o, si se comenta esa línea, con
`assert None == {'type': 'ephemeral'}`. Cualquiera de los dos es el fallo
correcto: confirma que ninguna de las dos cosas está implementada.

- [ ] **Step 3: Implementar `cache_control` y el ciclo de vida del grafo en `claude_agent.py`**

Reemplazar el bloque de imports y `run_turn` en
`app/agent/claude_agent.py`:

```python
import anthropic
import logging

from app.agent.tools import search_knowledge_base, get_source_table, CODE_EXECUTION_TOOL, _init_tools
from app.agent import files
from app.config import CLAUDE_MODEL, QDRANT_URL, QDRANT_COLLECTION, EMBED_DIM
from app.graph.neo4j_client import Neo4jGraphStore
from app.rag import vector_db

logger = logging.getLogger(__name__)
```

(El resto de `SYSTEM_PROMPT` se toca en el Task 4, no acá.)

```python
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
    except ConnectionError:
        logger.warning("Grafo no disponible, el agente sigue solo con busqueda vectorial")
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
```

`_extract_text_from_content` no cambia.

- [ ] **Step 4: Correr el test, confirmar que pasa**

Run: `pytest tests/test_claude_agent_caching.py -v`
Expected: 1 passed. (Va a fallar todavía por otra razón: `_init_tools` en
`tools.py` no acepta un segundo parámetro `graph_store` hasta el Task 3.
Si pasa este step antes del Task 3, ver la nota de secuencia abajo.)

> **Nota de secuencia**: este Step 4 depende de que `_init_tools` ya acepte
> `(store, graph_store)` — ese cambio está en el Task 3 (Step 3). Si se
> ejecuta este Task 2 antes del Task 3, adelantar solo la firma de
> `_init_tools` (sin el resto del Task 3) para que el test pase:
>
> ```python
> def _init_tools(store: vector_db.QdrantStorage, graph_store=None) -> None:
>     global _store, _graph_store, _accumulated_sources
>     _store = store
>     _graph_store = graph_store
>     _accumulated_sources = []
> ```
>
> y sumar `_graph_store: object | None = None` al bloque de estado global
> junto a `_store`. El resto de la firma completa de `_graph_store` (tipo
> `Neo4jGraphStore | None`, uso real en `search_knowledge_base`) se termina
> en el Task 3 — este adelanto solo evita que el test de caching quede
> bloqueado por una dependencia de otra task.

- [ ] **Step 5: Verificación manual de cache hits (gasta API real)**

Con Qdrant y Neo4j corriendo:

```bash
python -m scripts.benchmark_agent proveedor
```

Mirar la columna `cache_read` en el reporte: tiene que ser mayor a 0 (el
baseline la tiene en 0 porque no existía caching). Si da 0, revisar
`usage.cache_read_input_tokens` round-trip por round-trip — puede ser que
el primer round-trip nunca cachee (el prefijo es chico) pero el segundo y
tercero sí deberían.

- [ ] **Step 6: Commit**

```bash
git add app/agent/claude_agent.py tests/test_claude_agent_caching.py
git commit -m "feat: prompt caching en el agente (palanca 1)"
```

---

### Task 3: Palanca 2 — programmatic tool calling

**Files:**
- Modify: `app/agent/tools.py`
- Modify: `app/agent/claude_agent.py` (system prompt, ver Task 4 — el
  cambio de `CODE_EXECUTION_TOOL` va acá, la redacción del prompt en el
  Task 4 para no mezclar las dos palancas en un mismo diff de texto)
- Test: `tests/test_tools_ptc.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `_init_tools(store, graph_store)` — firma final (si el Task 2
  se hizo antes con la firma adelantada, este task no la vuelve a tocar,
  solo la usa). `_graph_store: Neo4jGraphStore | None` como estado de
  módulo, mismo patrón que `_store`.

- [ ] **Step 1: Escribir los tests (fallan)**

Crear `tests/test_tools_ptc.py`:

```python
"""Programmatic tool calling (palanca 2): get_source_table tiene que poder
llamarse tanto directo (como hoy) como desde el codigo que escribe Claude
dentro de code_execution. Estos tests verifican la DECLARACION de las
tools, no una llamada real a Claude."""

from app.agent.tools import CODE_EXECUTION_TOOL, get_source_table


def test_code_execution_tool_usa_la_variante_programatica():
    # 20260120 (no 20260521): es la variante que soporta allowed_callers.
    assert CODE_EXECUTION_TOOL == {"type": "code_execution_20260120", "name": "code_execution"}


def test_get_source_table_es_invocable_desde_code_execution():
    schema = get_source_table.to_dict()
    assert "code_execution_20260120" in schema.get("allowed_callers", [])
```

- [ ] **Step 2: Correr los tests, confirmar que fallan**

Run: `pytest tests/test_tools_ptc.py -v`
Expected: FAIL — `CODE_EXECUTION_TOOL` todavía tiene `code_execution_20260521`,
y `get_source_table.to_dict()` no tiene `allowed_callers` en el dict (la
clave ni aparece cuando el decorador no la recibe).

- [ ] **Step 3: Implementar en `app/agent/tools.py`**

Reemplazar el bloque de estado global y `_init_tools`/`_get_store`:

```python
CODE_EXECUTION_TOOL = {"type": "code_execution_20260120", "name": "code_execution"}

# Estado global para pasar las stores y acumular sources entre tool calls
_store: vector_db.QdrantStorage | None = None
_graph_store = None  # Neo4jGraphStore | None -- import perezoso, ver search_knowledge_base
_accumulated_sources: list[str] = []


def _init_tools(store: vector_db.QdrantStorage, graph_store=None) -> None:
    """Inicializar los tools con las stores y resetear el estado."""
    global _store, _graph_store, _accumulated_sources
    _store = store
    _graph_store = graph_store
    _accumulated_sources = []


def _get_store() -> vector_db.QdrantStorage:
    """Obtener la instancia de store (debe estar inicializada con _init_tools)."""
    if _store is None:
        raise RuntimeError(
            "Tools no inicializados. Llamar _init_tools(store) desde run_turn() "
            "al inicio de cada turno."
        )
    return _store
```

Y `get_source_table` cambia solo el decorador (el cuerpo de la función no
cambia):

```python
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
```

`search_knowledge_base` se queda con `@beta_tool` sin argumentos (sigue
siendo `allowed_callers=["direct"]` por default) — el mapa de grafo se
integra en el Task 5, no acá.

- [ ] **Step 4: Correr los tests, confirmar que pasan**

Run: `pytest tests/test_tools_ptc.py -v`
Expected: 2 passed.

- [ ] **Step 5: Correr toda la suite (nada se rompió)**

Run: `pytest tests/ -v`
Expected: todos los tests existentes siguen en verde (56 antes de este
sub-proyecto, más los nuevos de las tasks anteriores).

- [ ] **Step 6: Verificación manual de un gráfico (gasta API real)**

Con la UI corriendo (`streamlit run streamlit_app.py`) o con un script
suelto, pedir: *"Graficá el gasto en catering de los últimos eventos"*.
Confirmar:
- Sale un gráfico (el camino de `files.save_generated_files` no cambió).
- En los logs, la secuencia de tool calls muestra `get_source_table` con
  `caller.type == "code_execution_20260120"` en vez de un `tool_use`
  directo (se puede inspeccionar imprimiendo `block.caller` en el loop de
  `benchmark_agent.run_question`, o revisando la respuesta cruda).

Si el gráfico no sale o sale distinto a como salía antes de este cambio,
es el criterio de rollback: revertir solo este Task 3 (queda acotado a
`CODE_EXECUTION_TOOL` y el decorador de `get_source_table`).

- [ ] **Step 7: Commit**

```bash
git add app/agent/tools.py tests/test_tools_ptc.py
git commit -m "feat: programmatic tool calling para get_source_table (palanca 2)"
```

---

### Task 4: Config — topes del grafo

**Files:**
- Modify: `app/config.py`

**Interfaces:**
- Produces: `GRAPH_MAX_ANCHORS: int` (default 5), `GRAPH_MAX_EDGES: int`
  (default 40) — consumidos por `retrieval.py` (Task 5) y `tools.py`
  (Task 6).

- [ ] **Step 1: Agregar las constantes**

En `app/config.py`, después del bloque `GRAPH_DEDUP_THRESHOLD`:

```python
# --- Enriquecimiento del agente con el grafo (sub-proyecto 2) ---
# Cuantas entidades "ancla" (las que aparecen en los documentos que ya
# encontro la busqueda semantica) se muestran en el mapa que ve Claude.
# 5: alcanza para orientar sin inflar el prompt.
GRAPH_MAX_ANCHORS = int(os.getenv("GRAPH_MAX_ANCHORS", "5"))
# Techo de aristas totales en el mapa. 40 cubre con margen las 11 aristas
# del nodo mas conectado del corpus de prueba ("Catering Buena Mesa") y
# mantiene el bloque en el orden de los 200-400 tokens que justifica esta
# palanca (contra los ~4.000 que cuesta una busqueda de chunks).
GRAPH_MAX_EDGES = int(os.getenv("GRAPH_MAX_EDGES", "40"))
```

No hace falta test unitario para esto (son constantes leídas por
`os.getenv`, mismo patrón que `GRAPH_DEDUP_THRESHOLD` que tampoco lo
tiene) — se ejercitan indirectamente en los tests del Task 5.

- [ ] **Step 2: Verificar que el módulo sigue importando**

Run: `python -c "from app.config import GRAPH_MAX_ANCHORS, GRAPH_MAX_EDGES; print(GRAPH_MAX_ANCHORS, GRAPH_MAX_EDGES)"`
Expected: `5 40`

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "feat: GRAPH_MAX_ANCHORS/GRAPH_MAX_EDGES en config"
```

---

### Task 5: `app/graph/retrieval.py` — funciones puras (TDD completo)

**Files:**
- Create: `app/graph/retrieval.py`
- Test: `tests/test_graph_retrieval.py`

**Interfaces:**
- Consumes: `GRAPH_MAX_ANCHORS`, `GRAPH_MAX_EDGES` de `app/config.py`
  (Task 4) como defaults, no como import obligatorio en cada test.
- Produces: `format_graph_context(anchors: list[dict], edges: list[dict], max_anchors: int = GRAPH_MAX_ANCHORS, max_edges: int = GRAPH_MAX_EDGES) -> str`

  Shape de `anchors`: `{"name": str, "norm_name": str, "types": list[str], "doc_count": int}`
  Shape de `edges`: `{"source": str, "rel_type": str, "target": str, "source_ids": list[str]}`

  Consumido por `app/agent/tools.py` en el Task 6.

- [ ] **Step 1: Escribir los tests (fallan)**

Crear `tests/test_graph_retrieval.py`:

```python
"""format_graph_context: convierte el resultado crudo de Neo4j (anchors +
edges, ya armados como dicts, sin Neo4j vivo) en el bloque de texto
compacto que ve Claude. Funcion pura -- mismo criterio que dedup.py y
cypher.py del sub-proyecto 1."""

from app.graph.retrieval import format_graph_context


def _anchor(name, types, doc_count, norm_name=None):
    return {"name": name, "norm_name": norm_name or name.lower(), "types": types, "doc_count": doc_count}


def _edge(source, rel_type, target, source_ids):
    return {"source": source, "rel_type": rel_type, "target": target, "source_ids": source_ids}


def test_sin_anclas_devuelve_vacio():
    assert format_graph_context([], []) == ""


def test_una_ancla_sin_aristas_se_muestra_igual():
    anchors = [_anchor("Catering Buena Mesa", ["Proveedor"], 6)]
    texto = format_graph_context(anchors, [])
    assert "Catering Buena Mesa" in texto
    assert "Proveedor" in texto
    assert "6" in texto


def test_arista_donde_la_ancla_es_el_origen_se_muestra_con_flecha_saliente():
    anchors = [_anchor("Catering Buena Mesa", ["Proveedor"], 6)]
    edges = [_edge("Catering Buena Mesa", "CONTRATADO_PARA", "Casamiento Perez-Gomez", ["gdrive:abc"])]

    texto = format_graph_context(anchors, edges)

    assert "-CONTRATADO_PARA->" in texto
    assert "Casamiento Perez-Gomez" in texto
    assert "gdrive:abc" in texto


def test_arista_donde_la_ancla_es_el_destino_se_muestra_con_flecha_entrante():
    anchors = [_anchor("Casamiento Perez-Gomez", ["Evento"], 4)]
    edges = [_edge("Catering Buena Mesa", "CONTRATADO_PARA", "Casamiento Perez-Gomez", ["gdrive:abc"])]

    texto = format_graph_context(anchors, edges)

    assert "<-CONTRATADO_PARA-" in texto
    assert "Catering Buena Mesa" in texto


def test_respeta_el_tope_de_anclas():
    anchors = [_anchor(f"Entidad{i}", ["Tipo"], 10 - i) for i in range(10)]
    texto = format_graph_context(anchors, [], max_anchors=3)
    assert texto.count("Entidad") == 3


def test_respeta_el_tope_de_aristas():
    anchors = [_anchor("Hub", ["Tipo"], 20)]
    edges = [_edge("Hub", "REL", f"Nodo{i}", []) for i in range(20)]
    texto = format_graph_context(anchors, edges, max_edges=5)
    assert texto.count("Nodo") == 5


def test_arista_sin_ningun_extremo_ancla_se_ignora():
    # No deberia pasar en la practica (neo4j_client.neighborhood siempre
    # devuelve aristas tocando al menos una ancla), pero si pasa, no debe
    # imprimir basura.
    anchors = [_anchor("Catering Buena Mesa", ["Proveedor"], 6)]
    edges = [_edge("Entidad X", "REL", "Entidad Y", [])]
    texto = format_graph_context(anchors, edges)
    assert "Entidad X" not in texto
    assert "Entidad Y" not in texto


def test_arista_sin_source_ids_no_rompe():
    anchors = [_anchor("Catering Buena Mesa", ["Proveedor"], 6)]
    edges = [_edge("Catering Buena Mesa", "REL", "Algo", [])]
    texto = format_graph_context(anchors, edges)
    assert "Algo" in texto  # no explota, solo no muestra un source_id
```

- [ ] **Step 2: Correr los tests, confirmar que fallan**

Run: `pytest tests/test_graph_retrieval.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.graph.retrieval'`.

- [ ] **Step 3: Implementar `app/graph/retrieval.py`**

```python
"""Arma el bloque de contexto de grafo que ve Claude, a partir del
resultado crudo de Neo4j (anchors_by_source_ids + neighborhood en
app/graph/neo4j_client.py).

Funcion pura a proposito -- mismo criterio que dedup.py y cypher.py del
sub-proyecto 1: es donde vive el presupuesto de tokens de esta palanca, y
se testea sin Neo4j vivo.
"""

from app.config import GRAPH_MAX_ANCHORS, GRAPH_MAX_EDGES


def format_graph_context(
    anchors: list[dict],
    edges: list[dict],
    max_anchors: int = GRAPH_MAX_ANCHORS,
    max_edges: int = GRAPH_MAX_EDGES,
) -> str:
    """anchors y edges vienen YA ordenados por relevancia (Neo4j hace el
    ORDER BY) -- esta funcion no reordena, solo recorta y formatea.

    Devuelve "" si no hay anclas (nada que mostrar), nunca None: el llamador
    siempre puede concatenar el resultado sin chequear null.
    """
    if not anchors:
        return ""

    capped_anchors = anchors[:max_anchors]
    anchor_names = {a["name"] for a in capped_anchors}
    capped_edges = edges[:max_edges]

    lines: list[str] = []
    for anchor in capped_anchors:
        types = "/".join(anchor.get("types") or [])
        lines.append(f"{anchor['name']} [{types}] ({anchor['doc_count']} docs)")

        for edge in capped_edges:
            source_ids = edge.get("source_ids") or []
            ref = f" ({source_ids[0]})" if source_ids else ""

            if edge["source"] == anchor["name"]:
                lines.append(f"  -{edge['rel_type']}-> {edge['target']}{ref}")
            elif edge["target"] == anchor["name"]:
                lines.append(f"  <-{edge['rel_type']}- {edge['source']}{ref}")
            # Ni source ni target es esta ancla: no corresponde bajo este
            # bloque (podria corresponder bajo otra ancla, se evalua en la
            # siguiente vuelta del for externo).

    return "\n".join(lines)
```

- [ ] **Step 4: Correr los tests, confirmar que pasan**

Run: `pytest tests/test_graph_retrieval.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/graph/retrieval.py tests/test_graph_retrieval.py
git commit -m "feat: retrieval.py -- formateo puro del mapa de grafo"
```

---

### Task 6: `neo4j_client.py` — lectura del vecindario

**Files:**
- Modify: `app/graph/neo4j_client.py`

**Interfaces:**
- Consumes: `normalize_name` de `app/graph/dedup.py` (ya importado en el
  archivo).
- Produces: `Neo4jGraphStore.anchors_by_source_ids(source_ids: list[str], limit: int) -> list[dict]`
  y `Neo4jGraphStore.neighborhood(norm_names: list[str], limit: int) -> list[dict]`,
  con los shapes de dict que consume `format_graph_context` (Task 5).
  Consumidos por `app/agent/tools.py` (Task 7).

No hay TDD automatizado en esta task: igual que `merge_entity` y
`remove_source_contribution` en el sub-proyecto 1, estos métodos hablan con
un Neo4j real y se verifican con un smoke script manual, no con pytest
(criterio ya establecido en el proyecto — ver
`docs/superpowers/specs/2026-08-31-optimizacion-agente-design.md` sección
Verificación).

- [ ] **Step 1: Implementar los dos métodos en `Neo4jGraphStore`**

Agregar en `app/graph/neo4j_client.py`, después de `get_all_entity_names`:

```python
    def anchors_by_source_ids(self, source_ids: list[str], limit: int) -> list[dict]:
        """Entidades ancla para el enriquecimiento del agente (sub-proyecto
        2): las que tienen AL MENOS uno de estos source_ids -- los mismos
        que ya devuelve QdrantStorage.search() -- ordenadas por cuantos
        documentos tocan en total (las mas conectadas primero, que son las
        que mas sirven para orientar una pregunta).
        """
        if not source_ids:
            return []
        query = """
        MATCH (e:Entity)
        WHERE any(sid IN e.source_ids WHERE sid IN $source_ids)
        RETURN e.name AS name, e.norm_name AS norm_name, e.types AS types,
               size(e.source_ids) AS doc_count
        ORDER BY doc_count DESC
        LIMIT $limit
        """
        records, _, _ = self.driver.execute_query(
            query, source_ids=source_ids, limit=limit, database_=self.database
        )
        return [dict(r) for r in records]

    def neighborhood(self, norm_names: list[str], limit: int) -> list[dict]:
        """Aristas donde el origen o el destino es una de estas anclas (por
        norm_name). Ordenadas por cuantos documentos evidencian cada
        relacion (mas fuentes primero), asi el corte por `limit` se queda
        con las aristas mejor respaldadas si hay mas de las que entran.
        """
        if not norm_names:
            return []
        query = """
        MATCH (a:Entity)-[r]->(b:Entity)
        WHERE a.norm_name IN $norm_names OR b.norm_name IN $norm_names
        RETURN a.name AS source, type(r) AS rel_type, b.name AS target,
               r.source_ids AS source_ids
        ORDER BY size(r.source_ids) DESC
        LIMIT $limit
        """
        records, _, _ = self.driver.execute_query(
            query, norm_names=norm_names, limit=limit, database_=self.database
        )
        return [dict(r) for r in records]
```

- [ ] **Step 2: Smoke test manual contra el grafo real (gasta nada de API,
  pero necesita Neo4j corriendo y ya poblado por el sub-proyecto 1)**

Crear un script descartable (no se commitea, es solo para verificar antes
de integrar):

```python
# smoke_neighborhood.py (correr y borrar, no forma parte del repo)
from app.graph.neo4j_client import Neo4jGraphStore

store = Neo4jGraphStore()

# "Catering Buena Mesa" -- el caso ancla del sub-proyecto 1, 6 source_ids.
# Sacar UN source_id real de esa entidad para probar la resolucion:
recs, _, _ = store.driver.execute_query(
    "MATCH (n:Entity {norm_name: 'catering buena mesa'}) RETURN n.source_ids AS sids",
    database_=store.database,
)
sample_source_id = recs[0]["sids"][0]
print("source_id de prueba:", sample_source_id)

anchors = store.anchors_by_source_ids([sample_source_id], limit=5)
print(f"\n{len(anchors)} anclas:")
for a in anchors:
    print(f"  {a['name']} {a['types']} ({a['doc_count']} docs)")

norm_names = [a["norm_name"] for a in anchors]
edges = store.neighborhood(norm_names, limit=40)
print(f"\n{len(edges)} aristas:")
for e in edges[:10]:
    print(f"  {e['source']} -{e['rel_type']}-> {e['target']} {e['source_ids']}")

store.close()
```

Correr: `python smoke_neighborhood.py`

Confirmar:
- `anchors` incluye "Catering Buena Mesa" con `doc_count >= 6`.
- `edges` incluye al menos una arista con "Catering Buena Mesa" como
  `source` (ej. `CONTRATADO_PARA` hacia algún evento).
- Ninguna excepción.

Borrar el script al terminar.

- [ ] **Step 3: Confirmar que la suite existente sigue en verde**

Run: `pytest tests/ -v`
Expected: todos pasan (este task no tocó ninguna función que ya tuviera
tests).

- [ ] **Step 4: Commit**

```bash
git add app/graph/neo4j_client.py
git commit -m "feat: anchors_by_source_ids y neighborhood en Neo4jGraphStore"
```

---

### Task 7: Integrar el mapa en `search_knowledge_base`

**Files:**
- Modify: `app/agent/tools.py`
- Test: `tests/test_tools_graph_context.py`

**Interfaces:**
- Consumes: `format_graph_context` (Task 5), `anchors_by_source_ids` /
  `neighborhood` (Task 6), `GRAPH_MAX_ANCHORS` / `GRAPH_MAX_EDGES` (Task 4).
- Produces: `_graph_context_for(graph_store, source_ids: list[str]) -> str`
  — función auxiliar aislada a propósito para poder testearla con un
  `graph_store` falso, sin Neo4j real (mismo patrón que
  `_sync_graph_safe` en `app/ingestion/pipeline.py` del sub-proyecto 1).
  `search_knowledge_base` sigue devolviendo un JSON string, ahora con una
  clave `"mapa"` nueva (string, `""` si no hay contexto de grafo).

- [ ] **Step 1: Escribir los tests (fallan)**

Crear `tests/test_tools_graph_context.py`:

```python
"""_graph_context_for: la logica de enriquecer una busqueda con el grafo,
aislada de search_knowledge_base para poder testearla con un graph_store
falso -- sin Neo4j real, y verificando en particular que un fallo del grafo
NUNCA rompe la busqueda semantica (search_knowledge_base tiene que seguir
funcionando aunque Neo4j este caido)."""

from app.agent.tools import _graph_context_for


class _FakeGraphStore:
    def __init__(self, anchors=None, edges=None, raise_on="none"):
        self._anchors = anchors or []
        self._edges = edges or []
        self._raise_on = raise_on

    def anchors_by_source_ids(self, source_ids, limit):
        if self._raise_on == "anchors":
            raise ConnectionError("Neo4j se cayo")
        return self._anchors

    def neighborhood(self, norm_names, limit):
        if self._raise_on == "neighborhood":
            raise ConnectionError("Neo4j se cayo")
        return self._edges


def test_graph_store_none_devuelve_vacio():
    assert _graph_context_for(None, ["gdrive:abc"]) == ""


def test_sin_source_ids_devuelve_vacio():
    store = _FakeGraphStore(anchors=[{"name": "X", "norm_name": "x", "types": [], "doc_count": 1}])
    assert _graph_context_for(store, []) == ""


def test_sin_anclas_encontradas_devuelve_vacio():
    store = _FakeGraphStore(anchors=[])
    assert _graph_context_for(store, ["gdrive:abc"]) == ""


def test_con_anclas_y_aristas_arma_el_mapa():
    store = _FakeGraphStore(
        anchors=[{"name": "Catering Buena Mesa", "norm_name": "catering buena mesa", "types": ["Proveedor"], "doc_count": 6}],
        edges=[{"source": "Catering Buena Mesa", "rel_type": "CONTRATADO_PARA", "target": "Casamiento Perez-Gomez", "source_ids": ["gdrive:abc"]}],
    )

    resultado = _graph_context_for(store, ["gdrive:abc"])

    assert "Catering Buena Mesa" in resultado
    assert "CONTRATADO_PARA" in resultado


def test_fallo_al_buscar_anclas_no_rompe_y_devuelve_vacio():
    store = _FakeGraphStore(raise_on="anchors")
    assert _graph_context_for(store, ["gdrive:abc"]) == ""


def test_fallo_al_buscar_vecindario_no_rompe_y_devuelve_vacio():
    store = _FakeGraphStore(
        anchors=[{"name": "X", "norm_name": "x", "types": [], "doc_count": 1}],
        raise_on="neighborhood",
    )
    assert _graph_context_for(store, ["gdrive:abc"]) == ""
```

- [ ] **Step 2: Correr los tests, confirmar que fallan**

Run: `pytest tests/test_tools_graph_context.py -v`
Expected: FAIL con `ImportError: cannot import name '_graph_context_for'`.

- [ ] **Step 3: Implementar en `app/agent/tools.py`**

`app/agent/tools.py:59-66` tiene hoy este bloque de imports (verificar con
`grep -n "^import\|^from" app/agent/tools.py` antes de editar, por si el
Task 3 ya lo modificó):

```python
import json

from anthropic import beta_tool  # noqa: F401 -- lo vas a necesitar para decorar

from app.rag import embeddings, vector_db  # noqa: F401
from app.config import EMBED_DIM, QDRANT_COLLECTION, QDRANT_URL  # noqa: F401

CODE_EXECUTION_TOOL = {"type": "code_execution_20260120", "name": "code_execution"}
```

Reemplazarlo por (agrega `logging`, `GRAPH_MAX_ANCHORS`/`GRAPH_MAX_EDGES`,
el import de `retrieval`, y el logger — todo lo demás queda igual):

```python
import json
import logging

from anthropic import beta_tool  # noqa: F401 -- lo vas a necesitar para decorar

from app.rag import embeddings, vector_db  # noqa: F401
from app.config import EMBED_DIM, GRAPH_MAX_ANCHORS, GRAPH_MAX_EDGES, QDRANT_COLLECTION, QDRANT_URL  # noqa: F401
from app.graph import retrieval

logger = logging.getLogger(__name__)

CODE_EXECUTION_TOOL = {"type": "code_execution_20260120", "name": "code_execution"}
```

Agregar la función nueva, después de `_get_store`:

```python
def _graph_context_for(graph_store, source_ids: list[str]) -> str:
    """Arma el mapa de grafo para una busqueda, a partir de los source_ids
    que ya devolvio Qdrant. Aislada de search_knowledge_base para poder
    testearla con un graph_store falso.

    Nunca propaga una excepcion: un fallo de Neo4j aca degrada a "sin mapa",
    no rompe la busqueda semantica -- mismo criterio que _sync_graph_safe
    en app/ingestion/pipeline.py.
    """
    if graph_store is None or not source_ids:
        return ""
    try:
        anchors = graph_store.anchors_by_source_ids(source_ids, limit=GRAPH_MAX_ANCHORS)
        if not anchors:
            return ""
        norm_names = [a["norm_name"] for a in anchors]
        edges = graph_store.neighborhood(norm_names, limit=GRAPH_MAX_EDGES)
        return retrieval.format_graph_context(anchors, edges)
    except Exception:
        logger.exception("No se pudo enriquecer con el grafo, sigo solo con busqueda vectorial")
        return ""
```

Y modificar `search_knowledge_base` (solo el final del cuerpo, después de
armar `result`):

```python
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

    query_vector = embeddings.embed_texts([query], input_type="query")[0]
    result = store.search(query_vector, top_k=top_k, kind_filter="text_chunk")

    global _accumulated_sources
    _accumulated_sources.extend([s for s in result["sources"] if s not in _accumulated_sources])

    result["mapa"] = _graph_context_for(_graph_store, result["sources"])

    return json.dumps(result, ensure_ascii=False)
```

- [ ] **Step 4: Correr los tests, confirmar que pasan**

Run: `pytest tests/test_tools_graph_context.py -v`
Expected: 6 passed.

- [ ] **Step 5: Correr toda la suite**

Run: `pytest tests/ -v`
Expected: todos en verde.

- [ ] **Step 6: Commit**

```bash
git add app/agent/tools.py tests/test_tools_graph_context.py
git commit -m "feat: enriquecer search_knowledge_base con el mapa del grafo (palanca 3)"
```

---

### Task 8: System prompt — cuándo usa el agente cada cosa

**Files:**
- Modify: `app/agent/claude_agent.py`

**Interfaces:**
- Consumes: nada nuevo (solo texto).
- Produces: `SYSTEM_PROMPT: str` actualizado.

- [ ] **Step 1: Reescribir `SYSTEM_PROMPT`**

Reemplazar la constante en `app/agent/claude_agent.py`:

```python
SYSTEM_PROMPT = """Sos un asistente de investigacion interno para una empresa de eventos.
Respondes preguntas usando el historial propio de eventos, presupuestos y proveedores de la empresa.

- Usa search_knowledge_base para encontrar texto relevante (resumenes de eventos, clausulas de contratos, notas de proveedores) en PDFs, Google Docs y planillas. Cada resultado incluye un campo "mapa" con las entidades y relaciones del grafo de conocimiento conectadas a esos documentos (ej. que otros eventos contrataron al mismo proveedor) -- revisalo antes de lanzar una busqueda nueva, muchas veces ya tiene la conexion que necesitas sin tener que buscar de nuevo.
- Si te piden un grafico, un total, un promedio o cualquier comparacion numerica exacta: NO la calcules a partir del texto de search_knowledge_base solo -- escribi codigo que llame a get_source_table con el source_id correspondiente para traer las filas exactas, y calcula/grafica (pandas/matplotlib disponibles) dentro de ese mismo codigo. get_source_table esta pensada para llamarse asi, desde tu codigo, no directo -- la tabla completa nunca tiene que entrar a la conversacion, solo el resultado que calcules.
- Siempre cita el/los archivo(s) fuente que usaste.
- Si no encontras nada relevante, decilo claramente en vez de inventar."""
```

- [ ] **Step 2: Confirmar que la suite sigue en verde**

Run: `pytest tests/ -v`
Expected: todos pasan (este cambio es solo texto, no toca ninguna
interfaz).

- [ ] **Step 3: Commit**

```bash
git add app/agent/claude_agent.py
git commit -m "feat: system prompt guia el uso del mapa de grafo y de get_source_table via codigo"
```

---

### Task 9: Medición final y documentación

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Correr el benchmark completo (gasta API real)**

Con Qdrant y Neo4j corriendo:

```bash
python -m scripts.benchmark_agent
```

Guardar la salida completa (las dos preguntas).

- [ ] **Step 2: Revisar a ojo la calidad de las respuestas**

El benchmark mide tokens/tiempo, no calidad. Correr las mismas dos
preguntas por la UI de Streamlit y confirmar a mano que las respuestas
siguen citando las fuentes correctas y no perdieron información contra lo
que se vio en el baseline original (sección "Contexto" del spec tiene las
respuestas completas del baseline para comparar).

- [ ] **Step 3: Documentar los resultados medidos en el README**

Agregar una sección después de "Cómo funciona la capa de grafo" en
`README.md`:

```markdown
## Optimización del agente (sub-proyecto 2)

Tres palancas aditivas sobre el agente de chat, medidas contra un baseline
congelado (dos preguntas reales, agente sin ninguna palanca aplicada):

1. **Prompt caching** (`app/agent/claude_agent.py`): la API es stateless y
   reenvía todo el historial en cada round-trip. Un solo parámetro
   (`cache_control`) baja ese re-envío a costo de caché.
2. **Programmatic tool calling** (`app/agent/tools.py`): `get_source_table`
   se llama desde el código que escribe Claude en `code_execution`, no
   directo -- las tablas completas ya no entran al contexto.
3. **Grafo de conocimiento** (`app/graph/retrieval.py`): `search_knowledge_base`
   devuelve, además de los chunks, un mapa compacto de las entidades y
   relaciones conectadas a esos documentos -- sin costo de LLM ni round-trips
   nuevos.

Resultados medidos (`python -m scripts.benchmark_agent`):

[completar con la tabla real de la corrida del Step 1]

Se evaluó (y se descartó) migrar el agente principal o la extracción de
entidades a un modelo local (la máquina de desarrollo tiene una RTX 5060 de
8GB vía Ollama): el ahorro de estas tres palancas viene de reducir la
*cantidad* de tokens, no el precio por token, y un modelo local en el
agente principal sería más lento con el volumen de contexto que maneja hoy.
Detalle completo en
`docs/superpowers/specs/2026-08-31-optimizacion-agente-design.md`.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: resultados medidos del sub-proyecto 2"
```

---

## Self-Review (completado durante la escritura de este plan)

**Cobertura del spec:** las tres palancas (Tasks 2, 3, 6-7-8), el arnés de
medición (Task 1), los topes configurables (Task 4), y la documentación de
resultados (Task 9) cubren cada sección del spec. `explore_entity` se
verificó que NO tiene ninguna task — está correctamente fuera de alcance.

**Inconsistencia encontrada y corregida:** el spec original bosquejaba
`find_entities(names)` (resolución de texto libre por fuzzy matching) como
uno de los "dos métodos de lectura" de `neo4j_client.py`, pero la sección
"Cómo se eligen las entidades ancla" del mismo spec describe un flujo
distinto: las anclas salen de los `source_ids` que ya trae la búsqueda de
Qdrant, no de texto libre. El spec quedó editado (`anchors_by_source_ids`
en vez de `find_entities`) y el plan implementa la versión consistente con
el flujo real de `search_knowledge_base`.

**Consistencia de tipos:** verificado que el shape de dict que devuelve
`anchors_by_source_ids`/`neighborhood` (Task 6) coincide exactamente con lo
que esperan `format_graph_context` (Task 5) y `_graph_context_for`
(Task 7): claves `name`/`norm_name`/`types`/`doc_count` para anclas,
`source`/`rel_type`/`target`/`source_ids` para aristas.

**Secuencia:** Task 2 (caching) depende de la firma de `_init_tools` que
formalmente se completa en el Task 3 — se documentó explícitamente el
adelanto necesario si se ejecutan en ese orden, para que ningún ejecutor
quede bloqueado.
