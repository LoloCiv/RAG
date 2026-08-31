"""Arma el bloque de contexto de grafo que ve Claude, a partir del
resultado crudo de Neo4j (anchors_by_source_ids + neighborhood en
app/graph/neo4j_client.py).

Funcion pura a proposito -- mismo criterio que dedup.py y cypher.py del
sub-proyecto 1: es donde vive el presupuesto de tokens de esta palanca, y
se testea sin Neo4j vivo.
"""

from app.config import GRAPH_MAX_ANCHORS, GRAPH_MAX_EDGES


def format_graph_context(
    anchors: list[dict],
    edges: list[dict],
    max_anchors: int = GRAPH_MAX_ANCHORS,
    max_edges: int = GRAPH_MAX_EDGES,
) -> str:
    """anchors y edges vienen YA ordenados por relevancia (Neo4j hace el
    ORDER BY) -- esta funcion no reordena, solo recorta y formatea.

    Devuelve "" si no hay anclas (nada que mostrar), nunca None: el llamador
    siempre puede concatenar el resultado sin chequear null.
    """
    if not anchors:
        return ""

    capped_anchors = anchors[:max_anchors]
    capped_edges = edges[:max_edges]

    lines: list[str] = []
    # Una arista cuyos DOS extremos son anclas es tocada dos veces por el
    # for externo (una vez como saliente bajo la ancla-origen, otra vez
    # como entrante bajo la ancla-destino) -- pero es el mismo hecho visto
    # desde los dos lados, y este es el unico modulo cuyo trabajo es cuidar
    # el presupuesto de tokens del bloque, asi que no corresponde gastarlo
    # dos veces en el mismo dato. Se imprime una sola vez, bajo la primera
    # ancla que la toca en el orden de relevancia que ya trae la lista (no
    # se reordena nada aca): quedan registrados por indice en
    # emitted_edge_indices para que las anclas siguientes la salteen.
    emitted_edge_indices: set[int] = set()
    for anchor in capped_anchors:
        types = "/".join(anchor.get("types") or [])
        lines.append(f"{anchor['name']} [{types}] ({anchor['doc_count']} docs)")

        for idx, edge in enumerate(capped_edges):
            if idx in emitted_edge_indices:
                continue

            source_ids = edge.get("source_ids") or []
            ref = f" ({source_ids[0]})" if source_ids else ""

            if edge["source"] == anchor["name"]:
                lines.append(f"  -{edge['rel_type']}-> {edge['target']}{ref}")
                emitted_edge_indices.add(idx)
            elif edge["target"] == anchor["name"]:
                lines.append(f"  <-{edge['rel_type']}- {edge['source']}{ref}")
                emitted_edge_indices.add(idx)
            # Ni source ni target es esta ancla: no corresponde bajo este
            # bloque (podria corresponder bajo otra ancla, se evalua en la
            # siguiente vuelta del for externo).

    return "\n".join(lines)
