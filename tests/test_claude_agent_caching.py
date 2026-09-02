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
        self._params = {"messages": [*kwargs.get("messages", []), {"role": "assistant", "content": []}]}

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
