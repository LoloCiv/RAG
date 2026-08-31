"""_graph_context_for: la logica de enriquecer una busqueda con el grafo,
aislada de search_knowledge_base para poder testearla con un graph_store
falso -- sin Neo4j real, y verificando en particular que un fallo del grafo
NUNCA rompe la busqueda semantica (search_knowledge_base tiene que seguir
funcionando aunque Neo4j este caido)."""

import json

import pytest

import app.agent.tools as tools_module
from app.agent.tools import _graph_context_for, _init_tools, search_knowledge_base


@pytest.fixture(autouse=True)
def _reset_mapa_anchors_shown():
    """_graph_context_for ahora dedupea anclas ya mostradas EN EL MISMO
    TURNO via el estado de modulo _mapa_anchors_shown. Los tests de este
    archivo llaman _graph_context_for directo (sin pasar por _init_tools,
    que es lo que resetea ese estado en produccion) -- sin este reset,
    un test que corre despues de otro heredaria anclas "ya mostradas" que
    no tienen nada que ver con el, y el orden de ejecucion de pytest
    dejaria de ser irrelevante."""
    tools_module._mapa_anchors_shown = set()
    yield


class _FakeGraphStore:
    def __init__(self, anchors=None, edges=None, raise_on="none"):
        self._anchors = anchors or []
        self._edges = edges or []
        self._raise_on = raise_on

    def anchors_by_source_ids(self, source_ids, limit):
        if self._raise_on == "anchors":
            raise ConnectionError("Neo4j se cayo")
        return self._anchors

    def neighborhood(self, norm_names, limit):
        if self._raise_on == "neighborhood":
            raise ConnectionError("Neo4j se cayo")
        return self._edges


def test_graph_store_none_devuelve_vacio():
    assert _graph_context_for(None, ["gdrive:abc"]) == ""


def test_sin_source_ids_devuelve_vacio():
    store = _FakeGraphStore(anchors=[{"name": "X", "norm_name": "x", "types": [], "doc_count": 1}])
    assert _graph_context_for(store, []) == ""


def test_sin_anclas_encontradas_devuelve_vacio():
    store = _FakeGraphStore(anchors=[])
    assert _graph_context_for(store, ["gdrive:abc"]) == ""


def test_con_anclas_y_aristas_arma_el_mapa():
    store = _FakeGraphStore(
        anchors=[{"name": "Catering Buena Mesa", "norm_name": "catering buena mesa", "types": ["Proveedor"], "doc_count": 6}],
        edges=[{"source": "Catering Buena Mesa", "rel_type": "CONTRATADO_PARA", "target": "Casamiento Perez-Gomez", "source_ids": ["gdrive:abc"]}],
    )

    resultado = _graph_context_for(store, ["gdrive:abc"])

    assert "Catering Buena Mesa" in resultado
    assert "CONTRATADO_PARA" in resultado


def test_fallo_al_buscar_anclas_no_rompe_y_devuelve_vacio():
    store = _FakeGraphStore(raise_on="anchors")
    assert _graph_context_for(store, ["gdrive:abc"]) == ""


def test_fallo_al_buscar_vecindario_no_rompe_y_devuelve_vacio():
    store = _FakeGraphStore(
        anchors=[{"name": "X", "norm_name": "x", "types": [], "doc_count": 1}],
        raise_on="neighborhood",
    )
    assert _graph_context_for(store, ["gdrive:abc"]) == ""


def test_no_repite_anclas_ya_mostradas_en_el_mismo_turno():
    # Cuando el mismo turno dispara 2+ search_knowledge_base en paralelo
    # sobre entidades solapadas, la segunda llamada no debe repetir el mapa
    # de la primera -- sin ganancia de informacion, puro gasto de tokens.
    store = _FakeGraphStore(
        anchors=[{"name": "Catering Buena Mesa", "norm_name": "catering buena mesa", "types": ["Proveedor"], "doc_count": 6}],
        edges=[{"source": "Catering Buena Mesa", "rel_type": "CONTRATADO_PARA", "target": "Casamiento Perez-Gomez", "source_ids": ["gdrive:abc"]}],
    )

    primera = _graph_context_for(store, ["gdrive:abc"])
    segunda = _graph_context_for(store, ["gdrive:abc"])

    assert "Catering Buena Mesa" in primera
    assert segunda == ""


