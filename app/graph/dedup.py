"""Deduplicacion difusa de nombres de entidad, sin gastar llamadas a Claude.

Claude extrae entidades documento por documento, asi que el mismo proveedor
puede volver escrito distinto en cada archivo ("Catering Buena Mesa",
"Buena Mesa Catering", "catering buena mesa."). Antes de escribir un nodo se
compara el nombre nuevo contra los que ya existen con ese label y, si hay un
match suficientemente bueno, se reusa el nodo existente.

Se evaluo hacer resolucion semantica con un LLM (como Microsoft GraphRAG) y
se descarto por ahora: el fuzzy matching resuelve el caso real sin costo de
API. Queda anotado como refinamiento futuro si aparece un caso que esto no
alcance a cubrir (ej. "Buena Mesa" vs "BM Servicios Gastronomicos", que no
comparten texto).

Funciones puras a proposito: se testean sin Neo4j ni Claude vivos.
"""

import unicodedata

from rapidfuzz import fuzz

from app.config import GRAPH_DEDUP_THRESHOLD


def strip_accents(text: str) -> str:
    """"Locación" -> "Locacion". Lo usan tanto el dedup de nombres como la
    sanitizacion de labels (app/graph/cypher.py): en los dos casos una tilde
    de mas no puede volver distinta a la misma cosa."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    """Forma canonica usada SOLO para comparar.

    El nombre que se guarda en Neo4j es siempre el original -- esto existe
    para que tildes, mayusculas y espacios de mas no cuenten como diferencia.
    """
    return " ".join(strip_accents(name).lower().split())


def find_best_match(
    name: str,
    candidates: list[str],
    threshold: int = GRAPH_DEDUP_THRESHOLD,
) -> str | None:
    """El candidato mas parecido a `name`, o None si ninguno llega al umbral.

    Usa token_sort_ratio: ordena las palabras antes de comparar, asi que es
    insensible al orden ("Catering Buena Mesa" == "Buena Mesa Catering").
    Devuelve el candidato tal cual vino (no normalizado), porque ese es el
    nombre que ya existe como nodo en el grafo.
    """
    if not candidates:
        return None

    target = normalize_name(name)
    best_score: float = 0.0
    best_candidate: str | None = None

    for candidate in candidates:
        score = fuzz.token_sort_ratio(target, normalize_name(candidate))
        if score > best_score:
            best_score, best_candidate = score, candidate

    return best_candidate if best_score >= threshold else None
