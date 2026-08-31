"""search_knowledge_base + reranking (Fase 2): trae RERANK_CANDIDATES
candidatos de Qdrant (no solo top_k) y los reordena con el rerank de Voyage
antes de armar contexts/sources -- ese margen es lo que le permite al
reranker subir a primer lugar un chunk que la busqueda vectorial puso
3o/4o (el sintoma medido en la Fase 1, MRR base 0.90)."""

import json

import app.agent.tools as tools_module
from app.agent.tools import _init_tools, search_knowledge_base


class _RecordingFakeStore:
    """Devuelve dos chunks fijos, en orden vectorial (s1 primero), y anota
    con que top_k lo llamaron -- para verificar que se pidieron candidatos
    de mas, no solo top_k."""

    def __init__(self):
        self.called_with_top_k = None

    def search(self, query_vector, top_k, kind_filter):
        self.called_with_top_k = top_k
        return [
            {"text": "menos relevante", "source_id": "s1", "file_name": "a.pdf", "score": 0.9},
            {"text": "MAS relevante", "source_id": "s2", "file_name": "b.pdf", "score": 0.5},
        ]


def test_pide_candidatos_de_mas_no_solo_top_k(monkeypatch):
    fake_store = _RecordingFakeStore()
    monkeypatch.setattr(tools_module.embeddings, "embed_texts", lambda texts, input_type=None: [[0.0] * 10])
    monkeypatch.setattr(tools_module.embeddings, "rerank", lambda query, documents, top_k: list(range(len(documents)))[:top_k])

    _init_tools(fake_store, None)
    search_knowledge_base("pregunta", top_k=2)

    assert fake_store.called_with_top_k >= tools_module.RERANK_CANDIDATES


def test_reordena_contexts_y_sources_segun_el_rerank(monkeypatch):
    fake_store = _RecordingFakeStore()
    monkeypatch.setattr(tools_module.embeddings, "embed_texts", lambda texts, input_type=None: [[0.0] * 10])
    # El rerank invierte el orden: el chunk en indice 1 ("MAS relevante")
    # es en realidad el mas relevante, aunque Qdrant lo puso 2do.
    monkeypatch.setattr(tools_module.embeddings, "rerank", lambda query, documents, top_k: [1, 0])

    _init_tools(fake_store, None)
    raw = search_knowledge_base("pregunta", top_k=2)
    result = json.loads(raw)

    assert result["contexts"] == ["MAS relevante", "menos relevante"]
    assert result["sources"] == ["s2", "s1"]


def test_si_el_rerank_falla_sigue_funcionando_con_el_orden_vectorial(monkeypatch):
    fake_store = _RecordingFakeStore()
    monkeypatch.setattr(tools_module.embeddings, "embed_texts", lambda texts, input_type=None: [[0.0] * 10])

    def rerank_roto(query, documents, top_k):
        raise ConnectionError("Voyage no responde")

    monkeypatch.setattr(tools_module.embeddings, "rerank", rerank_roto)

    _init_tools(fake_store, None)
    raw = search_knowledge_base("pregunta", top_k=2)
    result = json.loads(raw)

    # Degrada al orden original de Qdrant -- la busqueda sigue funcionando.
    assert result["contexts"] == ["menos relevante", "MAS relevante"]
    assert result["sources"] == ["s1", "s2"]
