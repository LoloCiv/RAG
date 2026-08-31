# Sub-proyecto 2: optimizar el trabajo del agente

## Contexto

El sub-proyecto 1 dejó construido y poblado el grafo de conocimiento en Neo4j
(108 entidades, 179 relaciones sobre los 12 documentos de prueba), pero
deliberadamente **sin conectarlo al agente de chat**. Este sub-proyecto era,
en el plan original, "enganchar el grafo al agente para acelerar el
retrieval".

**Medir el problema cambió el diseño.** Antes de proponer nada se instrumentó
el agente actual con dos preguntas reales:

| Pregunta | Tiempo | Round-trips | Tool calls | Tokens entrada |
|---|---|---|---|---|
| "Planifico un casamiento de 150 invitados con presupuesto ajustado. ¿Qué me sirve de eventos pasados? ¿Qué proveedores y cuánto costaron?" | 43,3 s | 3 | 6 | 65.499 |
| "¿Cómo viene funcionando Catering Buena Mesa? ¿En qué eventos participó y qué se dijo de él?" | 87,8 s | 3 | 4 | 43.783 |

Dos hallazgos que corrigen la premisa del plan original:

1. **No son 4-5 round-trips secuenciales, son 3.** El SDK ya paraleliza las
   tool calls dentro de un mismo turno. La premisa de "4-5 viajes de ida y
   vuelta" era incorrecta.

2. **El costo real es el re-envío, no el descubrimiento.** Desglosando el
   contenido de cada tool result de la primera pregunta:

   | Concepto | Tokens |
   |---|---|
   | `search_knowledge_base` × 2 | 7.999 |
   | `get_source_table` × 3 | 5.843 |
   | **Contenido único total** | **13.842** |
   | Facturado en el baseline | 65.499 |
   | **Factor de re-envío** | **4,7×** |

   La API es stateless: cada round-trip reenvía todo el historial. **El 79%
   de los tokens facturados no es información nueva.**

Sí se confirmó el problema que motivaba el grafo, pero en la *segunda*
pregunta, no en la primera. Su secuencia de búsquedas fue:

```
1. "Catering Buena Mesa proveedor"
2. "Buena Mesa evaluación desempeño"
3. "Casamiento Garcia-Nunez reporte post-evento catering"   <- salió del resultado 1
4. "Cumpleanos 40 Laura Diaz catering feedback"             <- salió del resultado 1
```

Eso es un recorrido de grafo hecho a mano con búsqueda semántica, un salto
por vez. El grafo ya tiene esas aristas precomputadas.

## Objetivo

Reducir tokens de entrada y latencia **sin perder calidad de respuesta**.
El criterio de éxito es medible contra el baseline congelado de arriba.

Decisiones ya tomadas (no reabrir):

- **Tres palancas, en orden de impacto**, midiendo entre cada una para saber
  qué aportó cada cambio y no un antes/después borroso.
- **No se cambia de modelo ni se introducen modelos locales.** Se evaluó
  (la máquina tiene Ollama y una RTX 5060 de 8 GB) y se descartó: el ahorro
  que se busca viene de reducir la *cantidad* de tokens, no el precio por
  token. Un modelo local en el agente principal implicaría 43k tokens de
  contexto en un 8B con 8 GB de VRAM — más lento y peor. Un local en la
  extracción de ingesta arriesgaría el cimiento del grafo por centavos.
- **El grafo no reemplaza la búsqueda vectorial, la orienta.** El grafo dice
  qué documentos están conectados con qué; el texto sigue viniendo de Qdrant.
- Todo es **aditivo**: no se toca la ingesta ni el pipeline del
  sub-proyecto 1.

Fuera de alcance (siguen diferidos a sub-proyectos posteriores): split
multi-agente, detección de comunidades, resúmenes globales, visualización del
grafo, embeddings locales.

## Palanca 1: prompt caching

Ataca el 79% de re-envío. Es la única de las tres con **riesgo de calidad
cero**: la respuesta es idéntica, solo cambia lo que se factura.

En `app/agent/claude_agent.py`, sumar al `tool_runner` (ya acepta el
parámetro, verificado contra el SDK instalado):

```python
runner = client.beta.messages.tool_runner(
    ...,
    cache_control={"type": "ephemeral"},
)
```

Caching automático: el sistema coloca el breakpoint en el último bloque
cacheable y lo mueve hacia adelante a medida que crece la conversación. Es el
patrón recomendado para loops multi-turno, sin llevar contabilidad de
breakpoints a mano.

