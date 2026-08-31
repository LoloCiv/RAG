"""_graph_context_for: la logica de enriquecer una busqueda con el grafo,
aislada de search_knowledge_base para poder testearla con un graph_store
falso -- sin Neo4j real, y verificando en particular que un fallo del grafo
NUNCA rompe la busqueda semantica (search_knowledge_base tiene que seguir
funcionando aunque Neo4j este caido)."""

from app.agent.tools import _graph_context_for


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
