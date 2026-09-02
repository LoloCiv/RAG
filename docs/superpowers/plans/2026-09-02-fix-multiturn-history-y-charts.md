# Fix: historial multi-round-trip y captura de gráficos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arreglar dos bugs reales encontrados en uso en vivo del agente: (A) un turno con varios round-trips reales a la API (programmatic tool calling) corrompe el historial persistido, rompiendo el turno siguiente con un 400; (B) los gráficos que Claude genera con `code_execution` nunca se adjuntan porque `files.py` busca el tipo de bloque equivocado.

**Architecture:** `run_turn()`/`run_turn_streaming()` (`app/agent/claude_agent.py`) hoy solo conservan el ÚLTIMO mensaje que devuelve el `tool_runner` del SDK como "la respuesta del turno". Cuando el turno dispara más de un round-trip real (Claude llama una tool custom desde `code_execution` vía *programmatic tool calling*, pausa, se resuelve, y continúa), el runner internamente arma el historial COMPLETO y válido en `runner._params["messages"]` -- pero nosotros solo persistíamos el tramo final, que puede empezar con un `tool_result` cuyo `server_tool_use` vive en un round-trip anterior ya descartado. La próxima llamada a la API rechaza ese historial con 400 ("unexpected tool_use_id"). Esto también explica por qué se perdía narración intermedia del texto y (parcialmente) por qué no aparecían gráficos generados en una ronda que no fue la última.

Separado: `app/agent/files.py` busca bloques de tipo `bash_code_execution_tool_result`, pero este proyecto declara la tool como `code_execution_20260120` (necesaria para *programmatic tool calling*, de la que depende `get_source_table`), cuyo tipo real de bloque es `code_execution_tool_result` **sin el prefijo "bash_"** -- confirmado leyendo los tipos exactos del SDK instalado (`venv/Lib/site-packages/anthropic/types/beta/beta_code_execution_output_block.py` vs `beta_bash_code_execution_output_block.py`: mismo shape, `type` literal distinto). El fix soporta ambos nombres de tipo (Claude puede usar cualquiera de los dos sub-tools).

**Tech Stack:** Python 3.12, SDK `anthropic` (tool_runner beta), pytest, fakes propios (sin librerías de mocking).

**Spec:** No hay spec formal -- este plan sale de una sesión de debugging en vivo (systematic-debugging), no de un brainstorm previo. La investigación completa (lectura de `venv/Lib/site-packages/anthropic/lib/tools/_beta_runner.py`, los tipos del SDK, y dos fetches a la documentación oficial de Anthropic sobre `code-execution-tool` y `programmatic-tool-calling`) queda resumida en la sección "Context" de cada tarea abajo.

## Global Constraints

