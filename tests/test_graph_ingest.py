"""Orquestacion de la ingesta al grafo, con un graph_store falso.

Mismo criterio que test_qdrant_payload_shape.py: se testea la logica de
orquestacion (que se mergea, con que label, en que orden) sin Neo4j ni
Claude vivos. El fake simula lo unico que importa del store real: que la
identidad de un nodo sea su nombre normalizado y que el label del tipo se
acumule encima.
"""

import pytest

from app.graph import ingest
from app.graph.dedup import normalize_name
from app.graph.extraction import Entity, ExtractionResult, Relationship


class FakeGraphStore:
    """Simula lo unico que importa del store real: la identidad de un nodo es
    su nombre normalizado, y el label del tipo se ACUMULA en vez de partir la
    identidad."""

    def __init__(self):
        self.entities: list[dict] = []
        self.relationships: list[dict] = []

    def _find(self, name: str) -> dict | None:
        key = normalize_name(name)
        return next((e for e in self.entities if normalize_name(e["name"]) == key), None)

    def get_all_entity_names(self) -> list[str]:
        return [e["name"] for e in self.entities]

    def merge_entity(self, name: str, label: str, description: str, source_id: str) -> None:
        existing = self._find(name)
        if existing is not None:
            if label not in existing["labels"]:
                existing["labels"].append(label)
            if source_id not in existing["source_ids"]:
                existing["source_ids"].append(source_id)
            return
        self.entities.append(
            {"name": name, "labels": [label], "description": description, "source_ids": [source_id]}
        )

    def merge_relationship(
        self, source_name, target_name, rel_type, description, source_id
    ) -> None:
        self.relationships.append(
            {
                "source_name": source_name,
                "target_name": target_name,
                "rel_type": rel_type,
                "source_id": source_id,
            }
        )


@pytest.fixture
def store():
    return FakeGraphStore()


def _stub_extraction(monkeypatch, result: ExtractionResult):
    monkeypatch.setattr(ingest.extraction, "extract_from_document", lambda text, name: result)


def test_entidades_se_mergean_con_el_type_sanitizado_como_label(monkeypatch, store):
    _stub_extraction(
        monkeypatch,
        ExtractionResult(
            entities=[Entity(name="Catering Buena Mesa", type="Proveedor de Catering", description="d")],
            relationships=[],
        ),
    )

    ingest.sync_document_graph(store, "gdrive:abc", "texto del documento", "Manual.txt")

    assert store.entities == [
        {
            "name": "Catering Buena Mesa",
            "labels": ["Proveedor_de_catering"],
            "description": "d",
            "source_ids": ["gdrive:abc"],
        }
    ]


def test_relaciones_usan_el_relation_type_sanitizado(monkeypatch, store):
    _stub_extraction(
        monkeypatch,
        ExtractionResult(
            entities=[
                Entity(name="Catering Buena Mesa", type="Proveedor", description="d"),
                Entity(name="Casamiento Perez", type="Evento", description="d"),
            ],
            relationships=[
                Relationship(
                    source="Catering Buena Mesa",
                    target="Casamiento Perez",
                    relation_type="contratado para",
                    description="d",
                )
            ],
        ),
    )

    ingest.sync_document_graph(store, "gdrive:abc", "texto", "Manual.txt")

    assert len(store.relationships) == 1
    rel = store.relationships[0]
    assert rel["rel_type"] == "CONTRATADO_PARA"
    assert rel["source_name"] == "Catering Buena Mesa"
    assert rel["target_name"] == "Casamiento Perez"


def test_dedupea_dentro_del_mismo_documento(monkeypatch, store):
    # Claude escribio el mismo proveedor de dos formas en un solo documento:
    # tiene que terminar en un unico nodo, con el nombre de la primera vez.
    _stub_extraction(
        monkeypatch,
        ExtractionResult(
            entities=[
                Entity(name="Catering Buena Mesa", type="Proveedor", description="d"),
                Entity(name="Buena Mesa Catering", type="Proveedor", description="otra"),
            ],
            relationships=[],
        ),
    )

    ingest.sync_document_graph(store, "gdrive:abc", "texto", "Manual.txt")

    assert len(store.entities) == 1
    assert store.entities[0]["name"] == "Catering Buena Mesa"


