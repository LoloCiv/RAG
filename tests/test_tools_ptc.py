"""Programmatic tool calling (palanca 2): get_source_table tiene que poder
llamarse tanto directo (como hoy) como desde el codigo que escribe Claude
dentro de code_execution. Estos tests verifican la DECLARACION de las
tools, no una llamada real a Claude."""

from app.agent.tools import CODE_EXECUTION_TOOL, get_source_table


def test_code_execution_tool_usa_la_variante_programatica():
    # Se usa code_execution_20260120 por decision de diseno explicita del
    # sub-proyecto 2 (ver spec), no porque 20260521 carezca de soporte para
    # allowed_callers -- el SDK instalado (anthropic 1.2.0) acepta
    # allowed_callers en ambas variantes.
    assert CODE_EXECUTION_TOOL == {"type": "code_execution_20260120", "name": "code_execution"}


def test_get_source_table_es_invocable_desde_code_execution():
    schema = get_source_table.to_dict()
    assert "code_execution_20260120" in schema.get("allowed_callers", [])