- TDD estricto: test que falla primero, después la implementación mínima (mismo patrón que el resto del proyecto -- ver `tests/` existentes).
- Correr los tests con `./venv/Scripts/python.exe -m pytest -q` (el Python global del sistema no tiene las dependencias del proyecto).
- Comentarios y docstrings en español, mismo estilo que el resto del código (explican el *por qué*, no el *qué*).
- No gastar llamadas reales a Claude/Voyage para verificar estas tareas -- todo se prueba con fakes. La Tarea 4 (al final, fuera del plan TDD) es la única que necesitaría una llamada real, y requiere confirmación explícita del usuario antes de correrla.
- No tocar `_tool_runner_kwargs()`, `_init_turn()`, `_readable_sources()`, ni el mecanismo de streaming (`run_turn_streaming`'s manejo de eventos `text_delta`/`tool_start`) -- funcionan bien, no forman parte de estos bugs.

---

### Task 1: `_new_messages_from_runner()` -- extraer todos los mensajes nuevos del turno, no solo el último

**Context:** `BaseSyncToolRunner.__run__()` en el SDK (`venv/Lib/site-packages/anthropic/lib/tools/_beta_runner.py:200-233`) hace `self.append_messages(message)` (o `message, response`) después de cada round-trip, creciendo `self._params["messages"]` con el mensaje de assistant y, si hubo tool calls, el mensaje de user con los `tool_result`. Cuando el loop `for message in runner: ...` termina (el turno completo terminó), `runner._params["messages"]` tiene el historial COMPLETO y válido de la conversación, incluidos TODOS los round-trips intermedios -- no hay una API pública que exponga esto, así que accedemos al dict interno directamente. `_new_messages_from_runner` extrae solo la parte NUEVA (lo agregado durante este turno), dejando afuera el `message_history` que ya se le pasó de entrada.

**Files:**
- Modify: `app/agent/claude_agent.py` (agregar función nueva, después de `_readable_sources`, antes de `_build_result` -- línea 165 actual)
- Test: `tests/test_claude_agent_history.py` (crear)

**Interfaces:**
- Produces: `_new_messages_from_runner(runner, original_len: int, last_message) -> list[dict]` -- usada por la Tarea 2 dentro de `run_turn()` y `run_turn_streaming()`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_claude_agent_history.py`:

```python
"""_new_messages_from_runner: extrae SOLO los mensajes que el tool_runner
agrego durante ESTE turno (no el message_history que ya se le paso de
entrada), en orden -- necesario para persistir un turno con multiples
round-trips reales a la API (ej. programmatic tool calling: el codigo de
code_execution llama a una tool custom, pausa, se resuelve, y continua en
un round-trip nuevo) sin corromper el historial.

Bug real que esto arregla: run_turn() guardaba solo last_message.content
como "la respuesta del turno". Cuando el turno tenia mas de un
round-trip, ese contenido final podia empezar con un
code_execution_tool_result cuyo server_tool_use vivia en un round-trip
ANTERIOR ya descartado -- estructuralmente invalido on its own. La
proxima llamada a la API lo rechazaba con:

    400 invalid_request_error: messages.1.content.0: unexpected
    tool_use_id found in code_execution_tool_result blocks:
    srvtoolu_xxx. Each code_execution_tool_result block must have a
    corresponding server_tool_use block before it.

No hay API publica que exponga el historial acumulado del runner --
accedemos a runner._params["messages"], el dict interno que el propio
runner arma y mantiene consistente en cada round-trip (ver
BaseSyncToolRunner.append_messages en
venv/Lib/site-packages/anthropic/lib/tools/_beta_runner.py). Cada
entrada ya es un dict plano (BetaMessageParam es un TypedDict), listo
para persistir o reenviar tal cual."""

from app.agent.claude_agent import _new_messages_from_runner


class _FakeRunnerConParams:
    def __init__(self, messages):
        self._params = {"messages": messages}


class _FakeMessage:
    def __init__(self, content):
        self.content = content


def test_devuelve_solo_los_mensajes_nuevos_no_el_historial_original():
    original = [{"role": "user", "content": "hola"}]
    nuevos = [
        {"role": "assistant", "content": []},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x"}]},
    ]
    runner = _FakeRunnerConParams(original + nuevos)

    result = _new_messages_from_runner(runner, len(original), _FakeMessage([]))

    assert result == nuevos


def test_conserva_varios_round_trips_sin_colapsarlos_a_uno_solo():
    original = [{"role": "user", "content": "hola"}]
    nuevos = [
        {"role": "assistant", "content": [{"type": "server_tool_use", "id": "srvtoolu_1"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "listo"}]},
    ]
    runner = _FakeRunnerConParams(original + nuevos)

    result = _new_messages_from_runner(runner, len(original), _FakeMessage([]))

    assert result == nuevos
    assert len(result) == 3


def test_degrada_a_un_solo_mensaje_si_el_runner_no_expone_params(caplog):
    # Resiliencia ante un SDK futuro que cambie la forma interna del
    # runner -- no debe explotar, degrada al comportamiento viejo (un
    # solo mensaje con el contenido final) y lo deja loggeado.
    class _RunnerSinParams:
        pass

    last_message = _FakeMessage([{"type": "text", "text": "hola"}])

    result = _new_messages_from_runner(_RunnerSinParams(), 1, last_message)

    assert result == [{"role": "assistant", "content": last_message.content}]


def test_degrada_a_lista_vacia_sin_runner_params_ni_last_message():
    class _RunnerSinParams:
        pass

    result = _new_messages_from_runner(_RunnerSinParams(), 1, None)

    assert result == []
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_claude_agent_history.py -v`
Expected: `ImportError: cannot import name '_new_messages_from_runner' from 'app.agent.claude_agent'`

- [ ] **Step 3: Implementar la función**

En `app/agent/claude_agent.py`, agregar después de `_readable_sources()` (antes de `def _build_result`, línea 165 actual):

```python
def _new_messages_from_runner(runner, original_len: int, last_message) -> list[dict]:
    """Todos los mensajes que el tool_runner agrego durante ESTE turno, en
    orden -- no solo el ultimo. Ver docstring de
    tests/test_claude_agent_history.py para el bug real que esto arregla
    (400 "unexpected tool_use_id" en el turno siguiente).

    No hay API publica que exponga el historial acumulado del runner --
    accedemos a runner._params["messages"], el dict interno que el propio
    runner arma y mantiene consistente en cada round-trip (ver
    BaseSyncToolRunner.append_messages en
    venv/Lib/site-packages/anthropic/lib/tools/_beta_runner.py). Si un
    SDK futuro cambia esa forma interna, degradamos al comportamiento
    viejo (un solo mensaje con last_message.content) en vez de explotar.
    """
    try:
        return list(runner._params["messages"][original_len:])
    except (AttributeError, KeyError, TypeError):
        logger.warning("No se pudo leer el historial completo del tool_runner, degradando a un solo mensaje")
        if last_message is None:
            return []
        return [{"role": "assistant", "content": last_message.content}]
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `./venv/Scripts/python.exe -m pytest tests/test_claude_agent_history.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/agent/claude_agent.py tests/test_claude_agent_history.py
git commit -m "feat: _new_messages_from_runner -- extraer todo el historial nuevo del turno, no solo el ultimo mensaje

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Usar `_new_messages_from_runner()` en `run_turn`/`run_turn_streaming` (arregla el bug del 400)

**Context:** Con la función de la Tarea 1 lista, hay que: (a) cambiar `_build_result()` para que arme `answer_text`/`chart_paths` a partir de TODOS los mensajes nuevos de assistant (no solo el último -- si no, se sigue perdiendo narración intermedia y charts de rondas no-finales), (b) reemplazar el campo `"response_content"` del resultado por `"new_messages"` (una lista de mensajes, no un solo content-block-list), y (c) actualizar `streamlit_app.py` para hacer `.extend(result["new_messages"])` en vez de un solo `.append(...)`. Los tres fakes de test existentes que simulan el `tool_runner` (`test_claude_agent_caching.py`, `test_claude_agent_sources.py`, `test_claude_agent_streaming.py`) necesitan un atributo `_params["messages"]` para no romperse -- eso también es parte de esta tarea.

**Files:**
- Modify: `app/agent/claude_agent.py:165-217` (`_build_result`, `run_turn`) y `:236-276` (`run_turn_streaming`)
- Modify: `streamlit_app.py:235-237`
- Modify: `tests/test_claude_agent_caching.py:21-26` (fake runner)
- Modify: `tests/test_claude_agent_sources.py:29-34` (fake runner)
- Modify: `tests/test_claude_agent_streaming.py:59-64` (fake runner)
- Test: `tests/test_claude_agent_history.py` (agregar un test de integración end-to-end vía `run_turn()`)

**Interfaces:**
- Consumes: `_new_messages_from_runner(runner, original_len, last_message) -> list[dict]` (Tarea 1)
- Produces: `run_turn(message_history) -> dict` con clave `"new_messages": list[dict]` en vez de `"response_content"`. `run_turn_streaming` mantiene el mismo shape final vía `_build_result`.

- [ ] **Step 1: Escribir el test de integración que falla**

Agregar al final de `tests/test_claude_agent_history.py`:

```python
import app.agent.claude_agent as claude_agent


class _FakeContentBlock:
    def __init__(self, type_, text=None):
        self.type = type_
        self.text = text


class _MultiRoundMessage:
    def __init__(self, content):
        self.content = content


class _MultiRoundFakeToolRunner:
    """Simula un turno con DOS round-trips reales (ej. programmatic tool
    calling): ronda 1 dice algo y llama una tool, ronda 2 sigue y
    termina. El __iter__ yieldea las DOS -- like the real runner does."""

    def __init__(self, *args, **kwargs):
        self._ronda1 = _MultiRoundMessage([_FakeContentBlock("text", "Encontre la planilla, calculando...")])
        self._ronda2 = _MultiRoundMessage([_FakeContentBlock("text", "Listo, el resultado es 42.")])
        self._params = {
            "messages": [
                *kwargs.get("messages", []),
                {"role": "assistant", "content": self._ronda1.content},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}]},
                {"role": "assistant", "content": self._ronda2.content},
            ]
        }

    def __iter__(self):
        return iter([self._ronda1, self._ronda2])


