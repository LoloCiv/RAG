"""Orquestacion: documento -> Claude -> dedup -> Neo4j.

Ata las tres piezas anteriores. Es el unico modulo de app/graph que las
conoce a todas; extraction, dedup y cypher no se conocen entre si.
"""

import logging

from app.config import GRAPH_DEDUP_THRESHOLD
from app.graph import cypher, dedup, extraction

logger = logging.getLogger(__name__)


def sync_document_graph(
    graph_store,
    source_id: str,
    document_text: str,
    file_name: str,
    threshold: int = GRAPH_DEDUP_THRESHOLD,
) -> None:
    """Extrae el grafo de un documento y lo escribe.

    No ataja excepciones a proposito -- el try/except por documento vive en
    pipeline.py (_sync_graph_safe), igual que el patron que ya usa el resto
    de la ingesta.
    """
    if not document_text.strip():
        return

    result = extraction.extract_from_document(document_text, file_name)

    # Una sola consulta por documento: el pool de candidatos se mantiene en
    # memoria y se le van sumando las entidades nuevas, asi el dedup tambien
    # funciona DENTRO del documento (la segunda variante de un nombre ya ve
    # a la primera) sin pagar una consulta por entidad.
    candidates = graph_store.get_all_entity_names()

    # De cada nombre que dijo Claude al nombre canonico que quedo realmente
    # en el grafo. Las relaciones vienen despues y referencian los nombres
    # ORIGINALES, asi que hace falta este mapa para no dejarlas apuntando a
    # nodos que el dedup fusiono.
    name_to_canonical: dict[str, str] = {}

    for entity in result.entities:
        label = cypher.sanitize_label(entity.type)
        canonical_name = dedup.find_best_match(entity.name, candidates, threshold)
        if canonical_name is None:
            canonical_name = entity.name
            candidates.append(canonical_name)
        graph_store.merge_entity(canonical_name, label, entity.description, source_id)
        name_to_canonical[entity.name] = canonical_name

    for rel in result.relationships:
        source = name_to_canonical.get(rel.source)
        target = name_to_canonical.get(rel.target)
        if source is None or target is None:
            # Pasa cuando Claude nombra en una relacion algo que no incluyo
            # en la lista de entidades. Sin los dos extremos no hay nodo que
            # matchear, asi que la relacion se descarta.
            logger.warning(
                "Relacion %s->%s de %s referencia una entidad no extraida, se saltea",
                rel.source,
                rel.target,
                file_name,
            )
            continue

        rel_type = cypher.sanitize_rel_type(rel.relation_type)
        graph_store.merge_relationship(source, target, rel_type, rel.description, source_id)
