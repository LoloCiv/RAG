import pytest

from app.agent import inbox
from app.agent.queries import list_queries, load_query, new_query_id, save_query


def _result(answer_text="respuesta", sources=None):
    return {"answer_text": answer_text, "sources": sources or [], "chart_paths": [], "new_messages": []}


def test_missing_reference_is_skipped_without_breaking(tmp_path, monkeypatch):
    cited = save_query(new_query_id(), "vieja", _result("anterior"), queries_dir=tmp_path)
    captured = {}
    def fake(history):
        captured["history"] = history
        return _result()
    monkeypatch.setattr(inbox.claude_agent, "run_turn", fake)
    inbox.ask("nueva", [cited["id"], "missing"], tmp_path)
    assert "vieja" in captured["history"][0]["content"]


def test_all_missing_references_degrades_to_raw_question(tmp_path, monkeypatch):
    captured = {}
    def fake(history):
        captured["history"] = history
        return _result()
    monkeypatch.setattr(inbox.claude_agent, "run_turn", fake)
    inbox.ask("nueva", ["missing"], tmp_path)
    assert captured["history"][0]["content"] == "nueva"


def test_ask_sends_a_single_user_message_history(tmp_path, monkeypatch):
    captured = {}
    def fake(history):
        captured["history"] = history
        return _result()
    monkeypatch.setattr(inbox.claude_agent, "run_turn", fake)
    inbox.ask("pregunta", queries_dir=tmp_path)
    assert captured["history"] == [{"role": "user", "content": "pregunta"}]


def test_ask_saves_the_record_and_returns_the_id(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox.claude_agent, "run_turn", lambda history: _result("ok"))
    record = inbox.ask("pregunta", queries_dir=tmp_path)
    assert load_query(record["id"], tmp_path)["answer_text"] == "ok"


def test_ask_persists_references_in_the_record(tmp_path, monkeypatch):
    cited = save_query(new_query_id(), "vieja", _result(), queries_dir=tmp_path)
    monkeypatch.setattr(inbox.claude_agent, "run_turn", lambda history: _result())
    assert inbox.ask("nueva", [cited["id"]], tmp_path)["references"] == [cited["id"]]


def test_ask_saves_nothing_if_the_agent_fails(tmp_path, monkeypatch):
    def fail(history):
        raise RuntimeError("boom")
    monkeypatch.setattr(inbox.claude_agent, "run_turn", fail)
    with pytest.raises(RuntimeError):
        inbox.ask("pregunta", queries_dir=tmp_path)
    assert list_queries(tmp_path) == []


def test_ask_streaming_forwards_text_delta_and_tool_start_as_is(tmp_path, monkeypatch):
    def fake(history):
        yield {"type": "text_delta", "text": "hola"}
        yield {"type": "tool_start", "label": "buscando"}
        yield {"type": "final", "result": _result("hola")}
    monkeypatch.setattr(inbox.claude_agent, "run_turn_streaming", fake)
    events = list(inbox.ask_streaming("pregunta", queries_dir=tmp_path))
    assert events[:2] == [{"type": "text_delta", "text": "hola"}, {"type": "tool_start", "label": "buscando"}]


def test_ask_streaming_last_event_carries_the_saved_record(tmp_path, monkeypatch):
    def fake(history):
        yield {"type": "final", "result": _result("ok")}
    monkeypatch.setattr(inbox.claude_agent, "run_turn_streaming", fake)
    last = list(inbox.ask_streaming("pregunta", queries_dir=tmp_path))[-1]
    assert last["type"] == "final"
    assert load_query(last["record"]["id"], tmp_path)["answer_text"] == "ok"