def test_anclas_parcialmente_solapadas_muestra_solo_las_nuevas():
    store = _FakeGraphStore(
        anchors=[
            {"name": "Catering Buena Mesa", "norm_name": "catering buena mesa", "types": ["Proveedor"], "doc_count": 6},
            {"name": "Quinta El Ombu", "norm_name": "quinta el ombu", "types": ["Locacion"], "doc_count": 5},
        ],
        edges=[],
    )

    _graph_context_for(store, ["gdrive:abc"])  # muestra ambas anclas, quedan marcadas

    # Segunda llamada: mismo store (mismas dos anclas candidatas), pero ya
    # se mostraron ambas -- no debe quedar nada nuevo que aportar.
    segunda = _graph_context_for(store, ["gdrive:abc"])
    assert segunda == ""

    # Un graph_store distinto con una ancla nueva sumada a una ya vista:
    # solo la nueva debe aparecer.
    store_con_novedad = _FakeGraphStore(
        anchors=[
            {"name": "Catering Buena Mesa", "norm_name": "catering buena mesa", "types": ["Proveedor"], "doc_count": 6},
            {"name": "Sabores del Plata", "norm_name": "sabores del plata", "types": ["Proveedor"], "doc_count": 6},
        ],
        edges=[],
    )
    tercera = _graph_context_for(store_con_novedad, ["gdrive:def"])
    assert "Catering Buena Mesa" not in tercera
    assert "Sabores del Plata" in tercera


def test_dedupe_no_marca_como_mostrada_una_ancla_que_el_presupuesto_de_caracteres_corto(monkeypatch):
    # format_graph_context (Cambio 1, GRAPH_MAX_CHARS) puede cortar una
    # ancla entera si el bloque supera el presupuesto -- esa ancla nunca
    # llego al texto que ve Claude, asi que NO debe marcarse como "ya
    # mostrada": una llamada posterior con menos competencia por espacio
    # todavia tiene que poder mostrarla.
    anchor_a = {"name": "Ancla A", "norm_name": "ancla a", "types": ["Tipo"], "doc_count": 5}
    anchor_b = {"name": "Ancla B", "norm_name": "ancla b", "types": ["Tipo"], "doc_count": 4}
    store = _FakeGraphStore(anchors=[anchor_a, anchor_b], edges=[])

    # Simular que el presupuesto de caracteres corto la segunda ancla: el
    # texto que devuelve format_graph_context solo trae el header de A.
    monkeypatch.setattr(
        tools_module.retrieval,
        "format_graph_context",
        lambda anchors, edges: "Ancla A [Tipo] (5 docs)",
    )

    _graph_context_for(store, ["gdrive:abc"])

    assert "ancla a" in tools_module._mapa_anchors_shown
    assert "ancla b" not in tools_module._mapa_anchors_shown


def test_init_tools_resetea_el_estado_de_anclas_mostradas():
    store = _FakeGraphStore(
        anchors=[{"name": "Catering Buena Mesa", "norm_name": "catering buena mesa", "types": ["Proveedor"], "doc_count": 6}],
        edges=[],
    )

    _graph_context_for(store, ["gdrive:abc"])
    assert _graph_context_for(store, ["gdrive:abc"]) == ""  # ya mostrada, mismo turno

    _init_tools(_FakeVectorStore({}), None)  # nuevo turno

    # Turno nuevo: la misma ancla vuelve a ser "nueva".
    otra_vez = _graph_context_for(store, ["gdrive:abc"])
    assert "Catering Buena Mesa" in otra_vez


class _FakeVectorStore:
    """Store vectorial falso: devuelve un resultado fijo de search_knowledge_base
    sin llamar a Qdrant."""

    def __init__(self, result):
        self._result = result

    def search(self, query_vector, top_k, kind_filter):
        # Devolver una copia -- search_knowledge_base muta result["mapa"] in place.
        return dict(self._result)


def test_search_knowledge_base_llama_a_graph_context_for_y_arma_mapa(monkeypatch):
    """Prueba end-to-end (sin Neo4j ni Voyage reales) de que
    search_knowledge_base efectivamente llama a _graph_context_for con el
    graph_store inicializado y los sources que devolvio la busqueda, y mete
    el resultado real (no un stub) bajo la clave "mapa" del JSON devuelto."""

    fake_store = _FakeVectorStore({"contexts": ["algo"], "sources": ["gdrive:abc"]})
    fake_graph_store = _FakeGraphStore(
        anchors=[{"name": "Catering Buena Mesa", "norm_name": "catering buena mesa", "types": ["Proveedor"], "doc_count": 6}],
        edges=[{"source": "Catering Buena Mesa", "rel_type": "CONTRATADO_PARA", "target": "Casamiento Perez-Gomez", "source_ids": ["gdrive:abc"]}],
    )

    # Evitar una llamada real a la API de Voyage.
    monkeypatch.setattr(
        tools_module.embeddings, "embed_texts", lambda texts, input_type=None: [[0.0] * 10]
    )

    _init_tools(fake_store, fake_graph_store)

    raw = search_knowledge_base("como viene Catering Buena Mesa?", top_k=3)

    # Es JSON valido.
    result = json.loads(raw)

    assert "mapa" in result
    # No es un stub: es el mapa REAL que arma _graph_context_for a partir del
    # graph_store falso (misma aserción de contenido que
    # test_con_anclas_y_aristas_arma_el_mapa).
    assert "Catering Buena Mesa" in result["mapa"]
    assert "CONTRATADO_PARA" in result["mapa"]

    # _FakeGraphStore (definido arriba en este archivo) no tiene close(): lo
    # cierra run_turn(), no search_knowledge_base -- no hay nada que
    # aserter aca al respecto.
