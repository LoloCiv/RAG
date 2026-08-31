"""QdrantStorage.rerank_results: reordena la lista correlacionada que
devuelve QdrantStorage.search() usando el rerank de Voyage, con
degradacion con gracia si falla (cuota, red) -- mismo criterio que el
grafo caido en _graph_context_for (app/agent/tools.py:_graph_context_for):
nunca propaga la excepcion, loguea y sigue con el orden vectorial original.

rerank_fn es inyectable (default: embeddings.rerank) para poder testear la
logica de reorden/degradacion sin hablarle a Voyage de verdad.
"""

import logging

from app.rag.vector_db import QdrantStorage


def _results(*source_ids):
    return [
        {"text": f"texto {i}", "source_id": sid, "file_name": f"{sid}.pdf", "score": 1.0 - i * 0.1}
        for i, sid in enumerate(source_ids)
    ]


def test_reordena_segun_los_indices_que_devuelve_rerank_fn():
    results = _results("s1", "s2", "s3")
    # rerank_fn dice que el orden correcto es s3, s1 (s2 no entra en el top_k)
    rerank_fn = lambda query, documents, top_k: [2, 0]

    reranked = QdrantStorage.rerank_results("query", results, top_k=2, rerank_fn=rerank_fn)

    assert [r["source_id"] for r in reranked] == ["s3", "s1"]


def test_lista_vacia_no_llama_a_rerank_fn():
    calls = []
    rerank_fn = lambda query, documents, top_k: calls.append(1) or []

    assert QdrantStorage.rerank_results("query", [], top_k=5, rerank_fn=rerank_fn) == []
    assert calls == []


def test_rerank_fn_que_falla_degrada_al_orden_vectorial_original(caplog):
    results = _results("s1", "s2", "s3")

    def rerank_fn(query, documents, top_k):
        raise ConnectionError("Voyage no responde")

    with caplog.at_level(logging.WARNING):
        reranked = QdrantStorage.rerank_results("query", results, top_k=2, rerank_fn=rerank_fn)

    # Primeros top_k del orden vectorial original -- ni un error 500 de
    # Voyage puede romper la busqueda semantica.
    assert [r["source_id"] for r in reranked] == ["s1", "s2"]
    assert any("rerank" in rec.message.lower() for rec in caplog.records)


def test_usa_embeddings_rerank_por_default(monkeypatch):
    import app.rag.vector_db as vector_db_module

    captured = {}

    def fake_rerank(query, documents, top_k):
        captured["query"] = query
        captured["documents"] = documents
        captured["top_k"] = top_k
        return list(range(len(documents)))[:top_k]

    monkeypatch.setattr(vector_db_module.embeddings, "rerank", fake_rerank)

    results = _results("s1", "s2")
    QdrantStorage.rerank_results("una pregunta", results, top_k=1)

    assert captured == {"query": "una pregunta", "documents": ["texto 0", "texto 1"], "top_k": 1}
