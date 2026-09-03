import threading
import time

from app.agent import inbox

_shared = {}


def test_two_concurrent_asks_do_not_clobber_each_others_sources(tmp_path, monkeypatch):
    expected = {"A": [{"source_id": "A"}], "B": [{"source_id": "B"}]}
    def fake(history):
        question = history[0]["content"]
        _shared["sources"] = expected[question]
        time.sleep(0.05)
        return {"answer_text": question, "sources": _shared["sources"], "chart_paths": [], "new_messages": []}
    monkeypatch.setattr(inbox.claude_agent, "run_turn", fake)
    results = {}
    def run(question):
        results[question] = inbox.ask(question, queries_dir=tmp_path)
    first = threading.Thread(target=run, args=("A",))
    second = threading.Thread(target=run, args=("B",))
    first.start(); time.sleep(0.01); second.start(); first.join(); second.join()
    assert results["A"]["sources"] == expected["A"]
    assert results["B"]["sources"] == expected["B"]


def test_lock_releases_if_the_agent_raises(tmp_path, monkeypatch):
    def fail(history):
        raise RuntimeError("boom")
    monkeypatch.setattr(inbox.claude_agent, "run_turn", fail)
    try:
        inbox.ask("pregunta", queries_dir=tmp_path)
    except RuntimeError:
        pass
    acquired = inbox._TURN_LOCK.acquire(timeout=2)
    assert acquired
    inbox._TURN_LOCK.release()
