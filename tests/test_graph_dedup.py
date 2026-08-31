"""Deduplicacion difusa de nombres de entidad.

El caso real que motiva esto: "Catering Buena Mesa" aparece en cinco
documentos distintos de la carpeta de prueba, y Claude no siempre lo escribe
igual (reordenado, con o sin tildes, con typos menores). Sin este paso el
grafo termina con cinco nodos que deberian ser uno solo.
"""

from app.graph.dedup import find_best_match, normalize_name


def test_normalize_saca_tildes():
    assert normalize_name("Catering Buenísimo") == "catering buenisimo"


def test_normalize_baja_a_minusculas():
    assert normalize_name("CATERING Buena Mesa") == "catering buena mesa"


def test_normalize_colapsa_espacios():
    assert normalize_name("  Catering   Buena\tMesa  ") == "catering buena mesa"


def test_encuentra_match_con_palabras_reordenadas():
    # El caso ancla del proyecto.
    candidatos = ["Catering Buena Mesa", "Salon Los Robles"]
    assert find_best_match("Buena Mesa Catering", candidatos) == "Catering Buena Mesa"


def test_encuentra_match_con_typo_menor():
    candidatos = ["Catering Buena Mesa"]
    assert find_best_match("Catering Buena Mesa.", candidatos) == "Catering Buena Mesa"


def test_encuentra_match_ignorando_tildes():
    candidatos = ["Salón Los Robles"]
    assert find_best_match("Salon Los Robles", candidatos) == "Salón Los Robles"


def test_devuelve_el_nombre_original_del_candidato_no_el_normalizado():
    # Lo que se guarda en Neo4j es el nombre tal cual vino, no la forma
    # normalizada que se usa solo para comparar.
    candidatos = ["Salón Los Robles"]
    assert find_best_match("salon los robles", candidatos) == "Salón Los Robles"


def test_entidades_distintas_no_matchean():
    candidatos = ["Catering Buena Mesa", "Salon Los Robles"]
    assert find_best_match("Fotografia Luz y Sombra", candidatos) is None


def test_nombres_parecidos_pero_distintos_no_matchean():
    # "Catering Buena Mesa" vs "Catering Mala Mesa": comparten dos de tres
    # palabras pero son proveedores distintos.
    assert find_best_match("Catering Mala Mesa", ["Catering Buena Mesa"]) is None


def test_sin_candidatos_devuelve_none():
    assert find_best_match("Catering Buena Mesa", []) is None


def test_elige_el_mejor_candidato_no_el_primero_que_pasa_el_umbral():
    candidatos = ["Catering Buena Mesa S.A.", "Catering Buena Mesa"]
    assert find_best_match("Catering Buena Mesa", candidatos) == "Catering Buena Mesa"


def test_threshold_configurable():
    # Con un umbral bajo hasta un match flojo pasa; con uno alto, no.
    candidatos = ["Catering Mala Mesa"]
    assert find_best_match("Catering Buena Mesa", candidatos, threshold=50) == "Catering Mala Mesa"
    assert find_best_match("Catering Buena Mesa", candidatos, threshold=99) is None