class _FakeBetaMessagesMultiRound:
    def tool_runner(self, **kwargs):
        return _MultiRoundFakeToolRunner(**kwargs)


class _FakeBetaMultiRound:
    def __init__(self):
        self.messages = _FakeBetaMessagesMultiRound()


class _FakeAnthropicClientMultiRound:
    def __init__(self, *args, **kwargs):
        self.beta = _FakeBetaMultiRound()


class _FakeQdrantStorage:
    def __init__(self, *args, **kwargs):
        pass


class _FakeGraphStore:
    def __init__(self, *args, **kwargs):
        pass

    def close(self) -> None:
        pass


def test_run_turn_conserva_texto_de_todas_las_rondas_no_solo_la_ultima(monkeypatch):
    monkeypatch.setattr(claude_agent.anthropic, "Anthropic", _FakeAnthropicClientMultiRound)
    monkeypatch.setattr(claude_agent.vector_db, "QdrantStorage", _FakeQdrantStorage)
    monkeypatch.setattr(claude_agent, "Neo4jGraphStore", _FakeGraphStore)
    monkeypatch.setattr(claude_agent, "_init_tools", lambda store, graph_store=None: None)

    result = claude_agent.run_turn([{"role": "user", "content": "hola"}])

    # Antes del fix esto daba solo "Listo, el resultado es 42." -- la
    # narracion de la ronda 1 se perdia porque solo se guardaba
    # last_message.content.
    assert "Encontre la planilla" in result["answer_text"]
    assert "Listo, el resultado es 42" in result["answer_text"]


