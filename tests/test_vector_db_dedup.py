"""_points_to_results / dedup_source_ids: aislan el armado del resultado de
QdrantStorage.search() del resto para poder testearlo sin Qdrant vivo.

Antes search() dedupeaba a nivel documento y tiraba el score (necesario
para reranking, que reordena a nivel chunk). Ahora _points_to_results
devuelve una lista correlacionada por chunk (text/source_id/file_name/score,
sin dedupear, en el orden de relevancia que ya trae Qdrant), y
dedup_source_ids se aplica aparte donde hace falta la lista de documentos
(por ejemplo para "sources" de search_knowledge_base o para
scripts/eval_retrieval.py). Separarlos evita que dedupear por-documento le
oculte al reranker la senal por-chunk que necesita.
"""

from app.rag.vector_db import QdrantStorage


class _FakePoint:
    def __init__(self, payload, score=0.0):
        self.payload = payload
        self.score = score


def test_points_to_results_preserva_orden_y_no_dedupea():
    points = [
        _FakePoint({"text": "a", "source_id": "s1", "file_name": "f1.pdf"}, score=0.9),
        _FakePoint({"text": "b", "source_id": "s2", "file_name": "f2.pdf"}, score=0.8),
        _FakePoint({"text": "c", "source_id": "s1", "file_name": "f1.pdf"}, score=0.7),  # mismo source, no se dedupea aca
    ]

    result = QdrantStorage._points_to_results(points)

    assert result == [
        {"text": "a", "source_id": "s1", "file_name": "f1.pdf", "score": 0.9},
        {"text": "b", "source_id": "s2", "file_name": "f2.pdf", "score": 0.8},
        {"text": "c", "source_id": "s1", "file_name": "f1.pdf", "score": 0.7},
    ]


def test_points_to_results_ignora_puntos_sin_texto():
    # kind="table_data" no tiene campo "text" -- no debe contribuir (mismo
    # criterio que el kind_filter de search()).
    points = [
        _FakePoint({"text": "", "source_id": "s1", "file_name": "f1.pdf"}),
        _FakePoint({"text": "algo", "source_id": "s2", "file_name": "f2.pdf"}),
    ]

    result = QdrantStorage._points_to_results(points)

    assert result == [{"text": "algo", "source_id": "s2", "file_name": "f2.pdf", "score": 0.0}]


def test_points_to_results_punto_sin_payload_no_rompe():
    points = [_FakePoint(None), _FakePoint({"text": "algo", "source_id": "s1", "file_name": "f1.pdf"}, score=0.5)]

    result = QdrantStorage._points_to_results(points)

    assert result == [{"text": "algo", "source_id": "s1", "file_name": "f1.pdf", "score": 0.5}]


def test_dedup_source_ids_preserva_orden_de_primera_aparicion():
    results = [
        {"text": "a", "source_id": "s1", "file_name": "f1.pdf", "score": 0.9},
        {"text": "b", "source_id": "s2", "file_name": "f2.pdf", "score": 0.8},
        {"text": "c", "source_id": "s1", "file_name": "f1.pdf", "score": 0.7},
        {"text": "d", "source_id": "s3", "file_name": "f3.pdf", "score": 0.6},
    ]

    assert QdrantStorage.dedup_source_ids(results) == ["s1", "s2", "s3"]


def test_dedup_source_ids_lista_vacia():
    assert QdrantStorage.dedup_source_ids([]) == []
