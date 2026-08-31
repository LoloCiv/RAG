"""TODO (vos): wrapper sobre Qdrant.

Este es el modulo mas usado de todo el proyecto -- lo llaman pipeline.py
(para upsert e idempotencia) y app/agent/tools.py (para las dos tools del
agente). Especificamente necesita una clase QdrantStorage con esta interfaz
(todo lo demas que escribiste asume exactamente estos nombres/firmas):

    class QdrantStorage:
        def __init__(self, url: str, collection: str, dim: int): ...

        def upsert(self, ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None: ...

        def search(self, query_vector: list[float], top_k: int = 5, kind_filter: str | None = None) -> dict:
            # devuelve {"contexts": [...], "sources": [...]}
            ...

        def get_by_source_id(self, source_id: str) -> dict | None:
            # devuelve el payload del punto kind="table_data" para ese source_id,
            # o None si no existe
            ...

        def delete_by_source_id(self, source_id: str) -> None: ...

--------------------------------------------------------------------------
Contexto / decisiones ya tomadas (ver el plan para el detalle completo):
--------------------------------------------------------------------------
- Una sola coleccion Qdrant (nombre en app/config.py: QDRANT_COLLECTION,
  "events_kb"), que mezcla dos tipos de punto discriminados por el campo
  "kind" del payload:
    - "text_chunk": chunks de texto de PDFs/Docs/resumenes de filas de sheet
      (ver la forma exacta del payload en pipeline.py:_upsert_text_chunks)
    - "table_data": un blob por tab de planilla con la tabla cruda completa
      (ver pipeline.py:_upsert_table_blob)

- __init__ (adaptado de vector_db.py del repo de referencia): conectar,
  crear la coleccion si no existe (VectorParams(size=dim, distance=Distance.COSINE)).
  A DIFERENCIA del repo de referencia: si QdrantClient no puede conectar,
  no dejes pasar la excepcion cruda -- atajala y relanza un error con un
  mensaje claro tipo "Qdrant no responde en {url} -- esta corriendo el
  contenedor Docker?" (va a ser el fallo mas comun corriendo esto en local,
  conviene que sea legible).

- search(): igual que el repo de referencia (similarity search + juntar
  contexts/sources de los payloads), pero agregale un filtro opcional por
  "kind" -- search_knowledge_base (la tool del agente) solo quiere
  kind="text_chunk", nunca quiere que aparezcan blobs de tabla (JSON crudo)
  mezclados en los resultados de busqueda semantica. Mirar
  qdrant_client.models.Filter / FieldCondition / MatchValue para armar el
  filtro.

- get_by_source_id(): ESTO NO es similarity search. Es un client.scroll()
  filtrado por source_id + kind="table_data", que devuelve como mucho un
  punto -- devolve directamente su .payload (o None si no hay match). La
  usa get_source_table en app/agent/tools.py para traerle a Claude la tabla
  exacta antes de graficar.

- delete_by_source_id(): client.delete() con un Filter por source_id
  (borra TODOS los puntos con ese source_id, sea kind="text_chunk" o
  "table_data"). La usa pipeline.py antes de re-ingerir un archivo que
  cambio, para no dejar puntos viejos huerfanos.

Pistas:
- El repo de referencia (ProductionGradeRAGPythonApp/vector_db.py) ya tiene
  __init__/upsert/search resueltos para el caso simple (sin el campo
  "kind", sin get_by_source_id/delete_by_source_id) -- es el punto de
  partida logico, extendelo en vez de arrancar de cero.
"""

from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue

from app.config import EMBED_DIM, QDRANT_COLLECTION, QDRANT_URL  # noqa: F401 -- los vas a necesitar


class QdrantStorage:
    def __init__(self, url: str = QDRANT_URL, collection: str = QDRANT_COLLECTION, dim: int = EMBED_DIM):
        """Conectar a Qdrant y crear la colección si no existe.
        
        Lanza un error claro si Qdrant no responde.
        """
        try:
            self.client = QdrantClient(url=url, timeout=30)
            self.collection = collection
            
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
        except Exception as e:
            raise ConnectionError(
                f"Qdrant no responde en {url} -- ¿esta corriendo el contenedor Docker? "
                f"Error: {e}"
            ) from e

    def upsert(self, ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None:
        """Insertar o actualizar puntos en Qdrant (upsert idempotente)."""
        points = [
            PointStruct(id=ids[i], vector=vectors[i], payload=payloads[i])
            for i in range(len(ids))
        ]
        self.client.upsert(self.collection, points=points)

    def search(self, query_vector: list[float], top_k: int = 5, kind_filter: str | None = None) -> dict:
        """Búsqueda por similitud semántica.
        
        Si kind_filter es "text_chunk", solo devuelve chunks de texto.
        Si es None, devuelve todos los resultados.
        """
        query_filter = None
        if kind_filter:
            query_filter = Filter(
                must=[
                    FieldCondition(key="kind", match=MatchValue(value=kind_filter))
                ]
            )
        
        # OJO: .search() fue removido en qdrant-client 1.10+ (reemplazado
        # por .query_points()) -- .search() ya no existe en la version
        # instalada (1.19.0), tira AttributeError.
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            with_payload=True,
            limit=top_k,
        )

        return self._dedup_sources_preserving_order(response.points)

    @staticmethod
    def _dedup_sources_preserving_order(points) -> dict:
        """Arma {"contexts", "sources"} a partir de los puntos que devuelve
        Qdrant, YA ordenados por score (mas relevante primero).

        Estatico y aislado a proposito: se puede testear el orden del
        dedup con puntos falsos, sin Qdrant vivo. Antes el dedup de
        sources usaba un set() -- Python no garantiza orden ahi, asi que
        se perdia la info de "que source es mas relevante" (necesaria
        para MRR en scripts/eval_retrieval.py). dict como set ordenado
        conserva el orden de primera aparicion.
        """
        contexts = []
        sources: dict[str, None] = {}

        for r in points:
            payload = getattr(r, "payload", None) or {}
            text = payload.get("text", "")
            source_id = payload.get("source_id", "")
            if text:
                contexts.append(text)
                sources[source_id] = None

        return {"contexts": contexts, "sources": list(sources)}

    def get_by_source_id(self, source_id: str) -> dict | None:
        """Obtener el payload del punto kind='table_data' para un source_id.
        
        Devuelve None si no existe.
        """
        filter_cond = Filter(
            must=[
                FieldCondition(key="source_id", match=MatchValue(value=source_id)),
                FieldCondition(key="kind", match=MatchValue(value="table_data")),
            ]
        )
        
        results = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=filter_cond,
            limit=1
        )
        
        points, _ = results
        if points:
            return points[0].payload
        return None

    def delete_by_source_id(self, source_id: str) -> None:
        """Borrar todos los puntos con un source_id (chunks y tabla)."""
        filter_cond = Filter(
            must=[
                FieldCondition(key="source_id", match=MatchValue(value=source_id))
            ]
        )
        self.client.delete(
            collection_name=self.collection,
            points_selector=filter_cond
        )
