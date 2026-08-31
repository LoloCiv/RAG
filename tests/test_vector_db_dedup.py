"""_dedup_sources_preserving_order: aisla el dedup de sources del resto de
QdrantStorage.search() para poder testear el orden sin Qdrant vivo. Los
puntos que devuelve response.points YA vienen ordenados por score (mas
relevante primero) -- antes se perdia ese orden porque el dedup usaba un
set() (Python no garantiza orden ahi), lo que hubiera invalidado cualquier
metrica de ranking (MRR en scripts/eval_retrieval.py) calculada sobre
"sources"."""

from app.rag.vector_db import QdrantStorage


class _FakePoint:
    def __init__(self, payload):
        self.payload = payload


def test_preserva_el_orden_de_aparicion_al_dedupear():
    points = [
        _FakePoint({"text": "a", "source_id": "s1"}),
        _FakePoint({"text": "b", "source_id": "s2"}),
        _FakePoint({"text": "c", "source_id": "s1"}),  # repetido, mismo source
        _FakePoint({"text": "d", "source_id": "s3"}),
    ]

    result = QdrantStorage._dedup_sources_preserving_order(points)

    assert result["sources"] == ["s1", "s2", "s3"]
    assert result["contexts"] == ["a", "b", "c", "d"]


def test_ignora_puntos_sin_texto():
    # kind="table_data" no tiene campo "text" -- no debe contribuir ni a
    # contexts ni a sources (mismo criterio que el kind_filter de search()).
    points = [
        _FakePoint({"text": "", "source_id": "s1"}),
        _FakePoint({"text": "algo", "source_id": "s2"}),
    ]

    result = QdrantStorage._dedup_sources_preserving_order(points)

    assert result["sources"] == ["s2"]
    assert result["contexts"] == ["algo"]


def test_punto_sin_payload_no_rompe():
    points = [_FakePoint(None), _FakePoint({"text": "algo", "source_id": "s1"})]

    result = QdrantStorage._dedup_sources_preserving_order(points)

    assert result == {"contexts": ["algo"], "sources": ["s1"]}
