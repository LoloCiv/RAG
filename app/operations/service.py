"""Coordina evidencia RAG y borrador sin conceder permiso de envio."""

from pathlib import Path

from app.config import WORK_ITEMS_DIR
from app.operations import work_items
from app.operations.providers import OperationsProvider


def generate_draft(work_item_id: str, provider: OperationsProvider, work_items_dir: Path = WORK_ITEMS_DIR) -> dict:
    """Genera una propuesta revisable; cualquier envio sigue requiriendo aprobacion."""
    record = work_items.load_work_item(work_item_id, work_items_dir)
    if record is None:
        raise ValueError("No existe el work item")
    message = next((item for item in reversed(record["messages"]) if item["direction"] == "inbound"), None)
    if message is None:
        raise ValueError("No hay un mensaje entrante para responder")
    classification = provider.classify_message(message["text"])
    fields = provider.extract_fields(message["text"])
    work_items.set_analysis(work_item_id, classification, fields, work_items_dir)
    question = (
        f"Necesito responder a {record['supplier_name']} por el evento {record['event_name']}. "
        f"Su mensaje fue: {message['text']}\n"
        "Buscá en la base de conocimiento datos verificables para redactar una respuesta. "
        "Indicá claramente cualquier dato que no esté respaldado."
    )
    research = provider.research_and_answer(question)
    draft = provider.draft_reply(
        message=message["text"],
        research=research.get("answer_text", ""),
        supplier_name=record["supplier_name"],
        event_name=record["event_name"],
    )
    evidence = {"query_id": research.get("id"), "answer_text": research.get("answer_text", ""), "sources": research.get("sources", [])}
    return work_items.set_draft(work_item_id, draft, evidence, work_items_dir)
