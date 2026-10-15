"""La búsqueda combina evidencia sin atribuirle al histórico datos del evento actual."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.agent import queries
from app.similar_events.models import SimilarEventRequest
from app.similar_events.service import find_similar_events, build_search_queries


def fragment(text, source="doc", index=0):
    return {"text": text, "source_id": source, "chunk_index": index, "file_name": source + ".pdf", "score": 0.8, "sheet_tab": None}


class Storage:
    def __init__(self, initial=None):
        self.initial = initial if initial is not None else [fragment("La Cena Aurora se realizó el 10 de mayo de 2025 con 120 asistentes.")]
        self.calls = []

    def search_evidence(self, vector, top_k=20):
        self.calls.append(vector)
        if "Cena Aurora" in vector:
            return [fragment("Cena Aurora: hubo demoras de montaje. Coordinar acceso con anticipación.", "report")]
        return self.initial


class Provider:
    def __init__(self, invalid=False, status="completed", event_date="2025-05-10"):
        self.invalid, self.status, self.event_date = invalid, status, event_date
        self.seen = []
        self.usage = {"input_tokens": 40, "output_tokens": 25}
        self.model = "fake-model"

    def discover(self, request, evidence, today):
        return {"events": [{"event_name": "Cena Aurora", "identity_citations": [{"evidence_id": evidence[0].id, "quote": "La Cena Aurora"}]}]}

    def synthesize(self, request, candidates, evidence, today):
        self.seen = evidence
        identity = [{"evidence_id": evidence[0].id, "quote": "La Cena Aurora"}]
        report = next((item for item in evidence if item.source_id == "report"), evidence[0])
        return {"events": [{
            "event_name": "Cena Aurora", "identity_citations": identity,
            "event_date": self.event_date, "date_citations": identity if self.event_date else [],
            "status": self.status, "status_citations": identity if self.status != "unknown" else [],
            "similarities": [{"text": "Escala cercana: 120 asistentes", "citations": [{"evidence_id": "inventado" if self.invalid else evidence[0].id, "quote": "120 asistentes"}]}],
            "differences": [], "characteristics": [], "suppliers": [], "costs": [],
            "lessons": [{"text": "Coordinar el montaje", "citations": [{"evidence_id": report.id, "quote": "demoras de montaje" if report.source_id == "report" else "120 asistentes"}]}],
            "missing_information": ["Ubicación no documentada"], "suggestions": []
        }]}


def run_search(tmp_path, storage=None, provider=None):
    return find_similar_events(SimilarEventRequest(description="Cena corporativa", attendees=150), queries_dir=tmp_path, storage=storage or Storage(), provider=provider or Provider(), embed=lambda texts: texts, rerank=lambda query, items, top_k: items[:top_k], today=date(2026, 9, 7))


def test_queries_are_bounded_and_optional_preferences_not_requirements():
    request = SimilarEventRequest(description="Cena con presentaciones", event_type="Corporativo", attendees=150, location="Buenos Aires")
    searches = build_search_queries(request)
    assert 1 <= len(searches) <= 3
    assert len(set(searches)) == len(searches)
    assert "150" in " ".join(searches)
    assert "Buenos Aires" in " ".join(searches)
    with pytest.raises(ValueError):
        SimilarEventRequest(description="   ")
    with pytest.raises(ValueError):
        SimilarEventRequest(description="Cena", attendees=0)


def test_enrichment_dedup_persistence_and_existing_link_compatibility(tmp_path):
    provider, storage = Provider(), Storage()
    result = run_search(tmp_path, storage, provider)
    data = result["similar_events"]
    assert len(data["events"]) == 1
    assert {item["source_id"] for item in data["evidence"]} == {"doc", "report"}
    assert len(data["evidence"]) == 2
    assert any("Cena Aurora" in query for query in storage.calls)
    assert result["usage"] == provider.usage
    assert result["model"] == "fake-model"
    assert queries.load_query(result["id"], tmp_path)["similar_events"] == data
    assert result["elapsed_ms"] >= 0
    assert result["references"] == []


def test_empty_retrieval_does_not_call_model(tmp_path):
    result = run_search(tmp_path, Storage([]), object())
    assert result["similar_events"]["events"] == []
    assert result["similar_events"]["evidence"] == []


def test_unknown_citations_are_rejected_without_saving_partial_result(tmp_path):
    with pytest.raises(ValueError, match="evidencia"):
        run_search(tmp_path, provider=Provider(invalid=True))
    assert queries.list_queries(tmp_path) == []


@pytest.mark.parametrize("status,event_date", [("ongoing", "2025-05-10"), ("planned", "2025-05-10"), ("completed", "2027-01-01")])
def test_current_planned_and_future_events_are_excluded(tmp_path, status, event_date):
    record = run_search(tmp_path, provider=Provider(status=status, event_date=event_date))
    assert record["similar_events"]["events"] == []


def test_unknown_date_remains_unknown(tmp_path):
    record = run_search(tmp_path, provider=Provider(status="unknown", event_date=None))
    event = record["similar_events"]["events"][0]
    assert event["event_date"] is None
    assert event["status"] == "unknown"


def test_quotes_must_exist_in_the_retrieved_fragment(tmp_path):
    class InventedQuote(Provider):
        def synthesize(self, *args):
            result = super().synthesize(*args)
            result["events"][0]["identity_citations"][0]["quote"] = "Este evento tuvo 900 personas"
            return result
    with pytest.raises(ValueError, match="fragmento"):
        run_search(tmp_path, provider=InventedQuote())


def test_evidence_payload_preserves_metadata_without_changing_general_search():
    from app.rag.vector_db import QdrantStorage
    point = SimpleNamespace(score=.8, payload={"text": "Cena", "source_id": "s", "file_name": "f", "chunk_index": 7, "sheet_tab": "Eventos"})
    general = QdrantStorage._points_to_results([point])
    evidence = QdrantStorage._points_to_results([point], include_metadata=True)
    assert "chunk_index" not in general[0]
    assert evidence[0]["chunk_index"] == 7
    assert evidence[0]["sheet_tab"] == "Eventos"


def test_homonyms_remain_separate_and_mixed_identity_is_rejected(tmp_path):
    class Homonyms:
        def discover(self, request, evidence, today):
            return {"events": [{"event_name": "Cena Aurora", "identity_citations": [{"evidence_id": e.id, "quote": e.text}]} for e in evidence]}
        def synthesize(self, request, candidates, evidence, today):
            return {"events": [dict(candidate.model_dump(), missing_information=["Fecha no documentada"]) for candidate in candidates.events]}
    docs = Storage([fragment("Cena Aurora de ACME, realizada en Córdoba", "acme"), fragment("Cena Aurora de Beta, realizada en Mendoza", "beta")])
    result = run_search(tmp_path, docs, Homonyms())
    assert len(result["similar_events"]["events"]) == 2
    assert result["similar_events"]["events"][0]["identity_citations"] != result["similar_events"]["events"][1]["identity_citations"]
    class Merged(Homonyms):
        def synthesize(self, request, candidates, evidence, today):
            return {"events": [{"event_name": "Cena Aurora", "identity_citations": [c for candidate in candidates.events for c in candidate.identity_citations]}]}
    with pytest.raises(ValueError, match="identidad"):
        run_search(tmp_path, docs, Merged())


def test_conflicting_sources_keep_unknown_fields_and_original_cost_scope(tmp_path):
    class Conflicting(Provider):
        def synthesize(self, request, candidates, evidence, today):
            identity = candidates.events[0].identity_citations
            cost = next(e for e in evidence if e.source_id == "cost")
            planned = next(e for e in evidence if e.source_id == "brief")
            return {"events": [{"event_name": "Cena Aurora", "identity_citations": identity,
                "differences": [{"text": "El brief estimaba 150 asistentes; el reporte registra 120.", "citations": [
                    {"evidence_id": planned.id, "quote": "150 previstos"}, {"evidence_id": evidence[0].id, "quote": "120 asistentes"}]}],
                "costs": [{"amount_text": "8000", "currency": "USD", "date_text": "mayo de 2025", "scope": "catering para 120, sin IVA", "citations": [{"evidence_id": cost.id, "quote": cost.text}]}],
                "missing_information": ["Fecha exacta en conflicto; no se infiere de la modificación del archivo"],
                "suggestions": [{"text": "Revisar estimación antes de contratar", "citations": [{"evidence_id": planned.id, "quote": "150 previstos"}]}]}]}
    docs = Storage([fragment("La Cena Aurora tuvo 120 asistentes", "report0"), fragment("Cena Aurora: 150 previstos", "brief"), fragment("Cena Aurora: USD 8000, mayo de 2025, catering para 120, sin IVA", "cost")])
    result = run_search(tmp_path, docs, Conflicting())["similar_events"]["events"][0]
    assert result["event_date"] is None
    assert len(result["differences"][0]["citations"]) == 2
    assert result["costs"][0]["currency"] == "USD"
    assert "sin IVA" in result["costs"][0]["scope"]
    assert result["lessons"] == [] and len(result["suggestions"]) == 1


def test_evaluation_distinguishes_citation_integrity_from_human_claim_review(tmp_path):
    from scripts.evaluate_similar_events import score
    result = run_search(tmp_path)
    row = score({"id": "fixture", "expected_files": ["doc.pdf", "report.pdf"], "expected_events": ["Cena Aurora"]}, result)
    assert row["retrieved_file_recall"] == row["returned_event_recall"] == row["citation_integrity"] == 1
    assert row["claim_support_review"] == "pending_human_review"
    assert row["usage"]["input_tokens"] == 40