def test_run_turn_new_messages_incluye_las_tres_entradas_del_turno(monkeypatch):
    monkeypatch.setattr(claude_agent.anthropic, "Anthropic", _FakeAnthropicClientMultiRound)
    monkeypatch.setattr(claude_agent.vector_db, "QdrantStorage", _FakeQdrantStorage)
    monkeypatch.setattr(claude_agent, "Neo4jGraphStore", _FakeGraphStore)
    monkeypatch.setattr(claude_agent, "_init_tools", lambda store, graph_store=None: None)

    result = claude_agent.run_turn([{"role": "user", "content": "hola"}])

    # 2 assistant + 1 user(tool_result) -- si esto colapsara a 1 solo
    # mensaje (el bug viejo), el historial que se persiste y se
    # reenvia a la API en el proximo turno quedaria roto.
    assert len(result["new_messages"]) == 3
    assert [m["role"] for m in result["new_messages"]] == ["assistant", "user", "assistant"]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_claude_agent_history.py -v`
Expected: `KeyError: 'answer_text'` o similar -- `result` no tiene ese shape todavía porque `run_turn` sigue devolviendo `"response_content"` armado del último mensaje solo (fallo real de contenido, no de import).

- [ ] **Step 3: Reescribir `_build_result` y `run_turn`**

En `app/agent/claude_agent.py`, reemplazar el bloque actual (líneas 165-217, desde `def _build_result` hasta el `finally` de `run_turn`):

```python
def _build_result(client: anthropic.Anthropic, last_message, new_messages: list[dict]) -> dict:
    """Arma el dict de resultado final de un turno a partir de TODOS los
    mensajes nuevos que agrego el tool_runner durante este turno (no solo
    el ultimo -- ver _new_messages_from_runner). Compartido entre
    run_turn() y run_turn_streaming().
    """
    if last_message is None:
        return {"new_messages": [], "answer_text": "", "sources": [], "chart_paths": []}

    # Texto y charts: recorrer los bloques de TODOS los mensajes de
    # assistant nuevos (puede haber mas de uno si el turno disparo varios
    # round-trips reales -- ej. programmatic tool calling), no solo el
    # ultimo. Si no, se pierde narracion intermedia ("Encontre la
    # planilla, calculando...") y charts generados en una ronda que no
    # fue la final.
    assistant_blocks = [
        block
        for m in new_messages
        if m.get("role") == "assistant"
        for block in (m.get("content") or [])
    ]
    answer_text = _extract_text_from_content(assistant_blocks)
    chart_paths = files.save_generated_files(client, assistant_blocks)

    return {
        "new_messages": new_messages,
        "answer_text": answer_text,
        "sources": _readable_sources(),
        "chart_paths": chart_paths,
    }


def run_turn(message_history: list[dict]) -> dict:
    """Ejecutar un turno del agente con Claude (no incremental -- ver
    run_turn_streaming() para la version con streaming/progreso, Fase 3).

    Args:
        message_history: Historial de mensajes en formato Anthropic

    Returns:
        dict con:
            - new_messages: TODOS los mensajes nuevos que agrego este
              turno (uno o mas round-trips -- ver _new_messages_from_runner),
              para extender message_history antes del proximo turno
            - answer_text: Texto concatenado de la respuesta (para mostrar)
            - sources: Lista de {"source_id", "file_name", "drive_url"} usados en búsquedas
            - chart_paths: Paths locales de gráficos generados
    """
    store, graph_store = _init_turn()
    client = anthropic.Anthropic()
    original_len = len(message_history)

    try:
        # cache_control: el contenido de tool results se reenvia completo en
        # cada round-trip (la API es stateless). Medido en el baseline: el
        # 79% de los tokens facturados en una pregunta compleja eran
        # contenido repetido de vueltas anteriores. Este parametro activa
        # caching automatico, que coloca el breakpoint en el ultimo bloque
        # cacheable y lo va corriendo a medida que crece la conversacion.
        runner = client.beta.messages.tool_runner(**_tool_runner_kwargs(message_history))

        last_message = None
        for message in runner:
            last_message = message

        new_messages = _new_messages_from_runner(runner, original_len, last_message)
        return _build_result(client, last_message, new_messages)
    finally:
        if graph_store is not None:
            graph_store.close()
```

- [ ] **Step 4: Actualizar `run_turn_streaming`**

En el mismo archivo, dentro de `run_turn_streaming` (línea 236 actual), reemplazar:

```python
    store, graph_store = _init_turn()
    client = anthropic.Anthropic()

    try:
        runner = client.beta.messages.tool_runner(stream=True, **_tool_runner_kwargs(message_history))

        last_message = None
        for stream in runner:
            with stream:
                for event in stream:
                    if event.type == "content_block_delta" and getattr(event.delta, "type", None) == "text_delta":
                        yield {"type": "text_delta", "text": event.delta.text}
                    elif event.type == "content_block_start":
                        block_type = getattr(event.content_block, "type", None)
                        if block_type in ("tool_use", "server_tool_use"):
                            tool_name = getattr(event.content_block, "name", block_type)
                            yield {"type": "tool_start", "label": _tool_progress_label(tool_name)}
                last_message = stream.get_final_message()

        yield {"type": "final", "result": _build_result(client, last_message)}
    finally:
        if graph_store is not None:
            graph_store.close()
