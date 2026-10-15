# Optimización del agente (sub-proyecto 2)

Tres palancas aditivas sobre el agente, medidas contra un baseline
congelado (dos preguntas reales, agente sin ninguna palanca aplicada):

1. **Prompt caching** (`app/agent/claude_agent.py`): la API es stateless y
   reenvía todo el historial en cada round-trip. Un solo parámetro
   (`cache_control`) activa caching automático, que baja el costo de ese
   re-envío (las lecturas de caché facturan a 0.1× el precio normal).
2. **Programmatic tool calling** (`app/agent/tools.py`): `get_source_table`
   se llama desde el código que escribe Claude en `code_execution`, no
   directo -- las tablas completas ya no entran al contexto de la
   conversación, solo el resultado que el código calcula.
3. **Grafo de conocimiento** (`app/graph/retrieval.py` +
   `app/graph/neo4j_client.py`): `search_knowledge_base` devuelve, además
   de los chunks, un mapa compacto de las entidades y relaciones conectadas
   a esos documentos -- sin costo de LLM ni round-trips nuevos.

## Resultados medidos (`python -m scripts.benchmark_agent`, 3 palancas activas)

| Pregunta | Métrica | Baseline | Medido | Cambio |
|---|---|---|---|---|
| **proveedor** | tiempo | 87,8 s | 19,6 s | **-78%** |
| | round-trips | 3 | 3 | +0% |
| | tool calls | 4 | 3 | -25% |
| | tokens totales (in + cache) | 43.783 | 48.046 | +10% |
| | **costo ponderado de entrada*** | 43.783 | **37.364** | **-15%** |
| **planificación** | tiempo | 43,3 s | 110,5 s | +155% |
| | round-trips | 3 | 6 | +100% |
| | tool calls | 6 | 14 | +133% |
| | tokens totales (in + cache) | 65.499 | 319.772 | +388% |
| | **costo ponderado de entrada*** | 65.499 | **74.620** | **+14%** |

\* *Costo ponderado* pondera lecturas de caché a 0,1× y escrituras a 1,25×
(precios reales de la API). Es solo de entrada -- excluye `tokens_out`
porque el baseline congelado nunca lo capturó (sus entradas en `BASELINE`
tienen `tokens_out: 0` con un comentario aclarando que no se capturó al
congelar, ver `scripts/benchmark_agent.py`) -- y es la única columna
comparable 1:1 contra el baseline: el baseline no usaba caching, así que ahí
tokens totales == costo.
El conteo crudo de `tokens_in` de la API por sí solo cae a valores de un
dígito una vez que el caching está activo (porque ya no cuenta los tokens
servidos desde caché), lo que produciría un "-100%" engañoso si se lo
comparara directo contra el baseline -- por eso esta tabla usa tokens
totales y costo ponderado, no `tokens_in` crudo.

**La pregunta "proveedor" es el caso que motivó la palanca 3** (ver spec,
sección "Contexto"): en el baseline, esa pregunta encadenaba 4 búsquedas
semánticas a ciegas para descubrir que "Catering Buena Mesa" trabajó en dos
casamientos más. Con el grafo, esas conexiones llegan en el mismo
`search_knowledge_base` que trae los chunks -- de ahí el -78% de tiempo con
la misma cantidad de round-trips.

**La pregunta "planificación" no era el caso objetivo de la palanca 3** --
el spec ya señalaba que sus 3 round-trips eran eficientes por la
paralelización del SDK. Medido dos veces más para confirmar que no era un
outlier (la misma pregunta se volvió a medir dos veces más: la segunda
corrida dio +185% de tokens totales y -23% de costo ponderado; la oficial
de la tabla de arriba dio +388% de tokens y +14% de costo), la causa está
identificada: el bloque de mapa se calibró (`GRAPH_MAX_ANCHORS`/
`GRAPH_MAX_EDGES` en `app/config.py`) mirando una sola entidad muy conectada
del corpus ("Catering Buena Mesa", 11 aristas), pero una pregunta amplia como
esta toca 5 entidades ancla a la vez, cada una aportando sus propias
aristas -- el bloque real mide ~970 tokens por llamada contra el presupuesto
de 200-400 que asumía un solo ancla. Además, cuando el mismo turno dispara
varias búsquedas en paralelo sobre entidades solapadas (algo que el SDK ya
hacía antes de este sub-proyecto), cada una arrastra su propia copia del
mapa, duplicando ese costo sin aportar información nueva.

Ninguno de los dos casos perdió calidad de respuesta: se revisaron a mano
las respuestas completas de ambas preguntas contra las fuentes citadas y el
contenido real del corpus -- los datos, las citas y las conclusiones son
correctos, y el agente es explícito sobre lo que no encuentra en vez de
inventarlo.

**Actualización — implementado**: los dos ítems de arriba (dedup del mapa
entre búsquedas paralelas del mismo turno, y un presupuesto real de tamaño
en vez de topes de cantidad) se implementaron después de esta medición. Con
`GRAPH_MAX_CHARS` (`app/config.py`) cortando anclas completas apenas el
bloque supera ~400 tokens, más `_mapa_anchors_shown` (`app/agent/tools.py`)
evitando repetir una ancla ya mostrada en el turno:

- **Sin gastar API de Claude** (solo Qdrant + Neo4j + embeddings): las dos
  búsquedas en paralelo de "planificación" pasaron de ~7.770 caracteres
  combinados (~1.942 tokens) a **2.475 caracteres (~618 tokens)**, una baja
  del 68%. "proveedor" no se vio afectado -- su mapa sigue dentro del
  presupuesto original.
- **Remedido con el benchmark completo** (`python -m scripts.benchmark_agent
  planificacion`): costo ponderado -24% contra el baseline (mejor que las
  tres corridas anteriores: +14%, -23% y -23%). Los tokens totales crudos
  siguen altos en esta corrida puntual (+169%) porque el agente decidió
  explorar varias tablas -- esa variabilidad es del propio
  `thinking=adaptive` y de cuántas tablas decide pedir cada vez, no algo
  que este arreglo del mapa controle. Con una sola corrida post-arreglo no
  alcanza para declarar el caso resuelto, pero la dirección es consistente
  con la causa raíz identificada.

Se evaluó (y se descartó) migrar el agente principal o la extracción de
entidades a un modelo local (la máquina de desarrollo tiene una RTX 5060 de
8GB vía Ollama): el ahorro de estas tres palancas viene de reducir el
*costo por token* (caching) y la *cantidad de tokens reenviados* (PTC y
grafo), no el precio por token, y un modelo local en el agente principal
sería más lento con el volumen de contexto que maneja hoy. Detalle completo
en `docs/superpowers/specs/2026-08-31-optimizacion-agente-design.md`.

