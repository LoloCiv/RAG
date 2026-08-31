"""Wrapper sobre Neo4j: conectividad, MERGE de entidades/relaciones y
limpieza de la contribucion de un documento.

Mismo reparto de responsabilidades que app/rag/vector_db.py: aca vive TODO
lo que habla con la base, y nada de la logica de extraccion o dedup (esa
esta en extraction.py / dedup.py, como funciones puras testeables).

Sobre la interpolacion de `label` / `rel_type` en las queries: Cypher no
permite parametrizarlos, van si o si en el string. Por eso ambos tienen que
venir ya pasados por app/graph/cypher.py (whitelist de \\w) -- este modulo
asume que el que llama ya sanitizo. Los VALORES (name, description,
source_id) si van parametrizados, como corresponde.
"""

from neo4j import GraphDatabase, NotificationMinimumSeverity

from app.config import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER
from app.graph.dedup import normalize_name


class Neo4jGraphStore:
    def __init__(
        self,
        uri: str = NEO4J_URI,
        user: str = NEO4J_USER,
        password: str | None = NEO4J_PASSWORD,
        database: str = NEO4J_DATABASE,
    ):
        try:
            # Notificaciones del server apagadas: con labels dinamicos,
            # consultar un label que todavia no existe es lo NORMAL
            # (get_candidate_names de la primera entidad de cada tipo), y el
            # MATCH de dos extremos de una relacion siempre se ve como
            # "cartesian product". Ninguna de las dos indica un problema, y
            # juntas ahogan la salida del resync -- una notificacion por
            # entidad y por relacion de cada documento.
            self.driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                notifications_min_severity=NotificationMinimumSeverity.OFF,
            )
            self.driver.verify_connectivity()
        except Exception as e:
            # Mismo criterio que QdrantStorage: el fallo mas comun corriendo
            # esto en local es "me olvide de levantar el contenedor", y un
            # traceback del driver no lo dice.
            raise ConnectionError(
                f"Neo4j no responde en {uri} -- ¿esta corriendo el contenedor Docker? Error: {e}"
            ) from e
        self.database = database
        self._ensure_schema()

    def close(self) -> None:
        self.driver.close()

    def _ensure_schema(self) -> None:
        """Constraint de unicidad sobre la clave de identidad.

        Hace dos cosas a la vez: garantiza que no puedan existir dos nodos
        para la misma entidad, y crea el indice que usan todos los MERGE y
        MATCH de abajo (sin el, cada escritura escanea todos los :Entity).
        """
        self.driver.execute_query(
            "CREATE CONSTRAINT entity_norm_name IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE e.norm_name IS UNIQUE",
            database_=self.database,
        )

    def get_all_entity_names(self) -> list[str]:
        """Todos los nombres del grafo, para el fuzzy match.

        Sin filtrar por label a proposito: con `type` libre, el label que
        Claude elige cambia entre documentos (el mismo proveedor puede venir
        como "Proveedor" o "Proveedor de Catering"), asi que filtrar por
        label partiria la identidad de la entidad y dejaria duplicados. Es
        el mismo problema que tiene Microsoft GraphRAG por agrupar sus
        entidades por (title, type).
        """
        records, _, _ = self.driver.execute_query(
            "MATCH (e:Entity) RETURN e.name AS name", database_=self.database
        )
        return [r["name"] for r in records]

    def anchors_by_source_ids(self, source_ids: list[str], limit: int) -> list[dict]:
        """Entidades ancla para el enriquecimiento del agente (sub-proyecto
        2): las que tienen AL MENOS uno de estos source_ids -- los mismos
        que ya devuelve QdrantStorage.search() -- ordenadas por cuantos
        documentos tocan en total (las mas conectadas primero, que son las
        que mas sirven para orientar una pregunta).
        """
        if not source_ids:
            return []
        query = """
        MATCH (e:Entity)
        WHERE any(sid IN e.source_ids WHERE sid IN $source_ids)
        RETURN e.name AS name, e.norm_name AS norm_name, e.types AS types,
               size(e.source_ids) AS doc_count
        ORDER BY doc_count DESC
        LIMIT $limit
        """
        records, _, _ = self.driver.execute_query(
            query, source_ids=source_ids, limit=limit, database_=self.database
        )
        return [dict(r) for r in records]

    def neighborhood(self, norm_names: list[str], limit: int) -> list[dict]:
        """Aristas donde el origen o el destino es una de estas anclas (por
        norm_name). Ordenadas por cuantos documentos evidencian cada
        relacion (mas fuentes primero), asi el corte por `limit` se queda
        con las aristas mejor respaldadas si hay mas de las que entran.
        """
        if not norm_names:
            return []
        query = """
        MATCH (a:Entity)-[r]->(b:Entity)
        WHERE a.norm_name IN $norm_names OR b.norm_name IN $norm_names
        RETURN a.name AS source, type(r) AS rel_type, b.name AS target,
               r.source_ids AS source_ids
        ORDER BY size(r.source_ids) DESC
        LIMIT $limit
        """
        records, _, _ = self.driver.execute_query(
            query, norm_names=norm_names, limit=limit, database_=self.database
        )
        return [dict(r) for r in records]

    def merge_entity(self, name: str, label: str, description: str, source_id: str) -> None:
        """Crea el nodo o, si ya existia, le suma este source_id y este label.

        La identidad es `norm_name` (nombre normalizado), NO el par
        (nombre, label): el label del tipo se acumula encima. Asi una entidad
        que aparece como "Proveedor" en un documento y "Proveedor de Flores"
        en otro es un solo nodo con los dos labels -- no se pierde ninguno de
        los dos tipos que extrajo Claude.

        `name` y `description` se escriben solo ON CREATE: gana la primera
        forma en que se vio la entidad, en vez de que el ultimo resync pise
        lo que ya habia.
        """
        query = f"""
        MERGE (e:Entity {{norm_name: $norm_name}})
        ON CREATE SET e.name = $name, e.description = $description, e.source_ids = [$source_id]
        ON MATCH SET e.source_ids = CASE WHEN $source_id IN e.source_ids
                                         THEN e.source_ids ELSE e.source_ids + $source_id END
        SET e:`{label}`,
            e.types = CASE WHEN $label IN coalesce(e.types, [])
                           THEN e.types ELSE coalesce(e.types, []) + $label END
        """
        self.driver.execute_query(
            query,
            norm_name=normalize_name(name),
            name=name,
            label=label,
            description=description,
            source_id=source_id,
            database_=self.database,
        )

    def merge_relationship(
        self,
        source_name: str,
        target_name: str,
        rel_type: str,
        description: str,
        source_id: str,
    ) -> None:
        """MATCH (no MERGE) de los extremos: los dos nodos ya tienen que
        existir -- ingest.py mergea todas las entidades antes de las
        relaciones justamente para eso. Los busca por norm_name, la misma
        clave de identidad que usa merge_entity."""
        query = f"""
        MATCH (a:Entity {{norm_name: $source_norm}}), (b:Entity {{norm_name: $target_norm}})
        MERGE (a)-[r:`{rel_type}`]->(b)
        ON CREATE SET r.description = $description, r.source_ids = [$source_id]
        ON MATCH SET r.source_ids = CASE WHEN $source_id IN r.source_ids
                                         THEN r.source_ids ELSE r.source_ids + $source_id END
        """
        self.driver.execute_query(
            query,
            source_norm=normalize_name(source_name),
            target_norm=normalize_name(target_name),
            description=description,
            source_id=source_id,
            database_=self.database,
        )

    def remove_source_contribution(self, source_id: str) -> dict:
        """Borra lo que aporto un documento, ANTES de re-extraerlo.

        Esto NO es el delete-and-recreate simple de Qdrant: un nodo puede
        estar compartido entre varios documentos ("Catering Buena Mesa"
        aparece en cinco). Asi que se saca el source_id de todas las listas
        y despues se borra solo lo que quedo sin ninguna fuente (GC).
        """
        with self.driver.session(database=self.database) as session:
            return session.execute_write(self._remove_source_tx, source_id)

    @staticmethod
    def _remove_source_tx(tx, source_id: str) -> dict:
        tx.run(
            "MATCH (e:Entity) WHERE $sid IN e.source_ids "
            "SET e.source_ids = [x IN e.source_ids WHERE x <> $sid]",
            sid=source_id,
        )
        tx.run(
            "MATCH ()-[r]->() WHERE $sid IN r.source_ids "
            "SET r.source_ids = [x IN r.source_ids WHERE x <> $sid]",
            sid=source_id,
        )
        # Las relaciones primero: DETACH DELETE de los nodos se llevaria
        # relaciones que todavia tienen fuentes vivas si se hiciera al reves.
        rels = tx.run(
            "MATCH ()-[r]->() WHERE size(r.source_ids) = 0 DELETE r RETURN count(*) AS n"
        ).single()["n"]
        nodes = tx.run(
            "MATCH (e:Entity) WHERE size(e.source_ids) = 0 DETACH DELETE e RETURN count(*) AS n"
        ).single()["n"]
        return {"deleted_relationships": rels, "deleted_nodes": nodes}

    def stats(self) -> dict:
        """Conteos rapidos, para los smoke tests manuales."""
        entities, _, _ = self.driver.execute_query(
            "MATCH (e:Entity) RETURN count(e) AS n", database_=self.database
        )
        rels, _, _ = self.driver.execute_query(
            "MATCH ()-[r]->() RETURN count(r) AS n", database_=self.database
        )
        return {"entities": entities[0]["n"], "relationships": rels[0]["n"]}