**Detalle a verificar al implementar**: hay un mínimo de tokens para que un
prefijo sea cacheable (depende del modelo). El system prompt (331 tokens) más
las definiciones de tools (427) suman 758, así que el primer round-trip
probablemente no cachee. El segundo y el tercero sí — y ahí es donde está el
re-envío que interesa.

**Cómo se verifica**: `usage.cache_read_input_tokens` mayor a cero a partir
del segundo round-trip. Si da cero en llamadas repetidas, algo está
invalidando el prefijo.

## Palanca 2: programmatic tool calling

Hoy `get_source_table` vuelca 5.843 tokens de tablas crudas al contexto para
que Claude calcule y grafique. Con programmatic tool calling, Claude escribe
un script que **invoca la tool desde adentro del sandbox de ejecución**: la
tabla va al código, no al contexto, y solo vuelve el resultado.

Es el caso de uso que la documentación de Anthropic describe textualmente:
resultados intermedios grandes que conviene filtrar antes de que lleguen a la
ventana de contexto.

Cambios en `app/agent/tools.py`:

- `CODE_EXECUTION_TOOL` pasa de `code_execution_20260521` a
  `code_execution_20260120` (la variante que soporta llamadas programáticas;
  requiere Sonnet 4.5+, y el proyecto usa `claude-sonnet-5`).
- `get_source_table` se declara con
  `allowed_callers: ["code_execution_20260120"]`.

Y en `claude_agent.py`, el system prompt indica que para números exactos y
gráficos la tabla se pide **desde el código**, no al contexto.

**Restricciones conocidas** (de la doc del SDK): no es compatible con
`strict: true`, `disable_parallel_tool_use`, ni `tool_choice` forzado —
ninguno se usa hoy. Cuando hay una llamada programática pendiente, el mensaje
de usuario debe contener *solo* bloques `tool_result`.

**Riesgo**: es la palanca que toca el camino de gráficos, que hoy funciona.
Por eso va segunda y no primera. Se verifica pidiendo un gráfico y
confirmando que sale igual que antes.

## Palanca 3: el grafo

Ataca la segunda pregunta del baseline (88 s, cuatro búsquedas encadenadas
descubriendo a ciegas).

### `app/graph/neo4j_client.py` — dos métodos de lectura

Ojo: la entrada NO es texto libre. Las entidades ancla se resuelven a partir
de los `source_ids` que ya trae `result["sources"]` de
`search_knowledge_base` (ver "Cómo se eligen las entidades ancla" abajo), así
que no hace falta fuzzy matching por nombre acá — eso ya lo resolvió la
ingesta en el sub-proyecto 1.

```python
def anchors_by_source_ids(self, source_ids: list[str], limit: int) -> list[dict]:
    """Entidades que tienen AL MENOS uno de estos source_ids, ordenadas por
    cantidad total de documentos que tocan (las mas conectadas primero)."""

def neighborhood(self, norm_names: list[str], limit: int) -> list[dict]:
    """Aristas donde el origen o el destino es uno de estos nodos (por
    norm_name), con los source_ids de cada arista. Ordenadas por cuantos
    documentos evidencian cada relacion."""
```

### `app/graph/retrieval.py` — nuevo, funciones puras

Convierte el resultado crudo de Neo4j en el bloque compacto que ve Claude.
Puro a propósito: es donde vive el presupuesto de tokens y se testea sin
Neo4j vivo, igual que `dedup.py` y `cypher.py` en el sub-proyecto 1.

Formato, pensado para pesar poco (~200 tokens contra los ~4.000 que cuesta
una búsqueda de chunks):

```
Catering Buena Mesa [Proveedor_de_catering] (6 docs)
  -CONTRATADO_PARA-> Casamiento Perez-Gomez (gdrive:abc)
  -EN_EVALUACION_PARA-> Casamiento Fernandez-Lopez (gdrive:def)
```

Con tope explícito de aristas y de entidades ancla, configurable en
`app/config.py`: `GRAPH_MAX_ANCHORS` (default 5) y `GRAPH_MAX_EDGES`
(default 40). Los defaults salen del tamaño del grafo real: 40 aristas
cubren con margen las 11 del nodo más conectado del corpus actual
("Catering Buena Mesa"), y mantienen el bloque en el orden de los 200-400
tokens que justifica la palanca. Si el benchmark muestra que el mapa se
corta en casos útiles, se suben.

### Cómo se eligen las entidades ancla

Sin LLM y sin costo, usando datos que ya existen:

