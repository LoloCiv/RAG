"""tools._accumulated_sources: acumula source_id -> file_name a lo largo
de un turno (puede haber varias llamadas a search_knowledge_base), en
orden de PRIMERA aparicion -- Fase 3 del roadmap ("fuentes legibles" en la
UI necesita el file_name, no solo el source_id crudo).

Antes de esto _accumulated_sources era list[str] y claude_agent.py lo
volvia a dedupear con list(set(...)) al armar el resultado final -- un
set() de Python no garantiza orden, lo que tiraba abajo el orden de
relevancia que search_knowledge_base ya labura en preservar (ver
QdrantStorage.dedup_source_ids). Con dict ordenado (mismo patron que
dedup_source_ids) alcanza con recorrer tools._accumulated_sources.items()
directo, sin dedupear de nuevo."""

import app.agent.tools as tools_module
from app.agent.tools import _init_tools, search_knowledge_base


class _FakeVectorStore:
    def __init__(self, result):
        self._result = result

    def search(self, query_vector, top_k, kind_filter):
        return list(self._result)


def test_acumula_source_id_y_file_name_de_una_busqueda(monkeypatch):
    monkeypatch.setattr(tools_module.embeddings, "embed_texts", lambda texts, input_type=None: [[0.0] * 10])
    monkeypatch.setattr(tools_module.embeddings, "rerank", lambda query, documents, top_k: list(range(len(documents))))

    fake_store = _FakeVectorStore(
        [
            {"text": "a", "source_id": "s1", "file_name": "contrato.pdf", "score": 0.9},
            {"text": "b", "source_id": "s2", "file_name": "notas.docx", "score": 0.8},
        ]
    )
    _init_tools(fake_store, None)
    search_knowledge_base("pregunta", top_k=2)

    assert tools_module._accumulated_sources == {"s1": "contrato.pdf", "s2": "notas.docx"}


def test_preserva_orden_de_primera_aparicion_entre_llamadas(monkeypatch):
    monkeypatch.setattr(tools_module.embeddings, "embed_texts", lambda texts, input_type=None: [[0.0] * 10])
    monkeypatch.setattr(tools_module.embeddings, "rerank", lambda query, documents, top_k: list(range(len(documents))))

    class _SequencedStore:
        def __init__(self):
            self._calls = 0

        def search(self, query_vector, top_k, kind_filter):
            self._calls += 1
            if self._calls == 1:
                return [{"text": "a", "source_id": "s1", "file_name": "uno.pdf", "score": 0.9}]
            return [
                {"text": "b", "source_id": "s2", "file_name": "dos.pdf", "score": 0.9},
                {"text": "a-de-nuevo", "source_id": "s1", "file_name": "uno.pdf", "score": 0.5},
            ]

    _init_tools(_SequencedStore(), None)
    search_knowledge_base("primera pregunta", top_k=2)
    search_knowledge_base("segunda pregunta", top_k=2)

    # s1 aparecio primero (primera llamada) -- tiene que quedar primero en
    # el orden, aunque la segunda llamada lo vuelva a traer.
    assert list(tools_module._accumulated_sources.keys()) == ["s1", "s2"]


def test_init_tools_resetea_a_dict_vacio():
    _init_tools(_FakeVectorStore([]), None)
    assert tools_module._accumulated_sources == {}
