# Buzón de consultas + citas + MCP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el chat conversacional de `events-rag-poc` por un buzón de consultas stateless, con citas explícitas de consultas previas y un servidor MCP que lo expone hacia afuera.

**Architecture:** Cuatro fases secuenciales. Fase 1 introduce `app/agent/queries.py` (log append-only de consultas) y retira `app/agent/conversations.py`. Fase 2 introduce `app/agent/inbox.py` (compone el prompt con citas, ejecuta un turno único, guarda). Fase 3 expone `inbox.ask()` como una tool MCP vía stdio (`app/mcp_server.py`), con un lock global para la reentrancia de los globals de `app/agent/tools.py`. Fase 4 separa el modelo de extracción del grafo del modelo del agente. `app/agent/claude_agent.py` (contrato de `run_turn`/`run_turn_streaming`) y `app/agent/tools.py` no se tocan (salvo lectura).

**Tech Stack:** Python 3.11, Streamlit, SDK `anthropic` (tool_runner beta), SDK `mcp` (FastMCP, stdio transport), pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-buzon-de-consultas-mcp-design.md`

## Global Constraints

- **Naming:** identificadores (funciones, variables, campos de dict/JSON) en **inglés**; docstrings, comentarios, mensajes de log y texto de UI en **español**, explicando el *por qué*, no el *qué*.
- **Tests:** correr siempre con `./venv/Scripts/python.exe -m pytest -q` — el Python global del sistema no tiene las dependencias del proyecto.
- **TDD estricto:** test que falla → implementación mínima → verde → commit, en ese orden, en cada tarea.
- **Fakes propios, sin librerías de mocking** (`monkeypatch` de pytest), cero llamadas reales a Claude/Voyage/Qdrant/Neo4j en los tests.
- **Import estilo módulo** para todo lo que haya que monkeypatchear (`from app.agent import claude_agent` + `claude_agent.run_turn(...)`, nunca `from app.agent.claude_agent import run_turn`).
- **No pushear a `origin`** sin permiso explícito del usuario.
- **Antes de probar en vivo** (Fases 1-3): confirmar que Docker tiene arriba `neo4j` y `frosty_lalande` (`docker ps`; `docker start <nombre>` si están "Exited").
- **Streamlit cachea módulos en `sys.modules`:** al tocar código bajo `app/`, reiniciar el server (parar y volver a levantar `run_streamlit.bat` / la config de `.claude/launch.json`) — recargar la página no alcanza.
- **Checkpoint de fase:** al terminar la última tarea de cada fase, correr la suite completa y reportar el resultado antes de arrancar la fase siguiente.

---

## Fase 1 — Buzón

### Task 1: `app/config.py` — `QUERIES_DIR` + anclar `load_dotenv` a la raíz del proyecto

**Files:**
- Modify: `app/config.py:11-28`
- Test: `tests/test_config_env_anchor.py` (nuevo)

**Interfaces:**
- Produces: `app.config.QUERIES_DIR: Path` (= `DATA_DIR / "queries"`, creado en el mismo loop de `mkdir` que los demás dirs).

- [ ] **Step 1: Escribir el test que falla**

```python
"""app/config.py ancla load_dotenv() a PROJECT_ROOT (Fase 1, arreglo
necesario para la Fase 3 -- MCP via Claude Desktop): load_dotenv() sin
argumentos busca el .env desde el cwd hacia arriba. Un servidor lanzado
por Claude Desktop corre con un cwd arbitrario -- sin anclar, .env nunca
aparece y el server falla con "faltan ANTHROPIC_API_KEY".

Se prueba en un subproceso real (no reload del modulo) para no depender
de como pytest ya haya cacheado app.config -- y se le saca
ANTHROPIC_API_KEY al entorno heredado a proposito, para que la UNICA
forma de que el subproceso lo tenga sea que load_dotenv() haya leido el
.env real del proyecto pese a correr con un cwd que no lo tiene."""

import os
import subprocess
import sys
from pathlib import Path