def test_relacion_a_un_nombre_deduplicado_apunta_al_nombre_canonico(monkeypatch, store):
    # La relacion referencia la variante que se dedupeo -- tiene que
    # resolverse al nodo canonico, no quedar colgada.
    _stub_extraction(
        monkeypatch,
        ExtractionResult(
            entities=[
                Entity(name="Catering Buena Mesa", type="Proveedor", description="d"),
                Entity(name="Buena Mesa Catering", type="Proveedor", description="d"),
                Entity(name="Casamiento Perez", type="Evento", description="d"),
            ],
            relationships=[
                Relationship(
                    source="Buena Mesa Catering",
                    target="Casamiento Perez",
                    relation_type="CATERING_DE",
                    description="d",
                )
            ],
        ),
    )

    ingest.sync_document_graph(store, "gdrive:abc", "texto", "Manual.txt")

    assert store.relationships[0]["source_name"] == "Catering Buena Mesa"


def test_relacion_que_referencia_una_entidad_no_extraida_se_saltea(monkeypatch, store, caplog):
    _stub_extraction(
        monkeypatch,
        ExtractionResult(
            entities=[Entity(name="Catering Buena Mesa", type="Proveedor", description="d")],
            relationships=[
                Relationship(
                    source="Catering Buena Mesa",
                    target="Evento Fantasma",  # Claude nunca lo extrajo como entidad
                    relation_type="CATERING_DE",
                    description="d",
                )
            ],
        ),
    )

    with caplog.at_level("WARNING"):
        ingest.sync_document_graph(store, "gdrive:abc", "texto", "Manual.txt")

    assert store.relationships == []
    assert "Evento Fantasma" in caplog.text


def test_documento_vacio_no_llama_a_claude(monkeypatch, store):
    def explotar(text, name):
        raise AssertionError("no deberia llamarse a Claude con un documento vacio")

    monkeypatch.setattr(ingest.extraction, "extract_from_document", explotar)

    ingest.sync_document_graph(store, "gdrive:abc", "   \n  ", "Vacio.txt")

    assert store.entities == []


def test_el_mismo_nombre_con_types_distintos_es_un_solo_nodo_que_acumula_labels():
    # LA decision central del dedup: con types libres, el type NO puede ser
    # parte de la identidad. Claude le puso "Proveedor" en un documento y
    # "Proveedor de Flores" en otro a la MISMA empresa; tiene que quedar un
    # nodo con los dos labels, no dos nodos.
    # (Es el bug conocido de Microsoft GraphRAG, que agrupa por (title, type)
    # y termina descartando el nodo del segundo type.)
    store = FakeGraphStore()
    store.merge_entity("Flores del Sur", "Proveedor_de_flores", "d", "gdrive:doc1")
    store.merge_entity("Flores del Sur", "Proveedor", "d", "gdrive:doc2")

    assert len(store.entities) == 1
    assert store.entities[0]["labels"] == ["Proveedor_de_flores", "Proveedor"]
    assert store.entities[0]["source_ids"] == ["gdrive:doc1", "gdrive:doc2"]


def test_dedupea_entre_documentos_aunque_cambie_el_type(monkeypatch, store):
    # El caso ancla del plan, extremo a extremo: dos documentos, el mismo
    # proveedor con types distintos -> un nodo, dos source_ids.
    _stub_extraction(
        monkeypatch,
        ExtractionResult(
            entities=[Entity(name="Catering Buena Mesa", type="Proveedor de Catering", description="d")],
            relationships=[],
        ),
    )
    ingest.sync_document_graph(store, "gdrive:doc1", "texto", "Manual.txt")

    _stub_extraction(
        monkeypatch,
        ExtractionResult(
            entities=[Entity(name="catering buena mesa", type="Proveedor", description="otra")],
            relationships=[],
        ),
    )
    ingest.sync_document_graph(store, "gdrive:doc2", "texto", "Reporte.txt")

    assert len(store.entities) == 1
    assert store.entities[0]["source_ids"] == ["gdrive:doc1", "gdrive:doc2"]
    assert store.entities[0]["labels"] == ["Proveedor_de_catering", "Proveedor"]


def test_pide_los_candidatos_una_sola_vez_por_documento(monkeypatch, store):
    # El dedup dentro del documento no puede costar una consulta por
    # entidad: el pool de candidatos se mantiene en memoria y crece con las
    # entidades recien mergeadas.
    llamadas = []
    original = store.get_all_entity_names
    store.get_all_entity_names = lambda: (llamadas.append(1), original())[1]

    _stub_extraction(
        monkeypatch,
        ExtractionResult(
            entities=[
                Entity(name="Catering Buena Mesa", type="Proveedor", description="d"),
                Entity(name="Buena Mesa Catering", type="Proveedor", description="d"),
                Entity(name="Salon Jacaranda", type="Locacion", description="d"),
            ],
            relationships=[],
        ),
    )

    ingest.sync_document_graph(store, "gdrive:abc", "texto", "Manual.txt")

    assert len(llamadas) == 1
    assert len(store.entities) == 2  # las dos variantes del catering colapsaron
