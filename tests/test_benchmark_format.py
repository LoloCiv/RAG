"""format_comparison es pura: se testea con dicts armados a mano, sin
Qdrant/Neo4j/Claude vivos. run_question() en cambio SI llama al agente real
-- no se testea automaticamente, se corre a mano entre cada palanca (ver
plan de implementacion, Task 1 en adelante)."""

from scripts.benchmark_agent import BASELINE, format_comparison


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


def test_dict_sin_las_claves_nuevas_no_rompe_el_formato():
    """Los 5-key dicts de los tests viejos (y de cualquier medicion previa a
    esta correccion) tienen que seguir formateando sin explotar -- format_comparison
    debe usar .get(key, 0) y no indexado directo para total_in/cache_creation/tokens_out."""
    baseline = {"elapsed_s": 1.0, "round_trips": 1, "tool_calls": 0, "tokens_in": 100, "cache_read": 0}
    current = {"elapsed_s": 1.0, "round_trips": 1, "tool_calls": 0, "tokens_in": 100, "cache_read": 0}

    texto = format_comparison("sin claves nuevas", baseline, current)

    assert "sin claves nuevas" in texto


def test_total_in_se_calcula_contra_el_total_no_contra_tokens_in_crudo():
    """tokens_in solo son los tokens NO cacheados: comparar tokens_in a secas
    contra el baseline (medido sin cache) da un -100% falso. total_in
    (tokens_in + cache_read + cache_creation) es la columna comparable."""
    baseline = {
        "elapsed_s": 87.8,
        "round_trips": 3,
        "tool_calls": 4,
        "tokens_in": 43783,
        "cache_read": 0,
        "cache_creation": 0,
        "total_in": 43783,
        "tokens_out": 0,
    }
    current = {
        "elapsed_s": 20.0,
        "round_trips": 3,
        "tool_calls": 4,
        "tokens_in": 8,
        "cache_read": 31848,
        "cache_creation": 5000,
        "total_in": 36856,
        "tokens_out": 500,
    }

    texto = format_comparison("proveedor", baseline, current)
    total_in_line = next(l for l in texto.splitlines() if l.startswith("total_in"))

    assert "36,856" in total_in_line or "36856" in total_in_line
    # el total real bajo ~16%, no 100%: la fila total_in (la columna
    # comparable manzana-a-manzana) no puede reportar el -100% enganoso que
    # sale de comparar tokens_in (solo lo NO cacheado) contra el baseline.
    assert "-16" in total_in_line
    assert "-100%" not in total_in_line


def test_baseline_es_internamente_consistente():
    """El baseline se midio SIN ninguna palanca de cache -- por lo tanto para
    cada entrada total_in tiene que ser igual a tokens_in, y no hubo ni cache
    hits ni cache writes."""
    for label, entry in BASELINE.items():
        assert entry["total_in"] == entry["tokens_in"], label
        assert entry["cache_read"] == 0, label
        assert entry["cache_creation"] == 0, label