```

por:

```python
    store, graph_store = _init_turn()
    client = anthropic.Anthropic()
    original_len = len(message_history)

    try:
        runner = client.beta.messages.tool_runner(stream=True, **_tool_runner_kwargs(message_history))

        last_message = None
        for stream in runner:
            with stream:
                for event in stream:
                    if event.type == "content_block_delta" and getattr(event.delta, "type", None) == "text_delta":
                        yield {"type": "text_delta", "text": event.delta.text}
                    elif event.type == "content_block_start":
                        block_type = getattr(event.content_block, "type", None)
                        if block_type in ("tool_use", "server_tool_use"):
                            tool_name = getattr(event.content_block, "name", block_type)
                            yield {"type": "tool_start", "label": _tool_progress_label(tool_name)}
                last_message = stream.get_final_message()

        new_messages = _new_messages_from_runner(runner, original_len, last_message)
        yield {"type": "final", "result": _build_result(client, last_message, new_messages)}
    finally:
        if graph_store is not None:
            graph_store.close()
```

- [ ] **Step 5: Actualizar `streamlit_app.py`**

Reemplazar (línea 235-237):

```python
            st.session_state.api_messages.append(
                {"role": "assistant", "content": result["response_content"]}
            )
```

por:

```python
            # new_messages puede ser mas de un mensaje (varios round-trips
            # reales en este turno, ej. programmatic tool calling) -- ver
            # _new_messages_from_runner en claude_agent.py. Guardar solo
            # un .append() del ultimo mensaje corrompia el historial.
            st.session_state.api_messages.extend(result["new_messages"])
```

- [ ] **Step 6: Actualizar los tres fakes de test existentes**

En `tests/test_claude_agent_caching.py`, reemplazar (líneas 21-26):

```python
class _FakeToolRunner:
    def __init__(self, captured_kwargs: dict, **kwargs):
        captured_kwargs.update(kwargs)

    def __iter__(self):
        return iter([_FakeMessage()])
```

por:

```python
class _FakeToolRunner:
    def __init__(self, captured_kwargs: dict, **kwargs):
        captured_kwargs.update(kwargs)
        self._params = {"messages": [*kwargs.get("messages", []), {"role": "assistant", "content": []}]}

    def __iter__(self):
        return iter([_FakeMessage()])
```

En `tests/test_claude_agent_sources.py`, reemplazar (líneas 29-34):

```python
class _FakeToolRunner:
    def __init__(self, *args, **kwargs):
        pass

    def __iter__(self):
        return iter([_FakeMessage()])
```

por:

```python
class _FakeToolRunner:
    def __init__(self, *args, **kwargs):
        self._params = {"messages": [*kwargs.get("messages", []), {"role": "assistant", "content": []}]}

    def __iter__(self):
        return iter([_FakeMessage()])
```

En `tests/test_claude_agent_streaming.py`, reemplazar (líneas 59-64):

```python
class _FakeStreamingToolRunner:
    def __init__(self, streams, **kwargs):
        self._streams = streams

    def __iter__(self):
        return iter(self._streams)
```

por:

```python
class _FakeStreamingToolRunner:
    def __init__(self, streams, **kwargs):
        self._streams = streams
        self._params = {
            "messages": [*kwargs.get("messages", []), *({"role": "assistant", "content": []} for _ in streams)]
        }

    def __iter__(self):
        return iter(self._streams)
```

- [ ] **Step 7: Correr TODA la suite y verificar que pasa**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: todos los tests en verde (141 previos + los nuevos de esta tarea), ninguno roto por el cambio de shape de `run_turn`.

- [ ] **Step 8: Commit**

```bash
git add app/agent/claude_agent.py streamlit_app.py tests/test_claude_agent_caching.py tests/test_claude_agent_sources.py tests/test_claude_agent_streaming.py tests/test_claude_agent_history.py
git commit -m "fix: preservar TODOS los round-trips de un turno, no solo el ultimo (bug real: 400 en el turno siguiente)

Un turno con programmatic tool calling dispara mas de un round-trip real
a la API. run_turn()/run_turn_streaming() solo guardaban
last_message.content -- si ese contenido final empezaba con un
tool_result cuyo server_tool_use vivia en un round-trip anterior
descartado, la proxima llamada a la API lo rechazaba con 400
'unexpected tool_use_id'. Reproducido en vivo con una pregunta real
(grafico de barras que llama get_source_table desde code_execution).

