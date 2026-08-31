"""run_turn_streaming() (Fase 3): funcion hermana de run_turn() que
devuelve un generador de eventos incrementales en vez de esperar al
mensaje final -- text_delta para streaming de texto, tool_start para
indicacion de progreso durante tool calls, y SIEMPRE un evento final con
el mismo shape que devuelve run_turn().

Reemplaza Qdrant/Neo4j/Claude reales con fakes -- no gasta ninguna
llamada real (mismo criterio que test_claude_agent_caching.py). El fake
de mas bajo nivel es client.beta.messages.tool_runner(stream=True, ...):
un iterable de "streams" (uno por round-trip), cada uno un context
manager iterable de eventos, con .get_final_message()."""

import app.agent.tools as tools_module
from app.agent import claude_agent


class _FakeDelta:
    def __init__(self, type_, text=None):
        self.type = type_
        self.text = text


class _FakeContentBlock:
    def __init__(self, type_, name=None):
        self.type = type_
        self.name = name


class _FakeEvent:
    def __init__(self, type_, delta=None, content_block=None):
        self.type = type_
        self.delta = delta
        self.content_block = content_block


class _FakeMessageStream:
    def __init__(self, events, final_message):
        self._events = events
        self._final_message = final_message

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._final_message


class _FakeMessage:
    def __init__(self):
        self.content = []


class _FakeStreamingToolRunner:
    def __init__(self, streams, **kwargs):
        self._streams = streams

    def __iter__(self):
        return iter(self._streams)


class _FakeBetaMessages:
    def __init__(self, streams):
        self._streams = streams

    def tool_runner(self, **kwargs):
        assert kwargs.get("stream") is True
        return _FakeStreamingToolRunner(self._streams, **kwargs)


class _FakeBeta:
    def __init__(self, streams):
        self.messages = _FakeBetaMessages(streams)


class _FakeAnthropicClient:
    def __init__(self, *args, **kwargs):
        self.beta = _FakeBeta(_STREAMS_FOR_NEXT_CLIENT[0])


_STREAMS_FOR_NEXT_CLIENT = [[]]  # hack simple: closure via lista mutable, ver _set_streams


def _set_streams(streams):
    _STREAMS_FOR_NEXT_CLIENT[0] = streams


class _FakeQdrantStorage:
    def __init__(self, *args, **kwargs):
        pass


class _FakeGraphStore:
    def __init__(self, *args, **kwargs):
        pass

    def close(self) -> None:
        pass


def _patch_common(monkeypatch, streams):
    _set_streams(streams)
    monkeypatch.setattr(claude_agent.anthropic, "Anthropic", _FakeAnthropicClient)
    monkeypatch.setattr(claude_agent.vector_db, "QdrantStorage", _FakeQdrantStorage)
    monkeypatch.setattr(claude_agent, "Neo4jGraphStore", _FakeGraphStore)
    monkeypatch.setattr(claude_agent, "_init_tools", lambda store, graph_store=None: None)
    tools_module._accumulated_sources = {}


def test_yields_text_delta_events_en_orden(monkeypatch):
    final_message = _FakeMessage()
    stream = _FakeMessageStream(
        events=[
            _FakeEvent("content_block_delta", delta=_FakeDelta("text_delta", "Hola ")),
            _FakeEvent("content_block_delta", delta=_FakeDelta("text_delta", "mundo")),
        ],
        final_message=final_message,
    )
    _patch_common(monkeypatch, [stream])

    events = list(claude_agent.run_turn_streaming([{"role": "user", "content": "hola"}]))

    text_events = [e for e in events if e["type"] == "text_delta"]
    assert [e["text"] for e in text_events] == ["Hola ", "mundo"]


def test_yields_tool_start_con_etiqueta_legible_para_tool_use_y_server_tool_use(monkeypatch):
    final_message = _FakeMessage()
    stream = _FakeMessageStream(
        events=[
            _FakeEvent("content_block_start", content_block=_FakeContentBlock("tool_use", "search_knowledge_base")),
            _FakeEvent("content_block_start", content_block=_FakeContentBlock("server_tool_use", "code_execution")),
            # Un bloque de texto NO es una tool call -- no debe generar tool_start.
            _FakeEvent("content_block_start", content_block=_FakeContentBlock("text")),
        ],
        final_message=final_message,
    )
    _patch_common(monkeypatch, [stream])

    events = list(claude_agent.run_turn_streaming([{"role": "user", "content": "hola"}]))

    tool_events = [e for e in events if e["type"] == "tool_start"]
    assert [e["label"] for e in tool_events] == [
        "🔍 Buscando en la base de conocimiento...",
        "🧮 Calculando...",
    ]


def test_el_ultimo_evento_es_final_con_el_resultado(monkeypatch):
    final_message = _FakeMessage()
    stream = _FakeMessageStream(events=[], final_message=final_message)
    _patch_common(monkeypatch, [stream])

    events = list(claude_agent.run_turn_streaming([{"role": "user", "content": "hola"}]))

    assert events[-1]["type"] == "final"
    assert events[-1]["result"] == {"response_content": [], "answer_text": "", "sources": [], "chart_paths": []}


def test_evento_de_tipo_desconocido_no_rompe(monkeypatch):
    final_message = _FakeMessage()
    stream = _FakeMessageStream(events=[_FakeEvent("message_stop")], final_message=final_message)
    _patch_common(monkeypatch, [stream])

    events = list(claude_agent.run_turn_streaming([{"role": "user", "content": "hola"}]))

    assert events[-1]["type"] == "final"


def test_varios_round_trips_se_concatenan_en_orden(monkeypatch):
    stream1 = _FakeMessageStream(
        events=[_FakeEvent("content_block_delta", delta=_FakeDelta("text_delta", "primero"))],
        final_message=_FakeMessage(),
    )
    stream2 = _FakeMessageStream(
        events=[_FakeEvent("content_block_delta", delta=_FakeDelta("text_delta", "segundo"))],
        final_message=_FakeMessage(),
    )
    _patch_common(monkeypatch, [stream1, stream2])

    events = list(claude_agent.run_turn_streaming([{"role": "user", "content": "hola"}]))

    text_events = [e for e in events if e["type"] == "text_delta"]
    assert [e["text"] for e in text_events] == ["primero", "segundo"]
