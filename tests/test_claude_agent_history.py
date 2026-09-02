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