_new_messages_from_runner() lee el historial completo que el propio
tool_runner ya arma en runner._params[\"messages\"] -- no hay API publica
que lo exponga. result[\"response_content\"] (un solo content-block-list)
pasa a ser result[\"new_messages\"] (lista de mensajes completos,
extend() en vez de append() en streamlit_app.py). De paso arregla que se
perdia narracion intermedia del texto entre rondas.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Arreglar los nombres de tipo de bloque en `files.py` (gráficos no se adjuntaban)

**Context:** `save_generated_files()` busca `bash_code_execution_tool_result` / `bash_code_execution_result` / `bash_code_execution_output`. Pero `CODE_EXECUTION_TOOL = {"type": "code_execution_20260120", "name": "code_execution"}` (`app/agent/tools.py`) es la versión CON *programmatic tool calling* (necesaria para que `get_source_table` funcione desde `code_execution`, `allowed_callers=["code_execution_20260120"]`) -- y cuando Claude usa el sub-tool directo `code_execution` (en vez de `bash_code_execution`), el tipo real de los bloques de resultado NO lleva el prefijo "bash_": `code_execution_tool_result` / `code_execution_result` / `code_execution_output`. Confirmado comparando los tipos exactos del SDK instalado:

```
venv/Lib/site-packages/anthropic/types/beta/beta_code_execution_output_block.py:
    class BetaCodeExecutionOutputBlock(BaseModel):
        file_id: str
        type: Literal["code_execution_output"]

venv/Lib/site-packages/anthropic/types/beta/beta_bash_code_execution_output_block.py:
    class BetaBashCodeExecutionOutputBlock(BaseModel):
        file_id: str
        type: Literal["bash_code_execution_output"]
```

Mismo shape (`file_id: str`), tipo distinto. El fix soporta AMBOS nombres -- Claude puede usar el sub-tool `bash_code_execution` (comandos de shell) o el sub-tool directo `code_execution` (celda de Python, lo que usó en la prueba real) según el caso, y los dos tienen que capturarse.

**Nota importante, fuera de esta tarea:** incluso con este fix, en la prueba real que motivó esta investigación el bloque `code_execution_tool_result` tenía `content.content: []` (vacío) pese a que el código de Claude copió el archivo a `os.environ["OUTPUT_DIR"]` sin error. Leyendo la documentación oficial (`code-execution-tool.md`, sección "How generated files are captured"), la captura automática está descrita específicamente para llamadas al sub-tool `bash_code_execution` ("Each `bash_code_execution` call gets a new, empty directory...") -- no hay confirmación documentada de que la interfaz directa `code_execution` (celda de Python vía *programmatic tool calling*) dispare la misma captura. Este fix es correcto y necesario de todos modos (sin él, un archivo SÍ capturado nunca se procesa), pero puede no ser *suficiente* por sí solo -- ver Tarea 4 (opcional, fuera de este plan TDD) para la verificación en vivo.

**Files:**
- Modify: `app/agent/files.py`
- Test: `tests/test_files_save_generated.py` (crear)

**Interfaces:**
- Produces: `save_generated_files(client, content_blocks: list) -> list[str]` (firma sin cambios, comportamiento extendido).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_files_save_generated.py`:

```python
"""save_generated_files: baja los archivos que Claude genera con la tool
de code_execution (charts) via la Files API. Antes solo reconocia
bash_code_execution_tool_result (el sub-tool de comandos de shell) --
pero CODE_EXECUTION_TOOL esta declarada como code_execution_20260120
(programmatic tool calling, de la que depende get_source_table), y
cuando Claude usa el sub-tool DIRECTO code_execution (celda de Python,
sin pasar por bash), el tipo real del bloque de resultado no lleva el
prefijo "bash_": code_execution_tool_result / code_execution_result /
code_execution_output -- mismo shape que la variante bash-prefijada
(confirmado comparando los tipos del SDK), pero un string de tipo
distinto que el chequeo viejo nunca matcheaba. Bug real: un grafico que
Claude genero exitosamente nunca se adjuntaba en la UI.

Usa fakes con atributos (no dicts) -- getattr(block, "type", None) es
como el codigo real accede al tipo, igual que los objetos del SDK."""

from types import SimpleNamespace

from app.agent.files import save_generated_files


class _FakeFilesAPI:
    def __init__(self, filename: str, content: bytes):
        self._filename = filename
        self._content = content
        self.downloaded_file_ids: list[str] = []

    def retrieve_metadata(self, file_id: str):
        return SimpleNamespace(filename=self._filename)

    def download(self, file_id: str):
        self.downloaded_file_ids.append(file_id)
        return SimpleNamespace(write_to_file=lambda path: None)


class _FakeBeta:
    def __init__(self, files_api: _FakeFilesAPI):
        self.files = files_api


class _FakeClient:
    def __init__(self, files_api: _FakeFilesAPI):
        self.beta = _FakeBeta(files_api)


def _output_block(file_id: str, bash_prefix: bool) -> SimpleNamespace:
    type_name = "bash_code_execution_output" if bash_prefix else "code_execution_output"
    return SimpleNamespace(type=type_name, file_id=file_id)


def _result_block(file_id: str, bash_prefix: bool) -> SimpleNamespace:
    tool_result_type = "bash_code_execution_tool_result" if bash_prefix else "code_execution_tool_result"
    result_type = "bash_code_execution_result" if bash_prefix else "code_execution_result"
    return SimpleNamespace(
        type=tool_result_type,
        content=SimpleNamespace(
            type=result_type,
            content=[_output_block(file_id, bash_prefix)],
        ),
    )


def test_extrae_archivo_de_bloque_code_execution_tool_result_sin_prefijo_bash(monkeypatch, tmp_path):
    # El caso real que rompia: code_execution_20260120 (programmatic tool
    # calling) via el sub-tool directo, sin "bash_".
    import app.agent.files as files_module

    monkeypatch.setattr(files_module, "CHART_OUTPUTS_DIR", tmp_path)
    files_api = _FakeFilesAPI(filename="grafico.png", content=b"fake-png")
    client = _FakeClient(files_api)
    blocks = [_result_block("file_abc", bash_prefix=False)]

    saved = save_generated_files(client, blocks)

    assert saved == [str(tmp_path / "grafico.png")]
    assert files_api.downloaded_file_ids == ["file_abc"]


def test_sigue_funcionando_con_bash_code_execution_tool_result(monkeypatch, tmp_path):
    # No regresionar el sub-tool bash_code_execution (comandos de shell).
    import app.agent.files as files_module

    monkeypatch.setattr(files_module, "CHART_OUTPUTS_DIR", tmp_path)
    files_api = _FakeFilesAPI(filename="reporte.pdf", content=b"fake-pdf")
    client = _FakeClient(files_api)
    blocks = [_result_block("file_xyz", bash_prefix=True)]

    saved = save_generated_files(client, blocks)

    assert saved == [str(tmp_path / "reporte.pdf")]


def test_bloque_que_no_es_resultado_de_code_execution_se_ignora(tmp_path):
    blocks = [SimpleNamespace(type="text", text="hola")]

    assert save_generated_files(_FakeClient(_FakeFilesAPI("x", b"")), blocks) == []


def test_resultado_de_error_no_intenta_bajar_nada(tmp_path):
    error_block = SimpleNamespace(
        type="code_execution_tool_result",
        content=SimpleNamespace(type="code_execution_tool_result_error", error_code="timeout"),
    )

    assert save_generated_files(_FakeClient(_FakeFilesAPI("x", b"")), [error_block]) == []


def test_nombre_de_archivo_con_path_traversal_se_saltea(monkeypatch, tmp_path):
    # OJO: os.path.basename("../../etc/passwd") == "passwd" (un nombre
    # valido) -- NO dispara el guard. El guard existente solo cubre el
    # caso donde el basename resultante es exactamente "." o ".." (ej.
    # un filename que termina en "/.." tal cual), asi que el test tiene
    # que usar ESE caso, no una ruta con basename valido al final.
    import app.agent.files as files_module

    monkeypatch.setattr(files_module, "CHART_OUTPUTS_DIR", tmp_path)
    files_api = _FakeFilesAPI(filename="../..", content=b"x")
    client = _FakeClient(files_api)
    blocks = [_result_block("file_evil", bash_prefix=False)]

    assert save_generated_files(client, blocks) == []
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_files_save_generated.py -v`
Expected: `test_extrae_archivo_de_bloque_code_execution_tool_result_sin_prefijo_bash` FALLA (`saved == []`, no encuentra el bloque); los demás pueden pasar de casualidad -- lo que importa es que el primero falle por la razón correcta.

- [ ] **Step 3: Implementar el fix**

Reemplazar todo `app/agent/files.py`:

```python
"""Helper para bajar los archivos que genera la tool de ejecucion de codigo
(charts) via la Files API de Anthropic. Esto es mecanica de API, no una
decision de diseno de IA -- ya viene resuelto, no forma parte de lo que
tenes que escribir vos.

Uso tipico desde claude_agent.py, con los bloques de assistant de los
mensajes nuevos del turno (ver _build_result en claude_agent.py):

    chart_paths = save_generated_files(client, assistant_blocks)
"""

import logging
import os

from app.config import CHART_OUTPUTS_DIR

logger = logging.getLogger(__name__)

# CODE_EXECUTION_TOOL (app/agent/tools.py) es code_execution_20260120,
# necesaria para programmatic tool calling (de la que depende
# get_source_table). Claude puede generar archivos por dos sub-tools
# distintos segun el caso -- bash_code_execution (comandos de shell) o
# el sub-tool directo code_execution (celda de Python, sin pasar por
# bash) -- y cada uno usa un nombre de tipo de bloque distinto para lo
# que es, por lo demas, exactamente el mismo shape (confirmado
# comparando venv/Lib/site-packages/anthropic/types/beta/
# beta_code_execution_output_block.py vs
# beta_bash_code_execution_output_block.py: mismo campo file_id, type
# literal distinto). Sin este mapeo, un archivo generado por el segundo
# sub-tool nunca se reconocia -- bug real, un grafico generado con exito
# nunca se adjuntaba en la UI.
_CODE_EXECUTION_RESULT_TYPES = {
    "bash_code_execution_tool_result": ("bash_code_execution_result", "bash_code_execution_output"),
    "code_execution_tool_result": ("code_execution_result", "code_execution_output"),
}


def save_generated_files(client, content_blocks: list) -> list[str]:
    """Recorre los bloques de una respuesta de Claude buscando archivos
    generados por la tool de codigo (charts), los baja via la Files API y
    los guarda en data/chart_outputs/. Devuelve la lista de paths locales.
    """
    saved_paths: list[str] = []

    for block in content_blocks:
        result_type_names = _CODE_EXECUTION_RESULT_TYPES.get(getattr(block, "type", None))
        if result_type_names is None:
            continue
        expected_result_type, expected_output_type = result_type_names

        result = block.content
        if getattr(result, "type", None) != expected_result_type:
            # Es un error de la tool (result.error_code), no archivos.
            logger.warning("code_execution devolvio un error: %r", result)
            continue

        for file_ref in result.content or []:
            if getattr(file_ref, "type", None) != expected_output_type:
                continue

            try:
                metadata = client.beta.files.retrieve_metadata(file_ref.file_id)
                file_content = client.beta.files.download(file_ref.file_id)

                # Sanitizar el nombre: evita path traversal si Claude (o un
                # nombre de archivo raro) devolviera algo como "../../etc".
                safe_name = os.path.basename(metadata.filename)
                if not safe_name or safe_name in (".", ".."):
                    logger.warning("Nombre de archivo invalido, se saltea: %r", metadata.filename)
                    continue

                output_path = str(CHART_OUTPUTS_DIR / safe_name)
                file_content.write_to_file(output_path)
                saved_paths.append(output_path)
                logger.info("Grafico guardado en %s", output_path)
            except Exception:
                logger.exception("Fallo bajando el archivo generado %s", file_ref.file_id)

    return saved_paths
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_files_save_generated.py -v`
Expected: 5 passed

- [ ] **Step 5: Correr TODA la suite**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: todo en verde.

- [ ] **Step 6: Commit**

```bash
git add app/agent/files.py tests/test_files_save_generated.py
git commit -m "fix: save_generated_files reconoce code_execution_tool_result sin prefijo bash

CODE_EXECUTION_TOOL declara code_execution_20260120 (programmatic tool
calling, de la que depende get_source_table). Cuando Claude genera un
archivo via el sub-tool directo code_execution (celda de Python) en vez
de bash_code_execution, el bloque de resultado NO lleva el prefijo
'bash_' -- confirmado comparando los tipos exactos del SDK instalado
(mismo shape file_id:str, type literal distinto). El chequeo viejo solo
reconocia la variante bash-prefijada, asi que un grafico generado con
exito nunca se adjuntaba. Soporta ambos nombres de tipo ahora.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Tarea 4 (opcional, fuera del ciclo TDD -- requiere confirmación del usuario)

**No es una tarea con checkboxes** porque no se puede probar con fakes: verifica un comportamiento real de la API de Anthropic que la documentación no confirma para este caso específico (interfaz directa `code_execution` de *programmatic tool calling*, no `bash_code_execution`).

**Qué falta confirmar:** con las Tareas 2 y 3 aplicadas, ¿el archivo que Claude genera y copia a `os.environ["OUTPUT_DIR"]` desde una celda de Python directa (`code_execution`, sin pasar por `bash_code_execution`) queda capturado y aparece en `content.content` con un `file_id`? La documentación oficial solo confirma la captura para llamadas al sub-tool `bash_code_execution` explícitamente.

**Cómo probarlo (una sola llamada real a Claude, costo mínimo):** levantar la app (`streamlit run streamlit_app.py`, contenedores Docker arriba) y pedir un gráfico simple que dispare `code_execution` con `get_source_table` (ej. "Hacé un gráfico de barras con el presupuesto vs gastado de la planilla"). Revisar el JSON guardado en `data/conversations/` después: si `chart_paths` sigue vacío pero el `code_execution_tool_result` correspondiente en `new_messages` tiene `content.content` no vacío, el problema era solo el nombre de tipo (ya arreglado). Si `content.content` sigue vacío pese al fix, el problema es que la interfaz directa `code_execution` no dispara la captura de `$OUTPUT_DIR` -- en ese caso hace falta instruir a Claude (en `SYSTEM_PROMPT` o en la descripción de la tool) a generar archivos vía un paso explícito de `bash_code_execution` (ej. terminar el código con una llamada de shell que copie y liste el directorio, como recomienda la documentación) en vez de la celda directa.

**Antes de correr esto: preguntarle al usuario si quiere gastar esa llamada ahora o probarlo él mismo más adelante** -- mismo criterio de costo que el resto de la sesión.
