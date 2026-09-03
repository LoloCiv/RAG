"""El borrador combina evidencia del RAG con la propuesta del modelo liviano."""

from app.operations.service import generate_draft
from app.operations.work_items import ingest_message


class _FakeProvider:
    def classify_message(self, message: str):
        return {"intent": "quote", "priority": "normal", "needs_reply": True}

    def extract_fields(self, message: str):
        return {"event_name": "Cena anual", "amounts": [100]}

    def research_and_answer(self, question: str):
        return {
            "id": "query-123",
            "answer_text": "El presupuesto aprobado para catering es $100.",
            "sources": [{"file_name": "presupuesto.xlsx", "drive_url": "https://drive.example/x"}],
        }

    def draft_reply(self, *, message: str, research: str, supplier_name: str, event_name: str):
        assert "presupuesto aprobado" in research
        return "Hola, gracias. ¿Podrían confirmar si $100 incluye servicio?"


def test_generate_draft_records_evidence_and_keeps_review_status(tmp_path):
    record = ingest_message(
        {
            "message_id": "whatsapp-1",
            "channel": "whatsapp",
            "supplier_name": "Buena Mesa",
            "event_name": "Cena anual",
            "text": "¿Qué presupuesto manejan?",
        },
        work_items_dir=tmp_path,
    )

    updated = generate_draft(record["id"], _FakeProvider(), work_items_dir=tmp_path)

    assert updated["status"] == "needs_review"
    assert updated["draft"]["text"].startswith("Hola")
    assert updated["evidence"]["query_id"] == "query-123"
    assert updated["evidence"]["sources"][0]["file_name"] == "presupuesto.xlsx"
    assert updated["analysis"]["classification"]["intent"] == "quote"
    assert updated["analysis"]["fields"]["amounts"] == [100]
    assert updated["audit"][-1]["event"] == "draft_generated"
