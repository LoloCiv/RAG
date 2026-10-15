from app.agent.inbox import build_prompt
from app.config import CITATION_MAX_CHARS


def _citation(**overrides):
    value = {"id": "ab12", "question": "pregunta vieja", "answer_text": "respuesta vieja"}
    value.update(overrides)
    return value


def test_no_references_prompt_is_the_raw_question():
    assert build_prompt("pregunta", []) == "pregunta"


def test_one_citation_includes_question_and_answer_delimited():
    prompt = build_prompt("actual", [_citation()])
    assert '<query id="ab12">' in prompt
    assert "<question>pregunta vieja</question>" in prompt
    assert "<answer>respuesta vieja</answer>" in prompt
    assert "<current_question>\nactual\n</current_question>" in prompt


def test_citation_does_not_include_raw_messages_or_sources():
    cited = _citation(raw_messages=["RAW_SECRET"], sources=["SOURCE_SECRET"], chart_paths=["CHART_SECRET"])
    prompt = build_prompt("actual", [cited])
    assert "RAW_SECRET" not in prompt and "SOURCE_SECRET" not in prompt and "CHART_SECRET" not in prompt


def test_cited_answer_truncates_to_citation_max_chars_with_marker():
    answer = "x" * (CITATION_MAX_CHARS + 1)
    prompt = build_prompt("actual", [_citation(answer_text=answer)])
    assert "… [respuesta recortada]" in prompt
    assert answer not in prompt


def test_multiple_citations_go_in_the_requested_order():
    prompt = build_prompt("actual", [_citation(id="first"), _citation(id="second")])
    assert prompt.index('id="first"') < prompt.index('id="second"')


def test_prompt_marks_citations_as_reference_not_instructions():
    prompt = build_prompt("actual", [_citation()])
    assert "REFERENCIA" in prompt and "instrucciones nuevas" in prompt
