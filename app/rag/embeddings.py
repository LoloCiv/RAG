"""Generacion de embeddings con Voyage AI.

Voyage AI proporciona un servicio de embeddings de alta calidad que se integra
con el LLM de chat/agente en Claude (ver app/agent/claude_agent.py).

--------------------------------------------------------------------------
Que tiene que hacer embed_texts:
--------------------------------------------------------------------------
Dada una lista de strings, devolver una lista de vectores (uno por string,
mismo orden), usando el modelo de embeddings configurado en app/config.py
(EMBED_MODEL = "voyage-4-lite", EMBED_DIM = 1024).

Firma esperada (pipeline.py y app/agent/tools.py ya importan esto asi):

    def embed_texts(texts: list[str]) -> list[list[float]]:
        ...

Pistas:
- Voyage AI proporciona el SDK `voyageai` con cliente simple
  (`Client.embed(texts=..., model=...)`) -- mas simple que OpenAI.
- Los embeddings de Voyage vienen ordenados en la respuesta, por lo que
  directamente se pueden retornar como lista.
- Para valores input_type, usar "document" para chunks de texto (lo normal en RAG).
"""

import voyageai

from app.config import EMBED_DIM, EMBED_MODEL, VOYAGE_API_KEY

_client = None

# El SDK de Voyage ya trae reintento con backoff exponencial + jitter
# incorporado (ver voyageai.Client.embed -> self.retry_controller), pero
# viene apagado por default (max_retries=0). Sin tarjeta cargada en Voyage
# el rate limit es de solo 3 requests/minuto, asi que sin esto cualquier
# ingesta de mas de 3 archivos seguidos fallaba de una. Con max_retries>0
# el SDK reintenta solo en RateLimitError/ServiceUnavailableError/Timeout,
# esperando cada vez mas entre intentos.
_MAX_RETRIES = 8


def _get_client() -> voyageai.Client:
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=VOYAGE_API_KEY, max_retries=_MAX_RETRIES)
    return _client


def embed_texts(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Generar embeddings para una lista de strings usando Voyage AI.

    input_type="document" para lo que se indexa (chunks de texto, resumenes
    de tabla -- ver pipeline.py). input_type="query" para lo que se busca
    (ver search_knowledge_base en app/agent/tools.py). Voyage usa embeddings
    asimetricos: entrenaron document/query con prompts internos distintos,
    asi que usar "document" para las queries tambien funciona pero empeora
    la calidad del retrieval -- no es solo un detalle cosmetico.
    """
    if not texts:
        return []

    client = _get_client()
    response = client.embed(
        texts=texts,
        model=EMBED_MODEL,
        input_type=input_type,
    )

    # Retornar los vectores en el mismo orden que los textos
    return response.embeddings
