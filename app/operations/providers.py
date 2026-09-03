"""Tareas de modelo separadas para no acoplar operaciones al loop RAG.

La investigacion sigue en Claude Sonnet porque necesita herramientas. Las
tareas cortas se enrutan a Haiku y quedan listas para comparar proveedores.
"""

from typing import Protocol

import anthropic
from pydantic import BaseModel, Field

from app.agent import inbox
from app.config import ANTHROPIC_API_KEY, OPERATIONS_MODEL


class OperationsProvider(Protocol):
    def classify_message(self, message: str) -> dict: ...

    def extract_fields(self, message: str) -> dict: ...

    def research_and_answer(self, question: str) -> dict: ...

    def draft_reply(self, *, message: str, research: str, supplier_name: str, event_name: str) -> str: ...


class ClaudeOperationsProvider:
    """Implementacion inicial: conserva Sonnet para buscar y Haiku para redactar."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def research_and_answer(self, question: str) -> dict:
        return inbox.ask(question)

    def classify_message(self, message: str) -> dict:
        """Usa un esquema chico para que el triage no necesite el agente completo."""
        response = self._client.messages.parse(
            model=OPERATIONS_MODEL,
            max_tokens=300,
            system="Clasificá mensajes de proveedores de forma conservadora.",
            messages=[{"role": "user", "content": message}],
            output_format=MessageClassification,
        )
        return response.parsed_output.model_dump()

    def extract_fields(self, message: str) -> dict:
        """Extrae solo hechos textuales para que la UI no confunda inferencias con datos."""
        response = self._client.messages.parse(
            model=OPERATIONS_MODEL,
            max_tokens=500,
            system="Extraé datos comerciales explícitos sin inventar valores ausentes.",
            messages=[{"role": "user", "content": message}],
            output_format=MessageFields,
        )
        return response.parsed_output.model_dump()

    def draft_reply(self, *, message: str, research: str, supplier_name: str, event_name: str) -> str:
        response = self._client.messages.create(
            model=OPERATIONS_MODEL,
            max_tokens=600,
            system=(
                "Redactá un borrador breve y profesional para un proveedor. "
                "No inventes datos; si falta algo, pedilo con claridad."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Evento: {event_name}\nProveedor: {supplier_name}\n"
                    f"Mensaje recibido:\n{message}\n\n"
                    f"Evidencia de la empresa:\n{research}"
                ),
            }],
        )
        return "".join(block.text for block in response.content if block.type == "text").strip()


class MessageClassification(BaseModel):
    intent: str = Field(description="Intencion comercial principal del mensaje")
    priority: str = Field(description="Prioridad sugerida: low, normal o high")
    needs_reply: bool = Field(description="Si el mensaje requiere una respuesta")


class MessageFields(BaseModel):
    event_name: str | None = Field(description="Evento mencionado, si aparece")
    dates: list[str] = Field(description="Fechas explícitas mencionadas")
    amounts: list[float] = Field(description="Importes explícitos mencionados")
    requests: list[str] = Field(description="Pedidos explícitos del proveedor")
