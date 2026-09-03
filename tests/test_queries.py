"""El log del buzon se prueba solo contra directorios temporales."""

import json

from anthropic.types.beta import BetaTextBlock

from app.agent.queries import list_queries, load_query, new_query_id, save_query, set_feedback


def _fake_result(**overrides):
    result = {"answer_text": "", "sources": [], "chart_paths": [], "new_messages": []}
    result.update(overrides)
    return result


def test_new_query_id_is_unique():
    assert new_query_id() != new_query_id()


def test_save_query_returns_the_full_record_shape(tmp_path):
    query_id = new_query_id()
    result = _fake_result(answer_text="respuesta", sources=[{"file_name": "x.pdf"}], chart_paths=["chart.png"], new_messages=[{"role": "assistant", "content": "ok"}])
    record = save_query(query_id, "Cuanto gastamos?", result, queries_dir=tmp_path)
    assert set(record) == {"id", "created_at", "title", "question", "references", "answer_text", "sources", "chart_paths", "feedback", "raw_messages"}
    assert record["id"] == query_id
    assert record["question"] == "Cuanto gastamos?"
    assert record["answer_text"] == "respuesta"
    assert record["sources"] == result["sources"]
    assert record["chart_paths"] == ["chart.png"]
    assert record["feedback"] is None
    assert record["references"] == []
    assert json.loads((tmp_path / f"{query_id}.json").read_text(encoding="utf-8")) == record


def test_save_query_flattens_pydantic_blocks(tmp_path):
    query_id = new_query_id()
    result = _fake_result(new_messages=[{"role": "assistant", "content": [BetaTextBlock(type="text", text="respuesta")]}])
    save_query(query_id, "pregunta", result, queries_dir=tmp_path)
    saved = json.loads((tmp_path / f"{query_id}.json").read_text(encoding="utf-8"))
    assert saved["raw_messages"][0]["content"] == [{"type": "text", "text": "respuesta", "citations": None}]


def test_load_query_missing_returns_none(tmp_path):
    assert load_query("missing", queries_dir=tmp_path) is None


def test_load_query_corrupt_returns_none(tmp_path):
    (tmp_path / "bad.json").write_text("{bad", encoding="utf-8")
    assert load_query("bad", queries_dir=tmp_path) is None


def test_title_is_derived_from_question_and_truncated_to_60(tmp_path):
    record = save_query(new_query_id(), "x" * 100, _fake_result(), queries_dir=tmp_path)
    assert record["title"] == "x" * 60 + "…"


def test_list_queries_orders_by_created_at_descending(tmp_path):
    old_id, new_id = new_query_id(), new_query_id()
    save_query(old_id, "vieja", _fake_result(), queries_dir=tmp_path)
    save_query(new_id, "nueva", _fake_result(), queries_dir=tmp_path)
    data = load_query(new_id, queries_dir=tmp_path)
    data["created_at"] = "2099-01-01T00:00:00+00:00"
    (tmp_path / f"{new_id}.json").write_text(json.dumps(data), encoding="utf-8")
    assert [item["id"] for item in list_queries(tmp_path)] == [new_id, old_id]


def test_list_queries_skips_corrupt_files(tmp_path):
    query_id = new_query_id()
    save_query(query_id, "ok", _fake_result(), queries_dir=tmp_path)
    (tmp_path / "bad.json").write_text("{bad", encoding="utf-8")
    assert [item["id"] for item in list_queries(tmp_path)] == [query_id]


def test_list_queries_returns_only_metadata(tmp_path):
    save_query(new_query_id(), "pregunta", _fake_result(answer_text="secreto"), queries_dir=tmp_path)
    assert set(list_queries(tmp_path)[0]) == {"id", "title", "created_at"}


def test_set_feedback_does_not_clobber_the_rest_of_the_record(tmp_path):
    query_id = new_query_id()
    original = save_query(query_id, "pregunta", _fake_result(answer_text="respuesta"), references=["ref"], queries_dir=tmp_path)
    set_feedback(query_id, "up", queries_dir=tmp_path)
    loaded = load_query(query_id, queries_dir=tmp_path)
    assert loaded["feedback"] == "up"
    assert {**loaded, "feedback": None} == original


def test_references_defaults_to_empty_list(tmp_path):
    assert save_query(new_query_id(), "pregunta", _fake_result(), queries_dir=tmp_path)["references"] == []
