"""Los modos de respuesta priorizan rapidez sin relajar citas ni herramientas."""

from app.agent.claude_agent import _tool_runner_kwargs


def test_fast_mode_reduces_token_budget_and_adds_focus_instruction():
    kwargs = _tool_runner_kwargs([{"role": "user", "content": "consulta"}], response_mode="fast")

    assert kwargs["max_tokens"] == 4096
    assert "MODO RÁPIDO" in kwargs["system"]
    assert kwargs["thinking"] == {"type": "adaptive"}


def test_deep_mode_preserves_current_budget():
    kwargs = _tool_runner_kwargs([{"role": "user", "content": "consulta"}], response_mode="deep")

    assert kwargs["max_tokens"] == 16000
    assert "MODO RÁPIDO" not in kwargs["system"]
