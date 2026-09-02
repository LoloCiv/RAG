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
