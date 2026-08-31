"""Funciones puras de scoring del arnes de evaluacion de retrieval
(scripts/eval_retrieval.py): recall_at_k, reciprocal_rank,
resolve_expected_source_ids, format_report. Mismo criterio que
format_comparison en scripts/benchmark_agent.py (tests/test_benchmark_format.py):
se testean con datos armados a mano, sin Qdrant/Voyage vivos. evaluate_question()
y main() SI llaman a servicios reales -- no se testean aca."""

import pytest

from scripts.eval_retrieval import (
    format_report,
    reciprocal_rank,
    recall_at_k,
    resolve_expected_source_ids,
)


# --- recall_at_k ---

def test_recall_1_si_todos_los_archivos_esperados_aparecen():
    expected = [{"a1"}, {"b1"}]
    retrieved = ["x", "a1", "y", "b1"]
    assert recall_at_k(retrieved, expected) == 1.0


def test_recall_0_si_ninguno_aparece():
    expected = [{"a1"}, {"b1"}]
    retrieved = ["x", "y", "z"]
    assert recall_at_k(retrieved, expected) == 0.0


def test_recall_parcial():
    expected = [{"a1"}, {"b1"}]
    retrieved = ["a1", "z"]
    assert recall_at_k(retrieved, expected) == 0.5


def test_recall_1_cuando_no_hay_nada_esperado():
    # Nada que encontrar => no hay nada que falle.
    assert recall_at_k(["x", "y"], []) == 1.0


def test_recall_cuenta_un_archivo_con_multiples_source_ids_como_un_solo_hit():
    # Una planilla con 2 tabs = 2 source_ids para el MISMO archivo -- que
    # aparezca cualquiera de los dos cuenta como encontrado ese archivo.
    expected = [{"gdrive:x:TabA", "gdrive:x:TabB"}]
    retrieved = ["gdrive:x:TabB"]
    assert recall_at_k(retrieved, expected) == 1.0


# --- reciprocal_rank ---

def test_rr_1_si_el_primer_resultado_es_esperado():
    expected = [{"a1"}]
    assert reciprocal_rank(["a1", "x", "y"], expected) == 1.0


def test_rr_un_tercio_si_aparece_en_la_posicion_3():
    expected = [{"a1"}]
    assert reciprocal_rank(["x", "y", "a1"], expected) == pytest.approx(1 / 3)


def test_rr_0_si_no_aparece():
    expected = [{"a1"}]
    assert reciprocal_rank(["x", "y", "z"], expected) == 0.0


def test_rr_toma_el_primer_match_de_cualquier_archivo_esperado():
    # Dos archivos esperados (pregunta multi-file); el primero en aparecer
    # en el ranking (no necesariamente el primero de la lista de esperados)
    # es el que define el rank.
    expected = [{"a1"}, {"b1"}]
    retrieved = ["x", "b1", "a1"]
    assert reciprocal_rank(retrieved, expected) == pytest.approx(1 / 2)


def test_rr_0_cuando_no_hay_nada_esperado():
    assert reciprocal_rank(["x", "y"], []) == 0.0


# --- resolve_expected_source_ids ---

def _manifest():
    return {
        "drive_id_1": {"file_name": "Archivo_Uno", "source_ids": ["gdrive:1"]},
        "drive_id_2": {
            "file_name": "Planilla.xlsx",
            "source_ids": ["gdrive:2:TabA", "gdrive:2:TabB"],
        },
    }


def test_resuelve_archivo_simple_a_su_source_id():
    result = resolve_expected_source_ids(["Archivo_Uno"], _manifest())
    assert result == [{"gdrive:1"}]


def test_resuelve_planilla_multi_tab_a_todos_sus_source_ids():
    result = resolve_expected_source_ids(["Planilla.xlsx"], _manifest())
    assert result == [{"gdrive:2:TabA", "gdrive:2:TabB"}]


def test_archivo_esperado_que_no_esta_en_el_manifest_tira_keyerror():
    # Mejor fallar ruidoso que medir en silencio contra un golden set
    # desactualizado (archivo renombrado o nunca ingerido).
    with pytest.raises(KeyError):
        resolve_expected_source_ids(["No_Existe"], _manifest())


# --- format_report ---

def test_format_report_incluye_cada_pregunta_y_el_promedio():
    results = [
        {"id": "q1", "recall": 1.0, "rr": 1.0},
        {"id": "q2", "recall": 0.0, "rr": 0.0},
    ]
    texto = format_report(results)
    assert "q1" in texto
    assert "q2" in texto
    assert "0.50" in texto  # promedio de recall y de rr, ambos 0.5


def test_format_report_no_rompe_con_lista_vacia():
    texto = format_report([])
    assert isinstance(texto, str)
    assert "0.00" in texto