def test_config_loads_env_regardless_of_cwd(tmp_path):
    project_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env["PYTHONPATH"] = str(project_root)

    result = subprocess.run(
        [sys.executable, "-c", "from app.config import ANTHROPIC_API_KEY; print(bool(ANTHROPIC_API_KEY))"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.stdout.strip() == "True", result.stderr


def test_queries_dir_lives_under_data_dir():
    from app import config

    assert config.QUERIES_DIR == config.DATA_DIR / "queries"
    assert config.QUERIES_DIR.exists()
```

- [ ] **Step 2: Correr el test, confirmar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_config_env_anchor.py -v`
Expected: `test_config_loads_env_regardless_of_cwd` FAIL (imprime "False" — sin `.env`, `ANTHROPIC_API_KEY` queda `None`). `test_queries_dir_lives_under_data_dir` FAIL con `AttributeError: module 'app.config' has no attribute 'QUERIES_DIR'`.

- [ ] **Step 3: Implementación mínima**

En `app/config.py`, invertir el orden de `load_dotenv()` y `PROJECT_ROOT`, y sumar `QUERIES_DIR`:

```python
# --- Paths del proyecto ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
DATA_DIR = PROJECT_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"
CHART_OUTPUTS_DIR = DATA_DIR / "chart_outputs"
# Fase 5 (persistencia de conversaciones): un JSON por conversacion, mismo
# patron que manifest.json -- ver app/agent/conversations.py.
CONVERSATIONS_DIR = DATA_DIR / "conversations"
# Fase 1 del buzon de consultas: un JSON por consulta, se escribe UNA VEZ
# (salvo el campo feedback) -- ver app/agent/queries.py.
QUERIES_DIR = DATA_DIR / "queries"
GOOGLE_CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
GOOGLE_TOKEN_PATH = PROJECT_ROOT / "token.json"

for _dir in (DOWNLOADS_DIR, DATA_DIR, CHART_OUTPUTS_DIR, CONVERSATIONS_DIR, QUERIES_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
```

También quitar el `load_dotenv()` viejo (sin argumentos) que estaba antes de `PROJECT_ROOT`.

- [ ] **Step 4: Correr el test, confirmar que pasa**

Run: `./venv/Scripts/python.exe -m pytest tests/test_config_env_anchor.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Correr la suite completa**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: sin fallos nuevos (154 + 2 = 156 passed).

- [ ] **Step 6: Commit**

```bash
git add app/config.py tests/test_config_env_anchor.py
git commit -m "feat: anclar load_dotenv a PROJECT_ROOT y sumar QUERIES_DIR

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: `app/agent/queries.py` — `new_query_id` + `save_query`

**Files:**
- Create: `app/agent/queries.py`
- Test: `tests/test_queries.py` (nuevo)

**Interfaces:**
- Consumes: `app.config.QUERIES_DIR: Path` (Task 1).
- Produces: `new_query_id() -> str`, `save_query(query_id, question, result, references=None, queries_dir=QUERIES_DIR) -> dict`, `_to_json_safe(value)`, `_path_for(query_id, queries_dir) -> Path` — usados por las Tasks 3-5 y por `app/agent/inbox.py` (Fase 2).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_queries.py`:

```python
"""Log de consultas del buzon (Fase 1): un JSON por consulta en
QUERIES_DIR (app/config.py), escrito UNA VEZ (salvo el campo feedback,
via set_feedback -- ver Task 5). Todo contra tmp_path -- cero llamadas
reales, cero contacto con data/queries/ real."""

import json

from anthropic.types.beta import BetaTextBlock

from app.agent.queries import (
    list_queries,
    load_query,
    new_query_id,
    save_query,
    set_feedback,
)


def _fake_result(**overrides):
    base = {"answer_text": "", "sources": [], "chart_paths": [], "new_messages": []}
    base.update(overrides)
    return base


def test_new_query_id_is_unique():
    assert new_query_id() != new_query_id()


def test_save_query_returns_the_full_record_shape(tmp_path):
    query_id = new_query_id()
    result = _fake_result(
        answer_text="el gasto fue 100",
        sources=[{"source_id": "gdrive:abc", "file_name": "x.pdf", "drive_url": "https://drive.google.com/file/d/abc/view"}],
        chart_paths=["/tmp/chart.png"],
        new_messages=[{"role": "assistant", "content": "ok"}],
    )

    record = save_query(query_id, "Cuanto gastamos?", result, queries_dir=tmp_path)

    assert record["id"] == query_id
    assert record["question"] == "Cuanto gastamos?"
    assert record["answer_text"] == "el gasto fue 100"
    assert record["sources"] == result["sources"]
    assert record["chart_paths"] == ["/tmp/chart.png"]
    assert record["feedback"] is None
    assert record["references"] == []
    assert "created_at" in record
    assert record["raw_messages"] == result["new_messages"]
    on_disk = json.loads((tmp_path / f"{query_id}.json").read_text(encoding="utf-8"))
    assert on_disk == record


def test_save_query_flattens_pydantic_blocks(tmp_path):
    query_id = new_query_id()
    result = _fake_result(
        new_messages=[{"role": "assistant", "content": [BetaTextBlock(type="text", text="respuesta")]}]
    )

    save_query(query_id, "pregunta", result, queries_dir=tmp_path)

    on_disk = json.loads((tmp_path / f"{query_id}.json").read_text(encoding="utf-8"))
    assert on_disk["raw_messages"][0]["content"] == [{"type": "text", "text": "respuesta", "citations": None}]


def test_title_is_derived_from_question_and_truncated_to_60(tmp_path):
    query_id = new_query_id()
    pregunta_larga = "x" * 100

    record = save_query(query_id, pregunta_larga, _fake_result(), queries_dir=tmp_path)

    assert len(record["title"]) <= 61  # 60 + el "…" de corte
    assert record["title"].startswith("x" * 60)


def test_references_defaults_to_empty_list(tmp_path):
    record = save_query(new_query_id(), "pregunta", _fake_result(), queries_dir=tmp_path)

    assert record["references"] == []
```

(Los tests de `load_query`/`list_queries`/`set_feedback` van en las Tasks 3-5 — importarlos ya ahora en el `from app.agent.queries import (...)` de arriba es intencional: hace que este archivo falle por `ImportError` hasta que existan, marcando el contrato completo del módulo desde el principio.)

- [ ] **Step 2: Correr el test, confirmar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_queries.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.agent.queries'`.

- [ ] **Step 3: Implementación mínima**

Crear `app/agent/queries.py`:

```python
"""Log de consultas del buzon (Fase 1 del sub-proyecto "buzon + citas +
MCP"): un JSON por consulta en QUERIES_DIR (app/config.py), mismo patron
de archivo que app/ingestion/manifest.py.

A diferencia del extinto app/agent/conversations.py, un registro se
escribe UNA VEZ (save_query) -- no hay updated_at ni reescritura del
registro entero por turno, porque cada consulta se resuelve sola y no
se re-manda nunca a la API (ver app/agent/inbox.py, Fase 2). La unica
mutacion permitida despues de escrito es el feedback (set_feedback).

raw_messages se guarda -- destrabo los dos bugs de multi-round-trip de
esta semana, ver tests/test_claude_agent_history.py -- pero es solo
para auditoria: nunca se re-envia a la API.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import QUERIES_DIR

_TITLE_MAX_LEN = 60


def new_query_id() -> str:
    return uuid.uuid4().hex


def _title_from_question(question: str) -> str:
    text = question.strip()
    if len(text) > _TITLE_MAX_LEN:
        return text[:_TITLE_MAX_LEN].rstrip() + "…"
    return text


def _to_json_safe(value):
    """Copiado literal de app/agent/conversations.py (a borrar en la
    Task 6): aplana bloques Pydantic del SDK (BetaTextBlock etc, no
    serializables directo con json.dumps) con .model_dump(mode="json")
    recursivamente sobre listas/dicts."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_json_safe(v) for k, v in value.items()}
    return value


def _path_for(query_id: str, queries_dir: Path) -> Path:
    return queries_dir / f"{query_id}.json"


def save_query(
    query_id: str,
    question: str,
    result: dict,
    references: list[str] | None = None,
    queries_dir: Path = QUERIES_DIR,
) -> dict:
    """Escribe el registro de una consulta (una sola vez) y lo devuelve.

    `result` es el dict tal cual sale de run_turn()/del evento "final" de
    run_turn_streaming() -- esta funcion es el UNICO lugar que sabe
    mapear ese shape al del registro persistido, para que si el agente
    cambia su contrato haya un solo lugar que tocar.
    """
    record = {
        "id": query_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": _title_from_question(question),
        "question": question,
        "references": references or [],
        "answer_text": result.get("answer_text", ""),
        "sources": result.get("sources", []),
        "chart_paths": result.get("chart_paths", []),
        "feedback": None,
        "raw_messages": _to_json_safe(result.get("new_messages", [])),
    }

    queries_dir.mkdir(parents=True, exist_ok=True)
    _path_for(query_id, queries_dir).write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return record
```

(`load_query`, `list_queries`, `set_feedback` se agregan en las Tasks 3-5 — dejar el `from ... import` del test tal cual, todavía va a fallar por `ImportError` hasta esas tasks; correr solo los tests de esta task con `-k` mientras tanto.)

- [ ] **Step 4: Correr los tests de esta task, confirmar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_queries.py -v -k "new_query_id or save_query_returns or flattens_pydantic or title_is_derived or references_defaults"`
Expected: PASS (5 tests). El resto del archivo sigue en error de colección por los imports de `load_query`/`list_queries`/`set_feedback` — esperado hasta la Task 5.

- [ ] **Step 5: Commit**

```bash
git add app/agent/queries.py tests/test_queries.py
git commit -m "feat: queries.py -- new_query_id y save_query del buzon de consultas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `app/agent/queries.py` — `load_query`

**Files:**
- Modify: `app/agent/queries.py`
- Test: `tests/test_queries.py` (agregar)

**Interfaces:**
- Consumes: `_path_for` (Task 2).
- Produces: `load_query(query_id, queries_dir=QUERIES_DIR) -> dict | None`.

- [ ] **Step 1: Agregar los tests que fallan**

Agregar a `tests/test_queries.py`:

```python
def test_load_query_missing_returns_none(tmp_path):
    assert load_query("no-existe", queries_dir=tmp_path) is None


def test_load_query_corrupt_returns_none(tmp_path):
    (tmp_path / "corrupto.json").write_text("{not valid json", encoding="utf-8")
    assert load_query("corrupto", queries_dir=tmp_path) is None
```

- [ ] **Step 2: Correr, confirmar que fallan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_queries.py -v -k load_query`
Expected: FAIL con `ImportError` (todavía) o `AttributeError` — `load_query` no existe.

- [ ] **Step 3: Implementación mínima**

Agregar a `app/agent/queries.py`, después de `save_query`:

```python
def load_query(query_id: str, queries_dir: Path = QUERIES_DIR) -> dict | None:
    """Devuelve el registro completo, o None si no existe o el archivo
    esta corrupto."""
    path = _path_for(query_id, queries_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
```

- [ ] **Step 4: Correr, confirmar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_queries.py -v -k load_query`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/agent/queries.py tests/test_queries.py
git commit -m "feat: queries.py -- load_query

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: `app/agent/queries.py` — `list_queries`

**Files:**
- Modify: `app/agent/queries.py`
- Test: `tests/test_queries.py` (agregar)

**Interfaces:**
- Consumes: `save_query` (Task 2, para poblar el `tmp_path` en los tests).
- Produces: `list_queries(queries_dir=QUERIES_DIR) -> list[dict]` — `[{"id", "title", "created_at"}, ...]`, más reciente primero.

- [ ] **Step 1: Agregar los tests que fallan**

```python
def test_list_queries_orders_by_created_at_descending(tmp_path):
    id_vieja = new_query_id()
    id_nueva = new_query_id()
    save_query(id_vieja, "vieja", _fake_result(), queries_dir=tmp_path)
    save_query(id_nueva, "nueva", _fake_result(), queries_dir=tmp_path)
    data = json.loads((tmp_path / f"{id_nueva}.json").read_text(encoding="utf-8"))
    data["created_at"] = "2099-01-01T00:00:00+00:00"
    (tmp_path / f"{id_nueva}.json").write_text(json.dumps(data), encoding="utf-8")

    listado = list_queries(queries_dir=tmp_path)

    assert [q["id"] for q in listado] == [id_nueva, id_vieja]


def test_list_queries_skips_corrupt_files(tmp_path):
    ok_id = new_query_id()
    save_query(ok_id, "ok", _fake_result(), queries_dir=tmp_path)
    (tmp_path / "corrupto.json").write_text("{not valid json", encoding="utf-8")

    listado = list_queries(queries_dir=tmp_path)

    assert [q["id"] for q in listado] == [ok_id]


def test_list_queries_returns_only_metadata(tmp_path):
    query_id = new_query_id()
    save_query(query_id, "pregunta", _fake_result(answer_text="secreto"), queries_dir=tmp_path)

    [entry] = list_queries(queries_dir=tmp_path)

    assert set(entry.keys()) == {"id", "title", "created_at"}
```

- [ ] **Step 2: Correr, confirmar que fallan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_queries.py -v -k list_queries`
Expected: FAIL — `list_queries` no existe.

- [ ] **Step 3: Implementación mínima**

Agregar a `app/agent/queries.py`:

```python
def list_queries(queries_dir: Path = QUERIES_DIR) -> list[dict]:
    """Metadata liviana [{id, title, created_at}], mas reciente primero.
    Un archivo corrupto se saltea en vez de romper el listado entero."""
    queries_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for path in queries_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        items.append({"id": data["id"], "title": data.get("title", ""), "created_at": data.get("created_at", "")})
    items.sort(key=lambda q: q["created_at"], reverse=True)
    return items
```

- [ ] **Step 4: Correr, confirmar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_queries.py -v -k list_queries`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/agent/queries.py tests/test_queries.py
git commit -m "feat: queries.py -- list_queries

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `app/agent/queries.py` — `set_feedback`

**Files:**
- Modify: `app/agent/queries.py`
- Test: `tests/test_queries.py` (agregar)

**Interfaces:**
- Consumes: `load_query` (Task 3), `_path_for` (Task 2).
- Produces: `set_feedback(query_id, feedback, queries_dir=QUERIES_DIR) -> None`.

- [ ] **Step 1: Agregar el test que falla**

```python
def test_set_feedback_does_not_clobber_the_rest_of_the_record(tmp_path):
    result = _fake_result(
        answer_text="respuesta",
        sources=[{"source_id": "gdrive:abc", "file_name": "x", "drive_url": None}],
        chart_paths=["a.png"],
    )
    query_id = new_query_id()
    save_query(query_id, "pregunta", result, references=["ref1"], queries_dir=tmp_path)

    set_feedback(query_id, "up", queries_dir=tmp_path)

    loaded = load_query(query_id, queries_dir=tmp_path)
    assert loaded["feedback"] == "up"
    assert loaded["answer_text"] == "respuesta"
    assert loaded["sources"] == result["sources"]
    assert loaded["chart_paths"] == ["a.png"]
    assert loaded["references"] == ["ref1"]
```

- [ ] **Step 2: Correr, confirmar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_queries.py -v -k set_feedback`
Expected: FAIL — `set_feedback` no existe. (A partir de este punto el `ImportError` original del archivo completo también desaparece: los 4 símbolos ya existen.)

- [ ] **Step 3: Implementación mínima**

Agregar a `app/agent/queries.py`:

```python
def set_feedback(query_id: str, feedback: str | None, queries_dir: Path = QUERIES_DIR) -> None:
    """Unica mutacion permitida sobre un registro ya escrito. Lee el
    registro completo, cambia solo "feedback" y reescribe -- no
    reusa save_query a proposito: esa es la funcion que arma un
    registro POR PRIMERA VEZ, mezclar las dos firmas confundiria cual
    es cual."""
    record = load_query(query_id, queries_dir=queries_dir)
    if record is None:
        return
    record["feedback"] = feedback
    _path_for(query_id, queries_dir).write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
```

- [ ] **Step 4: Correr toda la suite de `test_queries.py`, confirmar 11/11 en verde**

Run: `./venv/Scripts/python.exe -m pytest tests/test_queries.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add app/agent/queries.py tests/test_queries.py
git commit -m "feat: queries.py -- set_feedback, cierra el modulo del buzon (Fase 1)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: `streamlit_app.py` — reemplazar el chat por el buzón; retirar `conversations.py`

**Files:**
- Modify: `app/config.py` (quitar `CONVERSATIONS_DIR`), `streamlit_app.py` (reescritura completa)
- Delete: `app/agent/conversations.py`, `tests/test_conversations.py`

**Interfaces:**
- Consumes: `app.agent.queries.{list_queries, load_query, save_query, new_query_id, set_feedback}` (Tasks 2-5), `app.agent.claude_agent.run_turn_streaming` (ya existente, contrato intacto).
- Produces: ninguna interfaz nueva para otras tasks — `streamlit_app.py` es la vista final de esta fase.

**Sin tests nuevos** (principio explícito de la spec §1.5: `streamlit_app.py` queda sin tests — `AppTest` exigiría fakes de Qdrant/Neo4j/env activos en el import; toda lógica testeable ya vive en `queries.py`). La verificación es la suite completa + una prueba manual en vivo.

- [ ] **Step 1: Quitar `CONVERSATIONS_DIR` de `app/config.py`**

En `app/config.py`, borrar la línea `CONVERSATIONS_DIR = DATA_DIR / "conversations"` y su comentario, y sacar `CONVERSATIONS_DIR` del tuple de `mkdir`:

```python
for _dir in (DOWNLOADS_DIR, DATA_DIR, CHART_OUTPUTS_DIR, QUERIES_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Borrar `app/agent/conversations.py` y `tests/test_conversations.py`**

```bash
git rm app/agent/conversations.py tests/test_conversations.py
```

- [ ] **Step 3: Reescribir `streamlit_app.py` completo**

```python
"""UI del POC: buzon de consultas (Fase 1 del diseno "buzon + citas +
MCP", ver docs/superpowers/specs/2026-09-03-buzon-de-consultas-mcp-
design.md) + boton de resync de Google Drive.

Cada consulta es independiente -- no hay historial de chat que se
reenvia entre preguntas. Corre todo en un solo proceso: esta pantalla
llama directo a app/ingestion/pipeline.py y app/agent/claude_agent.py.

Para levantarlo: `streamlit run streamlit_app.py` (con el venv activado).
"""

import logging

import streamlit as st

from app.agent import claude_agent, queries
from app.config import GOOGLE_DRIVE_FOLDER_ID, require_env
from app.graph.neo4j_client import Neo4jGraphStore
from app.ingestion import manifest, pipeline
from app.logging_conf import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Agente de Eventos (POC)", page_icon="📋", layout="wide")


@st.cache_data(ttl=60, show_spinner=False)
def graph_stats() -> dict:
    """Conteos del grafo para el sidebar.

    Deja propagar la excepcion de conexion a proposito: quien la llama la
    muestra como un warning, no como un error fatal. Que Neo4j este
    apagado no tiene que romper el buzon -- el agente usa el camino
    vectorial, el grafo es solo una mejora.
    """
    store = Neo4jGraphStore()
    try:
        return store.stats()
    finally:
        store.close()


# --- Estado de sesion ---
# El buzon es stateless por diseno: st.chat_input devuelve la pregunta en
# el mismo run que se resuelve, sin acumular nada. La UNICA clave que
# sobrevive entre reruns es viewing_id -- que consulta mostrar (la recien
# respondida, o una elegida del sidebar).
if "viewing_id" not in st.session_state:
    st.session_state.viewing_id = None


# --- Sidebar: consultas recientes ---
with st.sidebar:
    st.header("Consultas recientes")

    for _q in queries.list_queries():
        _label = _q["title"] or "(sin título)"
        _is_active = _q["id"] == st.session_state.viewing_id
        if st.button(("📬 " if _is_active else "") + _label, key=f"q_{_q['id']}", use_container_width=True):
            st.session_state.viewing_id = _q["id"]
            st.rerun()

    st.divider()


# --- Sidebar: config + resync de Drive (intacto, no referencia nada del chat) ---
with st.sidebar:
    st.header("Configuracion")

    missing = require_env()
    if missing:
        st.error("Faltan variables de entorno: " + ", ".join(missing) + "\n\nRevisa tu archivo .env (ver .env.example).")

    st.caption(f"Carpeta de Drive: `{GOOGLE_DRIVE_FOLDER_ID or '(no configurada)'}`")

    if st.button("🔄 Resincronizar Google Drive", disabled=not GOOGLE_DRIVE_FOLDER_ID):
        with st.spinner("Sincronizando con Google Drive..."):
            try:
                result = pipeline.run_resync(GOOGLE_DRIVE_FOLDER_ID)
                graph_stats.clear()  # el resync acaba de mover el grafo
                st.success(result.summary)
                if result.failed:
                    with st.expander(f"⚠️ {len(result.failed)} archivo(s) con error"):
                        for name, err in result.failed:
                            st.write(f"**{name}**: {err}")
                if result.warnings:
                    with st.expander(f"📄 {len(result.warnings)} archivo(s) con advertencia"):
                        for name, warning in result.warnings:
                            st.write(f"**{name}**: {warning}")
            except Exception as e:
                logger.exception("Fallo el resync de Drive")
                st.error(f"No se pudo sincronizar: {e}")

    try:
        _stats = graph_stats()
        col_e, col_r = st.columns(2)
        col_e.metric("Entidades", _stats["entities"])
        col_r.metric("Relaciones", _stats["relationships"])
        st.caption("Grafo en [Neo4j Browser](http://localhost:7474)")
    except Exception as e:  # noqa: BLE001 - ver docstring de graph_stats
        st.warning(f"Grafo no disponible: {e}")

    man = manifest.load_manifest()
    if man:
        st.caption(f"{len(man)} archivo(s) ingeridos")
        with st.expander("Ver detalle"):
            st.dataframe(
                [
                    {
                        "archivo": entry["file_name"],
                        "tipo": entry["mime_type"].split(".")[-1],
                        "ultima ingesta": entry["last_ingested_at"],
                    }
                    for entry in man.values()
                ],
                hide_index=True,
                use_container_width=True,
            )


# --- Buzon principal ---
st.title("📋 Agente de Eventos (POC)")
st.caption("Mandá tu consulta sobre eventos, presupuestos y proveedores. Cada consulta es independiente.")


def _render_sources(sources: list[dict]) -> None:
    """Fuentes legibles: nombre de archivo, con link a Drive cuando
    drive_view_url() pudo resolverlo."""
    with st.expander(f"Fuentes ({len(sources)})"):
        for src in sources:
            if src.get("drive_url"):
                st.write(f"- [{src['file_name']}]({src['drive_url']})")
            else:
                st.write(f"- {src['file_name']}")


_FEEDBACK_INDEX_TO_VALUE = {0: "down", 1: "up"}
_FEEDBACK_VALUE_TO_INDEX = {"down": 0, "up": 1}


def _render_query(record: dict) -> None:
    """Fuentes + imagenes + feedback de un registro del buzon --
    compartido entre la consulta recien respondida (el texto ya se
    mostro por streaming, arriba de este llamado) y la que se elige del
    sidebar (el texto se muestra con st.write antes de este llamado).

    Lee y escribe directo sobre `record`, y persiste el feedback en el
    instante que cambia via queries.set_feedback -- st.feedback devuelve
    el valor actual en cada rerun, comparar contra lo ya guardado
    alcanza para saber si el click es nuevo.
    """
    if record.get("sources"):
        _render_sources(record["sources"])
    for chart_path in record.get("chart_paths", []):
        st.image(chart_path)

    current_index = _FEEDBACK_VALUE_TO_INDEX.get(record.get("feedback"))
    new_index = st.feedback("thumbs", key=f"fb_{record['id']}", default=current_index)
    new_feedback = _FEEDBACK_INDEX_TO_VALUE.get(new_index)
    if new_feedback != record.get("feedback"):
        queries.set_feedback(record["id"], new_feedback)
        record["feedback"] = new_feedback


user_input = st.chat_input("Escribí tu pregunta...")

if user_input:
    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        progress = st.empty()
        progress.markdown("*Pensando...*")
        final_record: dict = {}

        def _stream_answer_text():
            # Generador puente entre run_turn_streaming() (eventos
            # text_delta/tool_start/final) y st.write_stream (que solo
            # entiende chunks de texto). Los tool_start actualizan el
            # placeholder de progreso aparte, sin yieldearse.
            global final_record
            for event in claude_agent.run_turn_streaming([{"role": "user", "content": user_input}]):
                if event["type"] == "text_delta":
                    progress.empty()
                    yield event["text"]
                elif event["type"] == "tool_start":
                    progress.markdown(f"*{event['label']}*")
                elif event["type"] == "final":
                    query_id = queries.new_query_id()
                    final_record = queries.save_query(query_id, user_input, event["result"])

        try:
            st.write_stream(_stream_answer_text())
            progress.empty()
            _render_query(final_record)
            st.session_state.viewing_id = final_record["id"]
        except Exception as e:
            progress.empty()
            logger.exception("Fallo la consulta")
            st.error(f"Ocurrió un error: {e}")

elif st.session_state.viewing_id:
    _viewed = queries.load_query(st.session_state.viewing_id)
    if _viewed:
        with st.chat_message("user"):
            st.write(_viewed["question"])
        with st.chat_message("assistant"):
            st.write(_viewed["answer_text"])
            _render_query(_viewed)
```

- [ ] **Step 4: Correr la suite completa**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: sin fallos (156 − 8 tests de `test_conversations.py` + 11 de `test_queries.py` ≈ 159 passed — el número exacto no importa, el criterio es 0 failed).

- [ ] **Step 5: Verificación manual en vivo**

1. `docker ps` — confirmar `neo4j` y `frosty_lalande` corriendo (`docker start <nombre>` si no).
2. Levantar la app (`run_streamlit.bat` / preview del `.claude/launch.json`).
3. Mandar una consulta por `st.chat_input`. Verificar que responde y que aparece un archivo nuevo en `data/queries/`.
4. Click en la consulta desde el sidebar ("Consultas recientes") — verificar que se re-muestra completa.
5. Probar el feedback (thumbs up/down) y confirmar que `data/queries/<id>.json` refleja el cambio.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: streamlit_app.py como buzon de consultas; retira conversations.py

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

### ⏸️ Checkpoint Fase 1

Correr `./venv/Scripts/python.exe -m pytest -q` una vez más, confirmar 0 failed, y **avisar al usuario** con el resultado antes de arrancar la Fase 2.

---

## Fase 2 — Citar consultas previas

### Task 7: `app/config.py` — `CITATION_MAX_CHARS`

**Files:**
- Modify: `app/config.py`

**Interfaces:**
- Produces: `app.config.CITATION_MAX_CHARS: int` (default 2000).

- [ ] **Step 1: Agregar la constante**

En `app/config.py`, junto a `GRAPH_MAX_CHARS` (mismo criterio de comentario — "~4 chars/token, regla de dedo a proposito"):

```python
# --- Citas de consultas previas (Fase 2 del buzon) ---
# Techo de caracteres por respuesta citada. Citar 3 respuestas largas sin
# tope son ~12k tokens de ruido por consulta -- mismo criterio de regla
# de dedo que GRAPH_MAX_CHARS (~4 chars/token).
CITATION_MAX_CHARS = int(os.getenv("CITATION_MAX_CHARS", "2000"))
```

- [ ] **Step 2: Correr la suite completa (nada debería romperse, es solo una constante nueva)**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: sin fallos.

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "feat: CITATION_MAX_CHARS para el recorte de citas (Fase 2)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: `app/agent/inbox.py` — `build_prompt` (función pura)

**Files:**
- Create: `app/agent/inbox.py`
- Test: `tests/test_inbox_prompt.py` (nuevo)

**Interfaces:**
- Consumes: `app.config.CITATION_MAX_CHARS` (Task 7).
- Produces: `build_prompt(question: str, citations: list[dict]) -> str`, `_truncate_answer(answer_text: str) -> str`. Cada `citation` es un dict con al menos `id`, `question`, `answer_text` (el shape de un registro de `queries.py`, o un subconjunto para test).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_inbox_prompt.py`:

```python
"""build_prompt() (Fase 2): compone el prompt final que recibe Claude
cuando el usuario cita consultas previas. Funcion PURA -- recibe los
registros ya cargados, no ids -- por eso se testea sin tocar disco ni
la API.

Formato: un solo mensaje de usuario con preambulo delimitado. NO se
fabrican turnos user/assistant -- eso le daria a una respuesta vieja la
autoridad del propio razonamiento de Claude, errores incluidos (ver
spec, seccion 2.1)."""

from app.agent.inbox import build_prompt
from app.config import CITATION_MAX_CHARS


def test_no_references_prompt_is_the_raw_question():
    assert build_prompt("Cuanto gastamos en catering?", []) == "Cuanto gastamos en catering?"


def test_one_citation_includes_question_and_answer_delimited():
    citation = {"id": "ab12cd34", "question": "Cuanto gastamos en catering en 2025?", "answer_text": "El gasto fue 100"}

    prompt = build_prompt("Y en 2024?", [citation])

    assert '<query id="ab12cd34">' in prompt
    assert "<question>Cuanto gastamos en catering en 2025?</question>" in prompt
    assert "<answer>El gasto fue 100</answer>" in prompt
    assert "<current_question>\nY en 2024?\n</current_question>" in prompt


def test_citation_does_not_include_raw_messages_or_sources():
    citation = {
        "id": "ab12cd34",
        "question": "pregunta",
        "answer_text": "respuesta",
        "raw_messages": [{"role": "assistant", "content": "TEXTO_SECRETO_DE_RAW_MESSAGES"}],
        "sources": [{"file_name": "TEXTO_SECRETO_DE_SOURCES.pdf"}],
        "chart_paths": ["/tmp/TEXTO_SECRETO_DE_CHART.png"],
    }

    prompt = build_prompt("pregunta nueva", [citation])

    assert "TEXTO_SECRETO_DE_RAW_MESSAGES" not in prompt
    assert "TEXTO_SECRETO_DE_SOURCES" not in prompt
    assert "TEXTO_SECRETO_DE_CHART" not in prompt


def test_cited_answer_truncates_to_citation_max_chars_with_marker():
    respuesta_larga = "x" * (CITATION_MAX_CHARS + 500)
    citation = {"id": "ab12cd34", "question": "pregunta", "answer_text": respuesta_larga}

    prompt = build_prompt("pregunta nueva", [citation])

    assert "… [respuesta recortada]" in prompt
    assert respuesta_larga not in prompt


def test_multiple_citations_go_in_the_requested_order():
    primera = {"id": "id1", "question": "pregunta 1", "answer_text": "respuesta 1"}
    segunda = {"id": "id2", "question": "pregunta 2", "answer_text": "respuesta 2"}

    prompt = build_prompt("pregunta nueva", [primera, segunda])

    assert prompt.index('id="id1"') < prompt.index('id="id2"')


def test_prompt_marks_citations_as_reference_not_instructions():
    citation = {"id": "id1", "question": "pregunta", "answer_text": "respuesta"}

    prompt = build_prompt("pregunta nueva", [citation])

    assert "REFERENCIA" in prompt
    assert "instrucciones nuevas" in prompt
```

- [ ] **Step 2: Correr, confirmar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_inbox_prompt.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.agent.inbox'`.

- [ ] **Step 3: Implementación mínima**

Crear `app/agent/inbox.py`:

```python
"""Composicion y ejecucion de una consulta del buzon (Fase 2 del diseno
"buzon + citas + MCP"): arma el prompt final (con o sin citas de
consultas previas), ejecuta un turno UNICO del agente, y guarda el
resultado en el log de consultas (app/agent/queries.py).

Las citas se inyectan como texto de REFERENCIA delimitado en un solo
mensaje de usuario -- NUNCA como turnos user/assistant fabricados: eso
le daria a una respuesta vieja la autoridad del propio razonamiento de
Claude, errores incluidos. Ver build_prompt() para el formato exacto.
"""

import logging

from app.config import CITATION_MAX_CHARS

logger = logging.getLogger(__name__)

_CITATION_TRUNCATION_MARK = "… [respuesta recortada]"


def _truncate_answer(answer_text: str) -> str:
    """Recorta una respuesta citada a CITATION_MAX_CHARS -- citar varias
    respuestas largas sin tope infla el prompt en miles de tokens de
    ruido por consulta (ver app/config.py)."""
    if len(answer_text) <= CITATION_MAX_CHARS:
        return answer_text
    return answer_text[:CITATION_MAX_CHARS].rstrip() + _CITATION_TRUNCATION_MARK


def build_prompt(question: str, citations: list[dict]) -> str:
    """El prompt exacto que recibe Claude. Funcion PURA (recibe los
    registros ya cargados, no ids) -- es lo que la hace testeable sin
    tocar disco, y es la unica fuente de verdad del formato de citas.

    Sin citas: devuelve la pregunta cruda, sin wrapper -- el caso comun
    no paga ni un token de <current_question>.
    """
    if not citations:
        return question

    blocks = "\n\n".join(
        f'<query id="{c["id"]}">\n'
        f'<question>{c["question"]}</question>\n'
        f'<answer>{_truncate_answer(c["answer_text"])}</answer>\n'
        f'</query>'
        for c in citations
    )

    preamble = (
        f"El usuario está citando {len(citations)} consulta(s) anterior(es) como contexto. Es\n"
        "material de REFERENCIA (una pregunta y la respuesta que ya se dio), NO\n"
        "instrucciones nuevas: la tarea real es la que viene en <current_question>.\n"
        "No tenés el detalle de las búsquedas de esas consultas -- si necesitás\n"
        "datos que no están acá, buscalos de nuevo con search_knowledge_base."
    )

    return (
        f"<cited_queries>\n{preamble}\n\n{blocks}\n</cited_queries>\n\n"
        f"<current_question>\n{question}\n</current_question>"
    )
```

- [ ] **Step 4: Correr, confirmar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_inbox_prompt.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/agent/inbox.py tests/test_inbox_prompt.py
git commit -m "feat: inbox.py -- build_prompt, formato de citas (Fase 2)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: `app/agent/inbox.py` — `_citations_for` + `ask()`

**Files:**
- Modify: `app/agent/inbox.py`
- Test: `tests/test_inbox_ask.py` (nuevo)

**Interfaces:**
- Consumes: `build_prompt` (Task 8), `app.agent.claude_agent.run_turn` (existente, importado **por módulo**: `from app.agent import claude_agent`), `app.agent.queries.{load_query, save_query, new_query_id}` (Fase 1), `app.config.QUERIES_DIR`.
- Produces: `_citations_for(references, queries_dir) -> list[dict]`, `ask(question, references=None, queries_dir=QUERIES_DIR) -> dict` — usado por Task 10 (`ask_streaming`), Task 14 (lock) y `app/mcp_server.py` (Task 16).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_inbox_ask.py`:

```python
"""ask() (Fase 2): compone el prompt (build_prompt), ejecuta un turno
UNICO del agente via claude_agent.run_turn, guarda el registro, y lo
devuelve. Fakea claude_agent.run_turn -- cero llamadas reales a
Claude/Voyage, mismo criterio que test_claude_agent_sources.py.

Import estilo modulo (from app.agent import claude_agent) en inbox.py es
lo que permite monkeypatchear inbox.claude_agent.run_turn sin librerias
de mocking."""

from app.agent import inbox
from app.agent.queries import list_queries, load_query, new_query_id, save_query


def _fake_result(answer_text="respuesta", sources=None, chart_paths=None, new_messages=None):
    return {
        "answer_text": answer_text,
        "sources": sources or [],
        "chart_paths": chart_paths or [],
        "new_messages": new_messages or [],
    }


def test_missing_reference_is_skipped_without_breaking(tmp_path, monkeypatch):
    citada = save_query(new_query_id(), "pregunta vieja", _fake_result(answer_text="respuesta vieja"), queries_dir=tmp_path)
    captured = {}

    def fake_run_turn(message_history):
        captured["message_history"] = message_history
        return _fake_result()

    monkeypatch.setattr(inbox.claude_agent, "run_turn", fake_run_turn)

    inbox.ask("pregunta nueva", references=[citada["id"], "no-existe"], queries_dir=tmp_path)

    prompt = captured["message_history"][0]["content"]
    assert "pregunta vieja" in prompt
    assert "<cited_queries>" in prompt


def test_all_missing_references_degrades_to_raw_question(tmp_path, monkeypatch):
    captured = {}

    def fake_run_turn(message_history):
        captured["message_history"] = message_history
        return _fake_result()

    monkeypatch.setattr(inbox.claude_agent, "run_turn", fake_run_turn)

    inbox.ask("pregunta nueva", references=["no-existe-1", "no-existe-2"], queries_dir=tmp_path)

    assert captured["message_history"][0]["content"] == "pregunta nueva"


def test_ask_sends_a_single_user_message_history(tmp_path, monkeypatch):
    captured = {}

    def fake_run_turn(message_history):
        captured["message_history"] = message_history
        return _fake_result()

    monkeypatch.setattr(inbox.claude_agent, "run_turn", fake_run_turn)

    inbox.ask("pregunta", queries_dir=tmp_path)

    assert len(captured["message_history"]) == 1
    assert captured["message_history"][0]["role"] == "user"


def test_ask_saves_the_record_and_returns_the_id(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox.claude_agent, "run_turn", lambda mh: _fake_result(answer_text="la respuesta"))

    record = inbox.ask("pregunta", queries_dir=tmp_path)

    assert record["answer_text"] == "la respuesta"
    assert load_query(record["id"], queries_dir=tmp_path) is not None


def test_ask_persists_references_in_the_record(tmp_path, monkeypatch):
    citada = save_query(new_query_id(), "pregunta vieja", _fake_result(answer_text="respuesta vieja"), queries_dir=tmp_path)
    monkeypatch.setattr(inbox.claude_agent, "run_turn", lambda mh: _fake_result())

    record = inbox.ask("pregunta nueva", references=[citada["id"]], queries_dir=tmp_path)

    assert record["references"] == [citada["id"]]


def test_ask_saves_nothing_if_the_agent_fails(tmp_path, monkeypatch):
    def fake_run_turn(message_history):
        raise RuntimeError("la API se cayo")

    monkeypatch.setattr(inbox.claude_agent, "run_turn", fake_run_turn)

    raised = False
    try:
        inbox.ask("pregunta", queries_dir=tmp_path)
    except RuntimeError:
        raised = True

    assert raised, "se esperaba que la excepcion propague"
    assert list_queries(queries_dir=tmp_path) == []
```

- [ ] **Step 2: Correr, confirmar que fallan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_inbox_ask.py -v`
Expected: FAIL — `inbox.ask` no existe (`AttributeError`).

- [ ] **Step 3: Implementación mínima**

Agregar a `app/agent/inbox.py` (imports al tope del archivo, junto a los existentes):

```python
from pathlib import Path

from app.agent import claude_agent
from app.agent.queries import load_query, new_query_id, save_query
from app.config import QUERIES_DIR
```

Y agregar al final del archivo:

```python
def _citations_for(references: list[str] | None, queries_dir: Path) -> list[dict]:
    """Carga los registros citados en el orden pedido, salteando los que
    ya no existen (referencia colgada -- registro borrado a mano, etc.)."""
    if not references:
        return []
    citations = []
    for ref_id in references:
        record = load_query(ref_id, queries_dir=queries_dir)
        if record is None:
            logger.warning("Referencia colgada, se saltea: %s", ref_id)
            continue
        citations.append(record)
    return citations


def ask(question: str, references: list[str] | None = None, queries_dir: Path = QUERIES_DIR) -> dict:
    """Una consulta completa: compone el prompt, ejecuta, guarda, y
    devuelve el registro. Bloqueante -- es la que usa el servidor MCP
    (Fase 3).

    Si el agente levanta excepcion, no se guarda nada -- un registro a
    medias en un log de auditoria es peor que ninguno.
    """
    citations = _citations_for(references, queries_dir)
    prompt = build_prompt(question, citations)

    result = claude_agent.run_turn([{"role": "user", "content": prompt}])

    query_id = new_query_id()
    return save_query(query_id, question, result, references=references, queries_dir=queries_dir)
```

- [ ] **Step 4: Correr, confirmar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_inbox_ask.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/agent/inbox.py tests/test_inbox_ask.py
git commit -m "feat: inbox.py -- ask(), turno unico con citas opcionales (Fase 2)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: `app/agent/inbox.py` — `ask_streaming()`

**Files:**
- Modify: `app/agent/inbox.py`
- Test: `tests/test_inbox_ask.py` (agregar)

**Interfaces:**
- Consumes: `build_prompt`, `_citations_for` (Task 8-9), `app.agent.claude_agent.run_turn_streaming` (existente), `queries.{new_query_id, save_query}`.
- Produces: `ask_streaming(question, references=None, queries_dir=QUERIES_DIR)` — generador. Reenvía `text_delta`/`tool_start` tal cual; último evento `{"type": "final", "record": dict}`.

- [ ] **Step 1: Agregar los tests que fallan**

Agregar a `tests/test_inbox_ask.py`:

```python
def test_ask_streaming_forwards_text_delta_and_tool_start_as_is(tmp_path, monkeypatch):
    def fake_run_turn_streaming(message_history):
        yield {"type": "text_delta", "text": "hola"}
        yield {"type": "tool_start", "label": "buscando..."}
        yield {"type": "final", "result": _fake_result(answer_text="hola")}

    monkeypatch.setattr(inbox.claude_agent, "run_turn_streaming", fake_run_turn_streaming)

    events = list(inbox.ask_streaming("pregunta", queries_dir=tmp_path))

    assert events[0] == {"type": "text_delta", "text": "hola"}
    assert events[1] == {"type": "tool_start", "label": "buscando..."}


def test_ask_streaming_last_event_carries_the_saved_record(tmp_path, monkeypatch):
    def fake_run_turn_streaming(message_history):
        yield {"type": "final", "result": _fake_result(answer_text="la respuesta")}

    monkeypatch.setattr(inbox.claude_agent, "run_turn_streaming", fake_run_turn_streaming)

    events = list(inbox.ask_streaming("pregunta", queries_dir=tmp_path))

    last = events[-1]
    assert last["type"] == "final"
    assert last["record"]["answer_text"] == "la respuesta"
    assert load_query(last["record"]["id"], queries_dir=tmp_path) is not None
```

- [ ] **Step 2: Correr, confirmar que fallan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_inbox_ask.py -v -k streaming`
Expected: FAIL — `ask_streaming` no existe.

- [ ] **Step 3: Implementación mínima**

Agregar a `app/agent/inbox.py`:

```python
def ask_streaming(question: str, references: list[str] | None = None, queries_dir: Path = QUERIES_DIR):
    """Igual que ask() pero generador. Reenvia tal cual los text_delta y
    tool_start de run_turn_streaming, y emite como ultimo evento
    {"type": "final", "record": dict} -- clave "record", no "result",
    para no confundir el contrato de esta capa con el de claude_agent.
    """
    citations = _citations_for(references, queries_dir)
    prompt = build_prompt(question, citations)

    result = None
    for event in claude_agent.run_turn_streaming([{"role": "user", "content": prompt}]):
        if event["type"] == "final":
            result = event["result"]
        else:
            yield event

    query_id = new_query_id()
    record = save_query(query_id, question, result, references=references, queries_dir=queries_dir)
    yield {"type": "final", "record": record}
```

- [ ] **Step 4: Correr, confirmar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_inbox_ask.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add app/agent/inbox.py tests/test_inbox_ask.py
git commit -m "feat: inbox.py -- ask_streaming(), cierra el modulo de la Fase 2

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: `streamlit_app.py` — formulario de citas (multiselect + text_area)

**Files:**
- Modify: `streamlit_app.py`

**Interfaces:**
- Consumes: `app.agent.inbox.ask_streaming` (Task 10), `app.agent.queries.list_queries` (Fase 1).

**Sin tests nuevos** (mismo principio que la Task 6). Verificación: suite completa + prueba manual en vivo.

- [ ] **Step 1: Reemplazar el import de `claude_agent` por `inbox`, y el bloque de `st.chat_input` por el form**

En `streamlit_app.py`, cambiar la línea de import:

```python
from app.agent import inbox, queries
```

(sacar `claude_agent` del import — ya no se llama directo desde la UI.)

Reemplazar el bloque completo desde `user_input = st.chat_input(...)` hasta el final del archivo por:

```python
with st.form("query_form", clear_on_submit=True):
    _recent = queries.list_queries()
    _titles = {q["id"]: q["title"] for q in _recent}
    references = st.multiselect(
        "Citar consultas anteriores (opcional)",
        options=list(_titles),
        format_func=lambda qid: _titles[qid],
    )
    question = st.text_area(
        "Tu consulta",
        height=120,
        placeholder="Preguntá sobre eventos, presupuestos y proveedores…",
    )
    submitted = st.form_submit_button("Enviar consulta", type="primary")

if submitted and question.strip():
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        progress = st.empty()
        progress.markdown("*Pensando...*")
        final_record: dict = {}

        def _stream_answer_text():
            global final_record
            for event in inbox.ask_streaming(question, references=references or None):
                if event["type"] == "text_delta":
                    progress.empty()
                    yield event["text"]
                elif event["type"] == "tool_start":
                    progress.markdown(f"*{event['label']}*")
                elif event["type"] == "final":
                    final_record = event["record"]

        try:
            st.write_stream(_stream_answer_text())
            progress.empty()
            _render_query(final_record)
            st.session_state.viewing_id = final_record["id"]
        except Exception as e:
            progress.empty()
            logger.exception("Fallo la consulta")
            st.error(f"Ocurrió un error: {e}")

elif st.session_state.viewing_id:
    _viewed = queries.load_query(st.session_state.viewing_id)
    if _viewed:
        with st.chat_message("user"):
            st.write(_viewed["question"])
        with st.chat_message("assistant"):
            st.write(_viewed["answer_text"])
            _render_query(_viewed)
```

- [ ] **Step 2: Correr la suite completa**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: sin fallos (streamlit_app.py no se testea, pero nada más debería romperse).

- [ ] **Step 3: Verificación manual en vivo**

1. `docker ps` — confirmar `neo4j` y `frosty_lalande` arriba.
2. Reiniciar el server Streamlit (parar y volver a levantar — cachea módulos).
3. Mandar una primera consulta sin citar nada.
4. Mandar una segunda consulta citando la primera desde el `multiselect`. Verificar en `data/queries/<id-nueva>.json` que `references` tiene el id correcto, y que la respuesta demuestra que Claude vio el contexto citado.

- [ ] **Step 4: Commit**

```bash
git add streamlit_app.py
git commit -m "feat: streamlit_app.py -- formulario con multiselect de citas (Fase 2)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

### ⏸️ Checkpoint Fase 2

Correr `./venv/Scripts/python.exe -m pytest -q`, confirmar 0 failed, y **avisar al usuario** con el resultado antes de arrancar la Fase 3.

---

## Fase 3 — Servidor MCP

### Task 12: `pyproject.toml` — dependencia `mcp` + console script

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: paquete `mcp` instalado en el venv (`mcp.server.fastmcp.FastMCP`, `mcp.types.{TextContent, ImageContent}`), disponible para las Tasks 15-16.

- [ ] **Step 1: Agregar la dependencia y el console script**

En `pyproject.toml`, agregar a la lista `dependencies` (junto a las demás, con el mismo criterio de pin de rango que `voyageai`):

```toml
    # Servidor MCP (Fase 3 del buzon de consultas). Riesgo de DLL nativa
    # verificado nulo: el cierre transitivo trae una sola extension
    # nativa (rpds-py via jsonschema), ya instalada y ya importa bien en
    # este venv -- no repite el problema de uuid_utils que rompio
    # voyageai 0.4.x.
    "mcp>=1.2,<2",
```

Y agregar la sección de entry point al final del archivo:

```toml
[project.scripts]
events-rag-mcp = "app.mcp_server:main"
```

- [ ] **Step 2: Reinstalar el proyecto en modo editable**

Run: `./venv/Scripts/python.exe -m pip install -e .`
Expected: instala `mcp` y sus dependencias transitivas (`pydantic_settings`, `sse_starlette`, `httpx_sse`, etc.) sin error.

- [ ] **Step 3: Verificar el import**

Run: `./venv/Scripts/python.exe -c "from mcp.server.fastmcp import FastMCP; from mcp.types import TextContent, ImageContent; print('ok')"`
Expected: imprime `ok`.

- [ ] **Step 4: Correr la suite completa**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: sin fallos (dependencia nueva, cero código propio tocado todavía).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build: agregar dependencia mcp y console script events-rag-mcp (Fase 3)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: `app/config.py` — `require_query_env()` / `require_env()`

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config_require_env.py` (nuevo)

**Interfaces:**
- Produces: `require_query_env() -> list[str]` (solo `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`), `require_env() -> list[str]` (los cuatro, reusa `require_query_env()`). `streamlit_app.py` sigue usando `require_env()` sin cambios.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_config_require_env.py`:

```python
"""require_query_env()/require_env() (Fase 3): separados para que un
servidor de SOLO CONSULTA (MCP stdio) no exija credenciales de Drive ni
de Neo4j que nunca usa -- _init_turn() en claude_agent.py ya degrada
solo a busqueda vectorial si Neo4j no esta.

OJO al testear: estas funciones leen CONSTANTES DE MODULO capturadas en
el import (app.config.ANTHROPIC_API_KEY, etc), no os.environ -- hay que
monkeypatchear el modulo, no el entorno."""

from app import config


def test_require_query_env_does_not_require_drive_or_neo4j(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-xxx")
    monkeypatch.setattr(config, "VOYAGE_API_KEY", "pa-xxx")
    monkeypatch.setattr(config, "GOOGLE_DRIVE_FOLDER_ID", None)
    monkeypatch.setattr(config, "NEO4J_PASSWORD", None)

    assert config.require_query_env() == []


def test_require_query_env_requires_anthropic_and_voyage(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "VOYAGE_API_KEY", None)

    missing = config.require_query_env()

    assert "ANTHROPIC_API_KEY" in missing
    assert "VOYAGE_API_KEY" in missing


def test_require_env_still_requires_all_four(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "VOYAGE_API_KEY", None)
    monkeypatch.setattr(config, "GOOGLE_DRIVE_FOLDER_ID", None)
    monkeypatch.setattr(config, "NEO4J_PASSWORD", None)

    missing = config.require_env()

    assert set(missing) == {"ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "GOOGLE_DRIVE_FOLDER_ID", "NEO4J_PASSWORD"}
```

- [ ] **Step 2: Correr, confirmar que fallan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_config_require_env.py -v`
Expected: `require_query_env` tests FAIL con `AttributeError` (no existe todavía). `test_require_env_still_requires_all_four` puede pasar ya (comportamiento viejo) o fallar según el orden de escritura — no importa, se confirma en verde en el Step 4.

- [ ] **Step 3: Implementación mínima**

En `app/config.py`, reemplazar la función `require_env()` existente por:

```python
def require_query_env() -> list[str]:
    """Lo minimo para RESPONDER consultas: la base ya esta ingerida y el
    grafo degrada solo (ver _init_turn en claude_agent.py). Un servidor
    de solo-consulta (Fase 3, MCP stdio) no necesita credenciales de
    Drive ni de Neo4j."""
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not VOYAGE_API_KEY:
        missing.append("VOYAGE_API_KEY")
    return missing


def require_env() -> list[str]:
    """Todo lo que necesita la app completa, INGESTA incluida (Drive +
    Neo4j) -- la usa el sidebar de administracion de streamlit_app.py."""
    missing = require_query_env()
    if not GOOGLE_DRIVE_FOLDER_ID:
        missing.append("GOOGLE_DRIVE_FOLDER_ID")
    if not NEO4J_PASSWORD:
        missing.append("NEO4J_PASSWORD")
    return missing
```

- [ ] **Step 4: Correr, confirmar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_config_require_env.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Correr la suite completa**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: sin fallos (`streamlit_app.py` sigue llamando `require_env()`, comportamiento idéntico).

- [ ] **Step 6: Commit**

```bash
git add app/config.py tests/test_config_require_env.py
git commit -m "feat: separar require_query_env() de require_env() (Fase 3)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 14: `app/agent/inbox.py` — lock de reentrancia

**Files:**
- Modify: `app/agent/inbox.py`
- Test: `tests/test_inbox_lock.py` (nuevo)

**Interfaces:**
- Produces: `inbox._TURN_LOCK: threading.Lock`, `inbox._LOCK_TIMEOUT_S: int` (180). `ask()`/`ask_streaming()` ahora serializan el turno completo con el lock.

**Contexto (spec §3.4):** `app/agent/tools.py` tiene estado global por turno (`_accumulated_sources`, `_mapa_anchors_shown`) que una tool call concurrente pisaría. `@mcp.tool()` corre funciones sync en un worker thread de anyio — dos tool calls concurrentes corren de verdad en paralelo. Decisión: lock global en `inbox.ask()`/`ask_streaming()` (opción A de la spec), no en `run_turn()` ni en `tools.py`, y no `contextvars`/refactor por closure todavía (opciones B/C, rompen tests y `scripts/benchmark_agent.py` sin necesidad real — concurrencia hoy es ~1, stdio sirve a un solo cliente).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_inbox_lock.py`:

```python
"""Lock de reentrancia de inbox.ask() (Fase 3, decision A de la spec):
serializa turnos completos porque app/agent/tools.py tiene estado
global por turno (_accumulated_sources, _mapa_anchors_shown) que una
tool call concurrente pisaria -- ver docstring de _TURN_LOCK en
inbox.py.

El fake de claude_agent.run_turn de aca simula ESE bug a proposito: dos
hilos que corran de verdad en paralelo se pisan un estado global
compartido (_shared_state) si el lock no esta. Sin el lock, el primer
test de este archivo falla -- es el test que lo justifica."""

import threading
import time

from app.agent import inbox

_shared_state = {}


def _fake_run_turn_that_uses_shared_global(sources_por_pregunta: dict):
    def fake_run_turn(message_history):
        pregunta = message_history[0]["content"]
        mis_sources = sources_por_pregunta[pregunta]
        _shared_state["sources"] = mis_sources
        time.sleep(0.05)  # ventana para que un segundo hilo pise _shared_state
        return {
            "answer_text": pregunta,
            "sources": _shared_state["sources"],
            "chart_paths": [],
            "new_messages": [],
        }

    return fake_run_turn


def test_two_concurrent_asks_do_not_clobber_each_others_sources(tmp_path, monkeypatch):
    sources_por_pregunta = {
        "pregunta A": [{"source_id": "A", "file_name": "a.pdf", "drive_url": None}],
        "pregunta B": [{"source_id": "B", "file_name": "b.pdf", "drive_url": None}],
    }
    monkeypatch.setattr(inbox.claude_agent, "run_turn", _fake_run_turn_that_uses_shared_global(sources_por_pregunta))

    resultados = {}

    def correr(pregunta):
        resultados[pregunta] = inbox.ask(pregunta, queries_dir=tmp_path)

    hilo_a = threading.Thread(target=correr, args=("pregunta A",))
    hilo_b = threading.Thread(target=correr, args=("pregunta B",))
    hilo_a.start()
    time.sleep(0.01)  # asegura que A arranca primero y toma el lock
    hilo_b.start()
    hilo_a.join()
    hilo_b.join()

    assert resultados["pregunta A"]["sources"] == sources_por_pregunta["pregunta A"]
    assert resultados["pregunta B"]["sources"] == sources_por_pregunta["pregunta B"]


def test_lock_releases_if_the_agent_raises(tmp_path, monkeypatch):
    def fake_run_turn_que_explota(message_history):
        raise RuntimeError("la API se cayo")

    monkeypatch.setattr(inbox.claude_agent, "run_turn", fake_run_turn_que_explota)

    try:
        inbox.ask("pregunta", queries_dir=tmp_path)
    except RuntimeError:
        pass

    # Si el lock no se libero en el finally, esto se cuelga hasta el
    # timeout real (180s) -- acquire con timeout corto para que el test
    # falle rapido en vez de colgarse.
    adquirido = inbox._TURN_LOCK.acquire(timeout=2)
    assert adquirido, "el lock no se libero tras la excepcion"
    inbox._TURN_LOCK.release()
```

- [ ] **Step 2: Correr, confirmar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_inbox_lock.py -v`
Expected: `test_two_concurrent_asks_do_not_clobber_each_others_sources` FAIL (las sources se mezclan sin el lock — condición de carrera real con `time.sleep(0.05)` de ventana). `test_lock_releases_if_the_agent_raises` FAIL con `AttributeError: _TURN_LOCK` (no existe todavía).

- [ ] **Step 3: Implementación mínima**

En `app/agent/inbox.py`, agregar el import de `threading` al tope, y antes de `def ask(...)`:

```python
import threading

# Lock global de reentrancia (Fase 3, decision A de la spec -- ver
# docs/superpowers/specs/2026-09-03-buzon-de-consultas-mcp-design.md
# seccion 3.4 para las 2 alternativas descartadas y por que). Serializa
# turnos completos: app/agent/tools.py tiene estado global por turno
# (_accumulated_sources, _mapa_anchors_shown) que una tool call
# concurrente pisaria. @mcp.tool() (Fase 3) corre funciones sync en un
# worker thread de anyio -- dos tool calls concurrentes corren de verdad
# en paralelo.
#
# Y esto ya es un bug latente HOY sin MCP: Streamlit corre cada sesion
# en su propio ScriptRunner thread, dos pestanas preguntando a la vez ya
# se pisan _accumulated_sources en la app actual.
#
# threading.Lock (no RLock -- no hay anidamiento legitimo).
# acquire(timeout=...), no "with lock", para fallar con un error claro
# en vez de colgarse si algo queda mal liberado.
#
# Fecha de vencimiento documentada: correcto para stdio (concurrencia
# real ~1, un turno tarda 43-88s dominado por esperar a Claude);
# incorrecto el dia que se exponga HTTP con mas de un usuario real --
# ese dia toca resolver con contextvars.ContextVar (opcion B descartada
# ahora).
_TURN_LOCK = threading.Lock()
_LOCK_TIMEOUT_S = 180  # > el peor turno medido del baseline (87.8s), con margen
```

Y reemplazar `ask()` y `ask_streaming()` por:

```python
def ask(question: str, references: list[str] | None = None, queries_dir: Path = QUERIES_DIR) -> dict:
    """Una consulta completa: compone el prompt, ejecuta, guarda, y
    devuelve el registro. Bloqueante -- es la que usa el servidor MCP.

    Si el agente levanta excepcion, no se guarda nada -- un registro a
    medias en un log de auditoria es peor que ninguno. El lock (ver
    _TURN_LOCK arriba) serializa TODO el turno, no solo el guardado.
    """
    citations = _citations_for(references, queries_dir)
    prompt = build_prompt(question, citations)

    if not _TURN_LOCK.acquire(timeout=_LOCK_TIMEOUT_S):
        raise RuntimeError("El buzón está procesando otra consulta. Reintentá en unos segundos.")
    try:
        result = claude_agent.run_turn([{"role": "user", "content": prompt}])
    finally:
        _TURN_LOCK.release()

    query_id = new_query_id()
    return save_query(query_id, question, result, references=references, queries_dir=queries_dir)


def ask_streaming(question: str, references: list[str] | None = None, queries_dir: Path = QUERIES_DIR):
    """Igual que ask() pero generador. Reenvia tal cual los text_delta y
    tool_start de run_turn_streaming, y emite como ultimo evento
    {"type": "final", "record": dict}.

    Sostiene _TURN_LOCK durante TODO el streaming (no solo al leer el
    resultado final) -- las tool calls que emiten text_delta/tool_start
    ya estan tocando el estado global de tools.py mientras se itera. Si
    el generador se abandona sin agotar, el finally lo libera igual --
    comportamiento normal de un generador recolectado.
    """
    citations = _citations_for(references, queries_dir)
    prompt = build_prompt(question, citations)

    if not _TURN_LOCK.acquire(timeout=_LOCK_TIMEOUT_S):
        raise RuntimeError("El buzón está procesando otra consulta. Reintentá en unos segundos.")
    try:
        result = None
        for event in claude_agent.run_turn_streaming([{"role": "user", "content": prompt}]):
            if event["type"] == "final":
                result = event["result"]
            else:
                yield event
    finally:
        _TURN_LOCK.release()

    query_id = new_query_id()
    record = save_query(query_id, question, result, references=references, queries_dir=queries_dir)
    yield {"type": "final", "record": record}
```

- [ ] **Step 4: Correr, confirmar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_inbox_lock.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Correr la suite completa**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: sin fallos (`test_inbox_ask.py` sigue en verde — el lock no cambia el comportamiento single-threaded).

- [ ] **Step 6: Commit**

```bash
git add app/agent/inbox.py tests/test_inbox_lock.py
git commit -m "feat: lock global de reentrancia en inbox.ask/ask_streaming (Fase 3)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 15: `app/mcp_server.py` — `_to_mcp_content` (función pura)

**Files:**
- Create: `app/mcp_server.py`
- Test: `tests/test_mcp_server.py` (nuevo)

**Interfaces:**
- Consumes: `mcp.types.{TextContent, ImageContent}` (Task 12).
- Produces: `_to_mcp_content(record: dict) -> list` — usada por Task 16.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_mcp_server.py`:

```python
"""_to_mcp_content() (Fase 3): registro del buzon -> content blocks MCP.
Funcion PURA sobre el dict -- sin FastMCP corriendo, sin API real."""

import base64

from app.mcp_server import _to_mcp_content


def _record(**overrides):
    base = {"answer_text": "el gasto fue 100", "sources": [], "chart_paths": []}
    base.update(overrides)
    return base


def test_returns_text_with_the_answer():
    content = _to_mcp_content(_record(answer_text="el gasto fue 100"))

    assert content[0].type == "text"
    assert "el gasto fue 100" in content[0].text


def test_text_includes_sources_with_name_and_url():
    record = _record(sources=[
        {"source_id": "gdrive:abc", "file_name": "presupuesto.xlsx", "drive_url": "https://drive.google.com/file/d/abc/view"}
    ])

    content = _to_mcp_content(record)

    assert "presupuesto.xlsx" in content[0].text
    assert "https://drive.google.com/file/d/abc/view" in content[0].text


def test_each_chart_becomes_base64_image_content(tmp_path):
    # PNG minimo valido (1x1 pixel) -- alcanza, _to_mcp_content no lo
    # decodifica como imagen, solo lo lee y codifica en base64.
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360000002000155a3c3350000000049454e44ae426082"
    )
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(png_bytes)
    record = _record(chart_paths=[str(chart_path)])

    content = _to_mcp_content(record)

    images = [c for c in content if c.type == "image"]
    assert len(images) == 1
    assert images[0].mimeType == "image/png"
    assert base64.b64decode(images[0].data) == png_bytes


def test_missing_chart_file_is_skipped():
    record = _record(chart_paths=["/no/existe/chart.png"])

    content = _to_mcp_content(record)

    assert all(c.type != "image" for c in content)


def test_no_charts_returns_text_only():
    content = _to_mcp_content(_record(chart_paths=[]))

    assert len(content) == 1
    assert content[0].type == "text"
```

- [ ] **Step 2: Correr, confirmar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_mcp_server.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.mcp_server'`.

- [ ] **Step 3: Implementación mínima**

Crear `app/mcp_server.py` (solo lo necesario para esta task — el registro de la tool y `main()` se agregan en la Task 16):

```python
"""Servidor MCP (Fase 3): expone el buzon de consultas via stdio para
que lo consuma un cliente MCP (Claude Desktop/Code, o un motor de flujos
mas grande -- ver "Fuera de alcance" en la spec). Una sola tool,
query_events_kb, sin "references": un cliente MCP no puede poblar ese
parametro sin una segunda tool que liste ids validos -- exactamente la
tool que YAGNI dice no construir todavia.
"""

import base64
import logging
from pathlib import Path

from mcp.types import ImageContent, TextContent

logger = logging.getLogger(__name__)


def _to_mcp_content(record: dict) -> list:
    """Registro del buzon -> content blocks de MCP. Funcion PURA sobre
    el registro (no llama al agente) -- por eso se puede testear entera
    sin servicios.

    Devuelve un TextContent (respuesta + fuentes) y un ImageContent en
    base64 por cada chart_path que TODAVIA exista en disco -- el cliente
    MCP puede correr en otra maquina/sandbox, un path local no significa
    nada ahi. Un chart que ya no esta en disco (registro viejo, archivo
    borrado) se saltea con warning en vez de romper la respuesta entera.
    """
    text = record.get("answer_text", "")
    sources = record.get("sources", [])
    if sources:
        lines = ["", "Fuentes:"]
        for src in sources:
            if src.get("drive_url"):
                lines.append(f"- {src['file_name']} ({src['drive_url']})")
            else:
                lines.append(f"- {src['file_name']}")
        text += "\n".join(lines)

    content: list = [TextContent(type="text", text=text)]

    for chart_path in record.get("chart_paths", []):
        path = Path(chart_path)
        if not path.exists():
            logger.warning("Chart ya no esta en disco, se saltea: %s", chart_path)
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append(ImageContent(type="image", data=data, mimeType="image/png"))

    return content
```

- [ ] **Step 4: Correr, confirmar que pasan**

Run: `./venv/Scripts/python.exe -m pytest tests/test_mcp_server.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: mcp_server.py -- _to_mcp_content (Fase 3)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 16: `app/mcp_server.py` — tool `query_events_kb` + `main()`

**Files:**
- Modify: `app/mcp_server.py`, `app/logging_conf.py` (docstring)
- Test: `tests/test_mcp_server.py` (agregar)

**Interfaces:**
- Consumes: `_to_mcp_content` (Task 15), `app.agent.inbox.ask` (Task 14), `app.config.require_query_env` (Task 13).
- Produces: `app.mcp_server.mcp: FastMCP`, `app.mcp_server.query_events_kb(question: str) -> list`, `app.mcp_server.main() -> None`.

- [ ] **Step 1: Agregar el test que falla**

Agregar a `tests/test_mcp_server.py`:

```python
from app.mcp_server import mcp


def test_tool_is_registered_on_the_server():
    tools = mcp._tool_manager.list_tools()
    names = {t.name for t in tools}

    assert "query_events_kb" in names
    [tool] = [t for t in tools if t.name == "query_events_kb"]
    assert "eventos" in tool.description.lower()
```

**Nota para quien ejecute esta task:** la introspección exacta de `FastMCP` (`_tool_manager.list_tools()`) es la API conocida del SDK `mcp` 1.x al momento de escribir este plan. Si al correr el test da `AttributeError` por un nombre distinto, explorar interactivamente con `./venv/Scripts/python.exe` (`dir(mcp)`, `dir(mcp._tool_manager)`) y ajustar la aserción — el contrato que importa es "poder confirmar que `query_events_kb` está registrada, con su descripción", no el nombre exacto del atributo interno.

- [ ] **Step 2: Correr, confirmar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_mcp_server.py -v -k test_tool_is_registered`
Expected: FAIL — `mcp` no existe en el módulo todavía.

- [ ] **Step 3: Implementación mínima**

Agregar a `app/mcp_server.py` (después de los imports existentes, agregar `sys` y `FastMCP`):

```python
import sys

from mcp.server.fastmcp import FastMCP

from app.agent import inbox
from app.config import require_query_env
from app.logging_conf import setup_logging

mcp = FastMCP("events-rag")
```

Y al final del archivo:

```python
def query_events_kb(question: str) -> list:
    """Responde una pregunta sobre eventos, presupuestos y proveedores
    de la empresa, buscando en la base de conocimiento propia. Devuelve
    el texto de la respuesta con sus fuentes, y un grafico por cada uno
    que se haya generado.
    """
    record = inbox.ask(question)
    return _to_mcp_content(record)


# Registro explicito, no decorador -- asi el test importa la funcion
# plana (query_events_kb) y la llama directo, sin tocar internals de
# FastMCP ni levantar un event loop.
mcp.tool()(query_events_kb)


def main() -> None:
    """Entry point stdio. OJO: en stdio, stdout ES el canal JSON-RPC --
    cualquier print() corrompe el protocolo. Todo diagnostico va a
    stderr (setup_logging() ya usa logging.basicConfig() sin handler,
    cuyo default es StreamHandler(sys.stderr) -- verificado, es seguro
    para stdio).
    """
    missing = require_query_env()
    if missing:
        print("Faltan variables de entorno: " + ", ".join(missing), file=sys.stderr)
        sys.exit(1)
    setup_logging()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

Corregir además el docstring de `app/logging_conf.py` (decía "todo a stdout", la conducta real —`StreamHandler(sys.stderr)` por default— es a stderr):

```python
"""Configuracion de logging para todo el proyecto.

Nivel POC: un solo logger por modulo (logging.getLogger(__name__)), todo
a STDERR (default de logging.basicConfig() sin handler explicito -- esto
importa para app/mcp_server.py, Fase 3: en stdio, stdout ES el canal
JSON-RPC del protocolo MCP, cualquier print()/log a stdout lo corrompe).
INFO para progreso normal (ingesta, tool calls), WARNING para archivos
salteados/no soportados, ERROR para fallos que abortaron algo. No hace
falta logging estructurado/JSON a esta escala (un solo proceso local).
"""
```

- [ ] **Step 4: Correr, confirmar que pasa**

Run: `./venv/Scripts/python.exe -m pytest tests/test_mcp_server.py -v`
Expected: PASS (6 tests). Ajustar la aserción de introspección si el Step 1 lo señaló necesario, y volver a correr.

- [ ] **Step 5: Correr la suite completa**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: sin fallos.

- [ ] **Step 6: Commit**

```bash
git add app/mcp_server.py app/logging_conf.py tests/test_mcp_server.py
git commit -m "feat: mcp_server.py -- tool query_events_kb + entry point stdio (Fase 3)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 17: Verificación en vivo del servidor MCP

**Files:** ninguno (solo verificación manual).

- [ ] **Step 1: Confirmar Docker**

Run: `docker ps` — confirmar `neo4j` y `frosty_lalande` arriba (`docker start <nombre>` si no; el servidor de solo-consulta no los necesita para responder, pero conviene probarlo con el stack completo levantado la primera vez).

- [ ] **Step 2: Probar el servidor por stdio directamente**

Run: `./venv/Scripts/python.exe -m app.mcp_server`
Expected: si faltan `ANTHROPIC_API_KEY`/`VOYAGE_API_KEY`, imprime el mensaje a stderr y sale con código 1. Si están, el proceso queda esperando en stdio (Ctrl+C para salir) — confirma que no crashea al arrancar.

- [ ] **Step 3: Conectar desde Claude Desktop o Claude Code**

Agregar a la config de MCP servers (`claude_desktop_config.json` o equivalente):

```json
{
  "mcpServers": {
    "events-rag": {
      "command": "C:\\Users\\Laure\\Desktop\\RAG\\events-rag-poc\\venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp_server"]
    }
  }
}
```

Reiniciar el cliente MCP, confirmar que la tool `query_events_kb` aparece, hacerle una pregunta real, y verificar que:
1. Responde con texto + fuentes.
2. Si la pregunta generó un gráfico, el cliente lo muestra (imagen embebida).
3. La consulta queda registrada en `data/queries/` (visible también desde el sidebar de Streamlit).

- [ ] **Step 4: Nada que commitear** (la config del cliente MCP vive fuera del repo).

### ⏸️ Checkpoint Fase 3

Correr `./venv/Scripts/python.exe -m pytest -q`, confirmar 0 failed, y **avisar al usuario** con el resultado (+ el resultado de la Task 17) antes de arrancar la Fase 4.

---

## Fase 4 — Modelo de extracción del grafo

### Task 18: `EXTRACTION_MODEL` separado de `CLAUDE_MODEL`

**Files:**
- Modify: `app/config.py`, `app/graph/extraction.py`
- Test: `tests/test_extraction_model.py` (nuevo)

**Interfaces:**
- Produces: `app.config.EXTRACTION_MODEL: str` (default `"claude-haiku-4-5-20251001"`). `app.graph.extraction.extract_from_document` pasa a llamar con `EXTRACTION_MODEL` en vez de `CLAUDE_MODEL`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_extraction_model.py`:

```python
"""Fase 4: la extraccion de entidades del grafo usa EXTRACTION_MODEL, no
CLAUDE_MODEL (el que usa el agente) -- separados porque
extract_from_document es una llamada con structured outputs, sin
programmatic tool calling ni code execution, asi que corre perfecto en
un modelo mas barato (ver spec, Fase 4 -- investigacion con fuentes
oficiales ya cerrada, esta es la unica accion de codigo que quedaba)."""

from app.config import CLAUDE_MODEL
from app.graph import extraction


class _FakeResponse:
    def __init__(self, parsed_output):
        self.parsed_output = parsed_output


class _FakeMessages:
    def __init__(self):
        self.captured_kwargs = {}

    def parse(self, **kwargs):
        self.captured_kwargs = kwargs
        return _FakeResponse(extraction.ExtractionResult(entities=[], relationships=[]))


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def test_extract_from_document_uses_extraction_model_not_claude_model(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(extraction, "_get_client", lambda: fake_client)
    monkeypatch.setattr(extraction, "EXTRACTION_MODEL", "claude-haiku-4-5-20251001")

    extraction.extract_from_document("texto del documento", "archivo.pdf")

    assert fake_client.messages.captured_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert fake_client.messages.captured_kwargs["model"] != CLAUDE_MODEL
```

- [ ] **Step 2: Correr, confirmar que falla**

Run: `./venv/Scripts/python.exe -m pytest tests/test_extraction_model.py -v`
Expected: FAIL — `extraction.EXTRACTION_MODEL` no existe (`AttributeError` al hacer `monkeypatch.setattr`), o (si se corrigiera el import antes que el uso) el `assert ... != CLAUDE_MODEL` falla porque todavía usa `CLAUDE_MODEL`.

- [ ] **Step 3: Implementación mínima**

En `app/config.py`, reemplazar la línea de `CLAUDE_MODEL` por:

```python
# --- Modelos ---
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")               # agente (necesita programmatic tool calling)
# Sonnet 5 es el modelo mas barato que soporta programmatic tool calling
# (ver spec Fase 4, fuentes oficiales) -- por eso el agente no cambia.
# La extraccion de entidades del grafo (app/graph/extraction.py) es una
# llamada por documento con structured outputs -- NO usa PTC ni code
# execution -- asi que corre perfecto en un modelo mas barato.
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "claude-haiku-4-5-20251001")  # extraccion del grafo
```

En `app/graph/extraction.py`, cambiar el import y el uso:

```python
from app.config import ANTHROPIC_API_KEY, EXTRACTION_MODEL
```

```python
    response = client.messages.parse(
        model=EXTRACTION_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Documento: {file_name}\n\n{document_text}"}],
        output_format=ExtractionResult,
    )
```

- [ ] **Step 4: Correr, confirmar que pasa**

Run: `./venv/Scripts/python.exe -m pytest tests/test_extraction_model.py -v`
Expected: PASS.

- [ ] **Step 5: Correr la suite completa**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: sin fallos (incluye `tests/test_graph_ingest.py`, que fakea `extraction.extract_from_document` entero y no depende del modelo usado internamente).

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/graph/extraction.py tests/test_extraction_model.py
git commit -m "feat: separar EXTRACTION_MODEL (Haiku 4.5) de CLAUDE_MODEL (Fase 4)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Verificación de extremo a extremo (opcional, con llamadas reales)**

Correr una ingesta completa (resync desde el sidebar de Streamlit) y comparar `graph_stats()` (entidades/relaciones) contra el estado actual del grafo — deberían ser equivalentes en cantidad y calidad, solo con el modelo de extracción más barato. `scripts/eval_retrieval.py` sigue en verde (no toca Claude, mide retrieval).

### ⏸️ Checkpoint Fase 4 — Plan completo

Correr `./venv/Scripts/python.exe -m pytest -q` una última vez, confirmar 0 failed, y avisar al usuario que las 4 fases están cerradas. No pushear a `origin` sin que lo pida.

---

## Self-Review (hecho al escribir este plan)

**Cobertura de la spec:** las 4 fases del documento de diseño tienen tarea(s) 1:1 — Fase 1 → Tasks 1-6, Fase 2 → Tasks 7-11, Fase 3 → Tasks 12-17, Fase 4 → Task 18. Los 11+8+3+11+3+6+2+1 = 45 tests nombrados en la spec están todos con código real en alguna task (11 en `test_queries.py`, 6 en `test_inbox_prompt.py`, 8 en `test_inbox_ask.py`, 3 en `test_config_require_env.py`, 6 en `test_mcp_server.py`, 2 en `test_inbox_lock.py`, 1 en `test_extraction_model.py`, más 2 de `test_config_env_anchor.py` no nombrados en la spec pero necesarios para el fix de `load_dotenv` que la spec sí pide en §1.3). Las decisiones "NO hacer" de la spec (§"Lo que NO hacer") se respetan: sin migración de `data/conversations/`, sin `@` autocomplete real, sin `references` en la tool MCP, sin refactor C de reentrancia, sin lock en `run_turn()`/`tools.py`, sin tests de `streamlit_app.py` con `AppTest`, sin HTTP, sin tocar `run_turn`/`run_turn_streaming`, sin cambiar el modelo del agente.

**Placeholders:** ninguno — cada step de código tiene la implementación completa, cada test tiene su cuerpo real.

**Consistencia de tipos/firmas:** `save_query(query_id, question, result, references=None, queries_dir=QUERIES_DIR) -> dict` (Task 2) es la firma que usa `inbox.ask()`/`ask_streaming()` (Tasks 9-10) sin variar. `build_prompt(question, citations)` (Task 8) es la firma que usa `_citations_for` + `ask()` (Task 9) sin variar. `claude_agent.run_turn`/`run_turn_streaming` nunca cambian de firma (contrato ya existente, intacto en todo el plan). `_to_mcp_content(record)` (Task 15) es la firma que usa `query_events_kb` (Task 16).
