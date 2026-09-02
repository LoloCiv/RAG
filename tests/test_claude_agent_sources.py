"""run_turn(): el campo "sources" del resultado (Fase 3 -- "fuentes
legibles" en la UI). Antes era list(set(tools._accumulated_sources))
sobre una list[str] de source_ids crudos -- un set() no garantiza orden
en Python, tirando abajo el orden de relevancia que search_knowledge_base
ya labura en preservar (Fase 2). Ahora tools._accumulated_sources es un
dict ordenado source_id -> file_name (ver app/agent/tools.py), y run_turn
arma sources como [{"source_id", "file_name", "drive_url"}, ...] en ese
mismo orden, sin dedupear de nuevo.

Reemplaza Qdrant/Neo4j/Claude reales con fakes -- no gasta ninguna
llamada real (mismo criterio que test_claude_agent_caching.py)."""

import app.agent.tools as tools_module
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
    def __init__(self, *args, **kwargs):
        # El tool_runner real NUNCA persiste en _params["messages"] el
        # mensaje CON EL QUE TERMINA el turno (ver
        # BaseSyncToolRunner.__run__ en _beta_runner.py -- next_step ==
        # "stop" hace return directo) -- el unico round de este fake es
        # ese mensaje terminal, asi que _params no debe incluirlo.
        self._params = {"messages": [*kwargs.get("messages", [])]}

    def __iter__(self):
        return iter([_FakeMessage()])


class _FakeBetaMessages:
    def tool_runner(self, **kwargs):
        return _FakeToolRunner(**kwargs)


class _FakeBeta:
    def __init__(self):
        self.messages = _FakeBetaMessages()


class _FakeAnthropicClient:
    def __init__(self, *args, **kwargs):
        self.beta = _FakeBeta()


class _FakeQdrantStorage:
    def __init__(self, *args, **kwargs):
        pass


class _FakeGraphStore:
    def __init__(self, *args, **kwargs):
        pass

    def close(self) -> None:
        pass


def _fake_init_tools_con(fixture: dict):
    def _fake(store, graph_store=None):
        tools_module._accumulated_sources = dict(fixture)

    return _fake


def test_sources_incluye_file_name_y_drive_url_en_orden(monkeypatch):
    monkeypatch.setattr(claude_agent.anthropic, "Anthropic", _FakeAnthropicClient)
    monkeypatch.setattr(claude_agent.vector_db, "QdrantStorage", _FakeQdrantStorage)
    monkeypatch.setattr(claude_agent, "Neo4jGraphStore", _FakeGraphStore)
    monkeypatch.setattr(
        claude_agent,
        "_init_tools",
        _fake_init_tools_con({"gdrive:abc123": "contrato.pdf", "gdrive:def456:Presupuesto": "planilla.xlsx"}),
    )

    result = claude_agent.run_turn([{"role": "user", "content": "hola"}])

    assert result["sources"] == [
        {
            "source_id": "gdrive:abc123",
            "file_name": "contrato.pdf",
            "drive_url": "https://drive.google.com/file/d/abc123/view",
        },
        {
            "source_id": "gdrive:def456:Presupuesto",
            "file_name": "planilla.xlsx",
            "drive_url": "https://drive.google.com/file/d/def456/view",
        },
    ]


def test_sin_busquedas_sources_es_lista_vacia(monkeypatch):
    monkeypatch.setattr(claude_agent.anthropic, "Anthropic", _FakeAnthropicClient)
    monkeypatch.setattr(claude_agent.vector_db, "QdrantStorage", _FakeQdrantStorage)
    monkeypatch.setattr(claude_agent, "Neo4jGraphStore", _FakeGraphStore)
    monkeypatch.setattr(claude_agent, "_init_tools", _fake_init_tools_con({}))

    result = claude_agent.run_turn([{"role": "user", "content": "hola"}])

    assert result["sources"] == []
