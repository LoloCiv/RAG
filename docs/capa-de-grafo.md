# Cómo funciona la capa de grafo (`app/graph/`)

Por cada documento que el resync detecta nuevo o cambiado, además del camino
vectorial:

1. `extraction.py` — **una** llamada a Claude por documento completo (no por
   chunk) que devuelve entidades y relaciones con structured outputs. Los
   tipos son **strings libres** que Claude elige según el dominio del
   documento, no un enum fijo: el mismo pipeline sirve para una empresa de
   eventos o para una ferretería sin tocar código.
2. `dedup.py` — fuzzy matching determinístico (`rapidfuzz`) para reconocer
   que "Buena Mesa Catering" y "Catering Buena Mesa" son la misma entidad,
   sin gastar API.
3. `cypher.py` — el tipo libre se convierte a un label **seguro y canónico**:
   whitelist de `\w` (Cypher no permite parametrizar labels, así que el texto
   se interpola: dejar pasar solo `\w` cierra la puerta a inyección aunque el
   documento sea hostil), sin tildes y con case fijo. Sin lo canónico,
   `Locación` / `Locacion` / `LOCACION` serían tres labels distintos para el
   mismo tipo y ninguna consulta por tipo funcionaría.
4. `neo4j_client.py` — escribe el grafo.

**La identidad de una entidad es su nombre normalizado, no el par
(nombre, tipo).** Como el tipo es libre, el mismo proveedor puede venir como
`Proveedor` en un documento y `Proveedor_de_Catering` en otro; si el tipo
fuera parte de la clave quedarían dos nodos. En cambio se mergea por
`norm_name` (con un constraint de unicidad) y **el tipo se acumula como
label adicional**, así no se pierde ninguno de los dos. Es el mismo problema
que tiene Microsoft GraphRAG por agrupar sus entidades por `(title, type)`
([microsoft/graphrag#1718](https://github.com/microsoft/graphrag/issues/1718)).

Idempotencia: un archivo que cambió no se borra y se recrea como en Qdrant,
porque un nodo puede estar compartido entre varios documentos. Se saca el
`source_id` del archivo de todas las listas y después se recolecta lo que
quedó sin ninguna fuente (`remove_source_contribution`).

Limitación conocida: el fuzzy matching no une entidades que no comparten
texto ("DJ Marco Vidal" vs "Marco Vidal", "Los Sonidos" vs "Los Sonidos
(banda)"). Resolverlo pide resolución semántica con LLM, deliberadamente
diferida para no gastar API en cada ingesta.

