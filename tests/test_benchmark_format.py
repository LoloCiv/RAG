"""format_comparison es pura: se testea con dicts armados a mano, sin
Qdrant/Neo4j/Claude vivos. run_question() en cambio SI llama al agente real
-- no se testea automaticamente, se corre a mano entre cada palanca (ver
plan de implementacion, Task 1 en adelante)."""

from scripts.benchmark_agent import format_comparison


def test_muestra_mejora_como_porcentaje_negativo():
    baseline = {"elapsed_s": 43.3, "round_trips": 3, "tool_calls": 6, "tokens_in": 65499, "cache_read": 0}
    current = {"elapsed_s": 20.0, "round_trips": 3, "tool_calls": 6, "tokens_in": 20000, "cache_read": 40000}

    texto = format_comparison("planificacion", baseline, current)

    assert "planificacion" in texto
    assert "65,499" in texto or "65499" in texto
    assert "20,000" in texto or "20000" in texto
    # tokens_in bajo un 69%: tiene que quedar visible como mejora
    assert "-69" in texto or "-70" in texto or "69%" in texto or "70%" in texto


def test_cache_read_en_cero_no_rompe_el_formato():
    baseline = {"elapsed_s": 1.0, "round_trips": 1, "tool_calls": 0, "tokens_in": 100, "cache_read": 0}
    current = {"elapsed_s": 1.0, "round_trips": 1, "tool_calls": 0, "tokens_in": 100, "cache_read": 0}

    texto = format_comparison("sin cambios", baseline, current)

    assert "sin cambios" in texto


def test_empeora_se_marca_como_positivo_no_como_mejora():
    baseline = {"elapsed_s": 10.0, "round_trips": 1, "tool_calls": 1, "tokens_in": 1000, "cache_read": 0}
    current = {"elapsed_s": 15.0, "round_trips": 1, "tool_calls": 1, "tokens_in": 1500, "cache_read": 0}

    texto = format_comparison("peor", baseline, current)

    assert "+50%" in texto or "+50.0%" in texto