1. Los chunks que devolvió Qdrant traen sus `source_ids`.
2. El grafo sabe qué entidades tienen esos `source_ids` (ya se guardan desde
   el sub-proyecto 1).
3. Se ordenan por cuántos documentos toca cada una — las más conectadas
   primero, que son las que más sirven para orientar.
4. Se cortan en `GRAPH_MAX_ANCHORS`.

### Integración

`search_knowledge_base` en `app/agent/tools.py` devuelve, junto a los
`contexts` y `sources` de siempre, un campo `mapa` con ese bloque. No se
agrega ninguna tool nueva ni ningún round-trip.

**`explore_entity` queda explícitamente fuera de alcance.** Se consideró
(el agente pidiendo el vecindario de una entidad deliberadamente) y se
descartó por YAGNI: si el mapa funciona, el agente ya lo recibe y nunca la
necesitaría, y una tool que no se usa igual paga su descripción en cada
llamada. Se reconsidera solo si la medición muestra que hace falta.

## Arnés de medición

`scripts/benchmark_agent.py`, en el repo y no en un temporal, porque la
medición es parte del entregable y hay que poder re-correrla entre palancas.

- Corre las dos preguntas del baseline contra el agente real.
- Reporta: tiempo total, round-trips, lista de tool calls, tokens de entrada
  y salida, y el desglose de caché (`cache_read_input_tokens` /
  `cache_creation_input_tokens`).
- Imprime la comparación contra el baseline congelado.

Baseline congelado (agente actual, antes de cualquier palanca):

| Pregunta | Tiempo | Round-trips | Tool calls | Tokens in |
|---|---|---|---|---|
| Planificación | 43,3 s | 3 | 6 | 65.499 |
| Proveedor | 87,8 s | 3 | 4 | 43.783 |

## Manejo de errores

Cada palanca cae con gracia y por separado:

- **Neo4j caído**: `search_knowledge_base` devuelve los chunks sin `mapa` y
  loguea el fallo. El agente sigue funcionando exactamente como hoy — el
  grafo es una mejora, no un requisito. Mismo criterio que el sidebar de
  Streamlit del sub-proyecto 1.
- **Caching**: no tiene modo de falla propio. Si el prefijo no llega al
  mínimo cacheable, simplemente no cachea y se factura como hoy.
- **Programmatic tool calling**: si el cambio de modalidad rompe la
  generación de gráficos, se revierte solo esa palanca (es un cambio
  localizado en `CODE_EXECUTION_TOOL` y el decorador de `get_source_table`).

## Verificación

**Automatizada (pytest, sin servicios vivos):**

- `retrieval.py`: armado del bloque compacto, respeto de los topes de aristas
  y anclas, orden de las entidades ancla por cantidad de documentos, y el
  caso de grafo vacío (no debe romper ni devolver ruido).
- Selección de anclas a partir de `source_ids`, con un store falso — mismo
  estilo que `test_graph_ingest.py`.
- `search_knowledge_base` con Neo4j caído: devuelve chunks y no explota.

**Manual / de integración (con servicios vivos):**

- `scripts/benchmark_agent.py` después de cada palanca, comparando contra el
  baseline.
- Un pedido de gráfico de punta a punta después de la palanca 2, confirmando
  que el gráfico sale igual.
- Revisar a ojo que las respuestas del benchmark sigan citando las fuentes
  correctas: el objetivo es menos tokens **sin perder calidad**, y eso último
  no lo mide un contador.

## Orden de construcción

1. **Arnés primero**: `scripts/benchmark_agent.py`, y confirmar que reproduce
   el baseline congelado. Sin esto no se puede atribuir mejora a nada.
2. **Palanca 1 (caching)**: una línea, medir, confirmar
   `cache_read_input_tokens > 0`.
3. **Palanca 2 (programmatic tool calling)**: cambiar la modalidad, medir,
   verificar que el gráfico sigue saliendo.
4. **Palanca 3 (grafo)**: `neo4j_client` → `retrieval.py` con TDD →
   integración en `search_knowledge_base` → system prompt → medir.
5. **Documentar** en el README los resultados medidos de cada palanca.

## Archivos críticos

- `app/agent/claude_agent.py` — caching y system prompt
- `app/agent/tools.py` — las tres palancas convergen acá
- `app/graph/neo4j_client.py` — métodos de lectura nuevos
- `app/graph/retrieval.py` — nuevo
- `app/config.py` — `GRAPH_MAX_EDGES`, `GRAPH_MAX_ANCHORS`
- `scripts/benchmark_agent.py` — nuevo
