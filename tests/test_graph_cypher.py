"""Sanitizacion de labels/tipos de relacion para Cypher.

Cypher no permite parametrizar labels ni tipos de relacion, asi que el
`type`/`relation_type` libre que devuelve Claude se interpola directo en la
query. Estos tests son la red de seguridad de esa interpolacion: si el
resultado solo puede contener \\w, no hay forma de que un documento hostil
cierre el backtick y meta Cypher propio.
"""

import re

import pytest

from app.graph.cypher import sanitize_label, sanitize_rel_type


def test_espacios_se_vuelven_guion_bajo():
    assert sanitize_label("Proveedor de catering") == "Proveedor_de_catering"


def test_puntuacion_se_colapsa_a_un_solo_guion_bajo():
    assert sanitize_label("Evento / Casamiento") == "Evento_casamiento"


def test_no_deja_guion_bajo_al_principio_ni_al_final():
    assert sanitize_label("  Proveedor!  ") == "Proveedor"


def test_nunca_empieza_con_digito():
    # Un label de Cypher no puede arrancar con un digito.
    resultado = sanitize_label("2024 Eventos")
    assert not resultado[0].isdigit()
    assert resultado == "_2024_eventos"


def test_string_vacio_cae_al_default():
    assert sanitize_label("") == "Entity"
    assert sanitize_label("   ") == "Entity"
    assert sanitize_label("!!!") == "Entity"


def test_saca_tildes():
    # Un label no puede depender de si Claude escribio "Locacion" o
    # "Locación": en Neo4j serian dos labels distintos para el mismo tipo.
    assert sanitize_label("Locación") == "Locacion"
    assert sanitize_label("Diseño") == "Diseno"


def test_el_case_de_entrada_no_cambia_el_label():
    # LA razon de ser de la normalizacion: Claude escribe el mismo type con
    # distinto case segun el documento, y sin esto quedan labels paralelos
    # ('Proveedor_de_Catering' y 'Proveedor_de_catering') para lo mismo.
    esperado = "Proveedor_de_catering"
    assert sanitize_label("Proveedor de Catering") == esperado
    assert sanitize_label("proveedor de catering") == esperado
    assert sanitize_label("PROVEEDOR DE CATERING") == esperado
    assert sanitize_label("Proveedor De Catering") == esperado


def test_arranca_en_mayuscula_como_manda_la_convencion_de_neo4j():
    assert sanitize_label("proveedor") == "Proveedor"


def test_trunca_a_100_caracteres():
    assert len(sanitize_label("A" * 500)) == 100


@pytest.mark.parametrize(
    "hostil",
    [
        "Proveedor`; DROP DATABASE neo4j; //",
        "Entity` {name: 'x'})-[:PWN]->(:Admin) //",
        'Foo" OR 1=1',
        "Foo) DETACH DELETE n //",
    ],
)
def test_intento_de_inyeccion_queda_solo_en_caracteres_de_palabra(hostil):
    resultado = sanitize_label(hostil)
    assert re.fullmatch(r"\w+", resultado, flags=re.UNICODE), resultado
    for prohibido in ("`", '"', "'", "(", ")", "{", "}", ";", "/", "-", "[", "]"):
        assert prohibido not in resultado


def test_rel_type_va_en_mayusculas():
    assert sanitize_rel_type("contratado para") == "CONTRATADO_PARA"


def test_rel_type_vacio_cae_al_default():
    assert sanitize_rel_type("") == "RELACIONADO_CON"


def test_rel_type_tambien_saca_tildes():
    # Sin esto conviven :CONTRATADO_PARA_LOCACIÓN y :CONTRATADO_PARA_LOCACION.
    assert sanitize_rel_type("ubicado en locación") == "UBICADO_EN_LOCACION"


def test_rel_type_tambien_bloquea_inyeccion():
    resultado = sanitize_rel_type("REL`]->() DETACH DELETE n //")
    assert re.fullmatch(r"\w+", resultado, flags=re.UNICODE), resultado
