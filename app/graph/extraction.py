"""Extraccion de entidades y relaciones de un documento, con Claude.

Decision de diseno central: **no hay esquema fijo de tipos**. El `type` de
cada entidad y el `relation_type` de cada relacion son strings libres que
Claude propone segun el dominio del documento que esta leyendo. La FORMA del
JSON esta fija (structured outputs con Pydantic), los VALORES quedan
abiertos. Asi el mismo pipeline sirve para esta empresa de eventos, para una
ferreteria o para una textil sin tocar codigo.

Granularidad: una llamada por documento completo (no por chunk). Un chunk
suelto pierde el contexto que hace falta para ver relaciones entre entidades
que se mencionan en partes distintas del archivo.
"""

import logging

import anthropic
from pydantic import BaseModel, Field

from app.config import ANTHROPIC_API_KEY, EXTRACTION_MODEL

logger = logging.getLogger(__name__)

# Techo generoso: un documento con muchas entidades puede producir un JSON
# largo. Por debajo de esto la respuesta se corta a la mitad y la validacion
# de Pydantic falla con un error poco claro.
_MAX_TOKENS = 16000


class Entity(BaseModel):
    name: str = Field(description="Nombre de la entidad, tal cual aparece en el documento")
    type: str = Field(description="Tipo de entidad, elegido libremente segun el dominio del documento")
    description: str = Field(description="Que es esta entidad, segun lo que dice el documento")


class Relationship(BaseModel):
    source: str = Field(description="name exacto de la entidad de origen")
    target: str = Field(description="name exacto de la entidad de destino")
    relation_type: str = Field(description="Tipo de relacion, elegido libremente segun el documento")
    description: str = Field(description="Que dice el documento sobre esta relacion")


class ExtractionResult(BaseModel):
    entities: list[Entity]
    relationships: list[Relationship]


_SYSTEM_PROMPT = """Sos un extractor de grafos de conocimiento. Te doy el
texto completo de un documento de una empresa (de cualquier rubro) y tenes
que identificar las entidades relevantes y las relaciones explicitas entre
ellas.

No uses un esquema fijo de tipos: elegi el "type" de cada entidad y el
"relation_type" de cada relacion con las palabras que mejor describan el
dominio de ESTE documento (ej. "Proveedor", "Evento", "CONTRATADO_PARA"). Si
la misma entidad aparece varias veces, usa siempre el mismo "name" exacto, y
usa ese mismo "name" en el "source"/"target" de las relaciones.

Se conservador: no inventes datos que no esten en el texto."""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Cliente perezoso y reusado: crear uno por documento abriria un pool
    de conexiones nuevo en cada llamada del resync."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def extract_from_document(document_text: str, file_name: str) -> ExtractionResult:
    """Una llamada a Claude -> entidades + relaciones validadas.

    No ataja excepciones a proposito: el try/except por documento vive en
    pipeline.py, igual que el resto de la ingesta.
    """
    client = _get_client()
    response = client.messages.parse(
        model=EXTRACTION_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Documento: {file_name}\n\n{document_text}"}],
        output_format=ExtractionResult,
    )
    result = response.parsed_output
    logger.info(
        "Grafo %s -> %d entidades, %d relaciones",
        file_name,
        len(result.entities),
        len(result.relationships),
    )
    return result
