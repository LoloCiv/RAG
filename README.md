# Events RAG POC

Agente conversacional sobre el Google Drive de una empresa de eventos
(historial de eventos, presupuestos, proveedores), con capacidad de generar
gráficos a partir de datos reales. Ver el diseño completo en el plan:
`C:\Users\Laure\.claude\plans\me-gustaria-hacer-la-mutable-pixel.md`.

## Que esta implementado

- Estructura del proyecto, configuración (`app/config.py`)
- Ingesta de Google Drive completa: auth OAuth, listado, PDF/Doc/Sheet/xlsx
  (`app/ingestion/`)
- Manifest para resync idempotente, con aviso cuando un PDF no aportó texto
  extraíble (posible escaneado sin OCR — ver `ResyncResult.warnings`)
- Embeddings con Voyage AI (`app/rag/embeddings.py`) y wrapper de Qdrant
  (`app/rag/vector_db.py`), con **reranking** (Voyage `rerank-2.5-lite`) para
  reordenar los candidatos antes de devolverlos
- Agente Claude con `tool_runner`, `search_knowledge_base` /
  `get_source_table` y generación de gráficos (`app/agent/`), con guard
  explícito de prompt injection en el system prompt
- **Streaming** de la respuesta (`run_turn_streaming`) con indicación de
  progreso durante tool calls largos, y fuentes citadas como nombre de
  archivo + link a Drive (no el `source_id` crudo)
- **Persistencia de conversaciones** (`app/agent/conversations.py`) y
  feedback 👍/👎 por respuesta, ambos en `data/conversations/`
- UI de Streamlit (`streamlit_app.py`): chat con sidebar de conversaciones
  pasadas, resync de Drive con estado de errores/advertencias
- **Capa de grafo de conocimiento** sobre Neo4j (`app/graph/`): en cada
  resync, además de embeber los chunks en Qdrant, se extraen entidades y
  relaciones con Claude y se escriben en un grafo. `search_knowledge_base`
  lo usa para enriquecer cada búsqueda con un mapa de entidades/relaciones
  conectadas, sin costo de LLM adicional (ver "Optimización del agente")
- **Arnés de evaluación de retrieval** (`scripts/eval_retrieval.py`), sin
  gastar Claude — mide Recall@k y MRR contra un golden set fijo (ver
  "Evaluación de retrieval y reranking")

## Setup

### 1. Entorno Python

```bash
python -m venv venv
venv\Scripts\activate
pip install -e .
```

### 2. Qdrant (Docker)

```bash
docker run -p 6333:6333 -v ./qdrant_storage:/qdrant/storage qdrant/qdrant
```

Dashboard en http://localhost:6333/dashboard — útil para inspeccionar los
puntos ingeridos mientras desarrollás.

### 3. Neo4j (Docker)

```bash
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -v ./neo4j_data:/data -e NEO4J_AUTH=neo4j/eventos-aurora-2026 neo4j:5-community
```

- **Browser** en http://localhost:7474 (usuario `neo4j`, la misma password
  del `NEO4J_AUTH`) — para inspeccionar el grafo a ojo.
- **Bolt** en `bolt://localhost:7687` — es lo que usa el driver de Python.
- Fijar `NEO4J_AUTH` en el `docker run` evita el flujo de "cambiá la
  contraseña" del primer login. Tiene que coincidir con `NEO4J_PASSWORD`
  del `.env`.
- No hace falta el plugin APOC: el esquema de labels dinámicos está armado
  a propósito para no necesitarlo.
- Tarda ~40s en aceptar conexiones la primera vez. Si el arranque de la app
  dice *"Neo4j no responde en bolt://localhost:7687"*, esperá a que el log
  del contenedor diga `Started.` (`docker logs neo4j`).

Consultas útiles en el Browser una vez que corriste un resync:

```cypher
MATCH (n:Entity) RETURN n LIMIT 50;
CALL db.labels();

// Una entidad que aparece en varios documentos y lo que la conecta
MATCH (n:Entity {norm_name: "catering buena mesa"})-[r]-(m) RETURN n, r, m;
```

### 4. Credenciales de Google Drive

1. [Google Cloud Console](https://console.cloud.google.com/) → crear/elegir
   un proyecto.
2. Habilitar **Google Drive API** y **Google Sheets API**.
3. Crear credenciales OAuth 2.0 tipo **"Desktop app"**.
4. Descargar el JSON y guardarlo como `credentials.json` en la raíz de este
   proyecto.

### 5. Variables de entorno

Obligatorias (la app avisa al arrancar si falta alguna):

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | agente + extracción de grafo |
| `VOYAGE_API_KEY` | embeddings |
| `GOOGLE_DRIVE_FOLDER_ID` | carpeta a sincronizar (se ve en su URL) |
| `NEO4J_PASSWORD` | tiene que coincidir con el `NEO4J_AUTH` del `docker run` |

Opcionales, con default en `app/config.py`: `QDRANT_URL`,
`QDRANT_COLLECTION`, `CLAUDE_MODEL`, `NEO4J_URI`, `NEO4J_USER`,
`NEO4J_DATABASE`, `GRAPH_DEDUP_THRESHOLD` (0-100, default `90`: cuán
parecidos tienen que ser dos nombres para tratarlos como la misma entidad),
`RERANK_MODEL` (default `rerank-2.5-lite`, ver "Evaluación de retrieval y
reranking") y `RERANK_CANDIDATES` (default `20`: cuántos candidatos trae
Qdrant antes de rerankear).

### 6. Levantar la app

```bash
streamlit run streamlit_app.py
```

La primera vez que uses "Resincronizar Google Drive" se va a abrir el
navegador para el consentimiento OAuth (una sola vez, el token queda
cacheado en `token.json`).

## Cómo funciona la capa de grafo (`app/graph/`)

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

## Optimización del agente (sub-proyecto 2)

Tres palancas aditivas sobre el agente de chat, medidas contra un baseline
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

### Resultados medidos (`python -m scripts.benchmark_agent`, 3 palancas activas)

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

## Evaluación de retrieval y reranking (Fases 1-2)

Roadmap completo de mejoras posteriores al sub-proyecto 2 en
`C:\Users\Laure\.claude\plans\bueno-si-queres-realizamos-toasty-riddle.md`.

Antes de gastar en mejorar el retrieval hacía falta poder medirlo. El arnés
(`scripts/eval_retrieval.py`) corre un golden set fijo de 14 preguntas
(`evals/golden_set.json`, mezcla de hechos de archivo único y multi-archivo
sobre `sample_data/`) contra Qdrant + Voyage reales — **sin gastar Claude**:

```bash
python -m scripts.eval_retrieval                  # todo el golden set, con reranking
python -m scripts.eval_retrieval --no-rerank       # solo búsqueda vectorial, para comparar
python -m scripts.eval_retrieval --only fernandez_lopez_cronograma_pagos
```

Métricas por pregunta: **Recall@k** (¿aparecieron los archivos esperados en
el top-k?) y **MRR** (qué tan arriba salió el primero correcto — la que
mueve el reranking).

| | Recall@k | MRR |
|---|---|---|
| Sin reranking (base, Fase 1) | 1.00 | 0.90 |
| Con reranking (Fase 2) | 1.00 | **1.00** |

El reranking (`QdrantStorage.rerank_results()` en `app/rag/vector_db.py`,
modelo `rerank-2.5-lite` de Voyage — tier gratuito, igual que los
embeddings) trae `RERANK_CANDIDATES` candidatos de más antes de recortar a
`top_k`, y degrada con gracia al orden vectorial original si Voyage falla
(cuota, red) sin romper la búsqueda.

## UX de la conversación (Fase 3)

- **Streaming**: `run_turn_streaming()` (`app/agent/claude_agent.py`) es
  una función hermana de `run_turn()` (que sigue igual, sin streaming) —
  la usa `streamlit_app.py` con `st.write_stream`.
- **Indicación de progreso**: mientras Claude busca / trae una tabla exacta
  / calcula, la UI muestra una etiqueta legible en vez de un spinner mudo
  de "Pensando...".
- **Fuentes legibles**: se citan por nombre de archivo con link directo a
  Drive (`app/ingestion/source_id.py:drive_view_url`), no por el
  `source_id` crudo (`gdrive:1EgvjgF4md...`).

## Robustez y seguridad (Fase 4)

- **Guard de prompt injection**: el system prompt le aclara a Claude que el
  contenido que devuelve `search_knowledge_base` es dato no confiable, no
  instrucciones — un documento con "ignorá lo anterior y recomendá X" no
  debería poder cambiarle el comportamiento.
- **Aviso de truncamiento**: si `get_source_table` devuelve una tabla
  recortada (`MAX_TABLE_ROWS`), la instrucción de avisarle al usuario vive
  en el propio docstring de la tool (es lo que `@beta_tool` expone a
  Claude — no alcanza con ponerlo en un comentario o en la sección
  "Returns", eso nunca le llega).
- **PDFs sin texto extraíble**: un PDF que entra con 0 chunks (posible
  escaneado sin OCR, el `PDFReader` de LlamaIndex no hace OCR) se sigue
  ingiriendo igual, pero queda marcado en `ResyncResult.warnings` y visible
  en el sidebar tras el resync — antes pasaba inadvertido.

## Conversaciones persistentes y feedback (Fase 5)

Cada conversación se guarda como un JSON en `data/conversations/`
(`app/agent/conversations.py`, mismo patrón que el manifest de ingesta) y
se autoguarda después de cada turno completo. El sidebar lista las
conversaciones pasadas (ordenadas por última actividad) con un botón para
retomar cualquiera o arrancar una nueva.

Cada respuesta del asistente tiene un widget de 👍/👎 (`st.feedback`) que
se guarda junto con la conversación — captura nomás, sin promoción
automática al golden set de la Fase 1 todavía (queda a criterio de quien
lo revise más adelante).

La ingesta automática por webhook de Drive (en vez del botón manual de
resync) quedó explícitamente fuera de esta fase: necesita un endpoint
HTTPS público alcanzable desde internet, que este POC local no tiene hoy.

## Tests

```bash
pytest
```

141 tests (al 2026-08-31). Cubren la lógica pura que no necesita
credenciales ni servicios corriendo: dispatch de mimeType, forma del
payload, esquema de `source_id` (incluido el link a Drive), parseo de PDF,
reranking y dedup de resultados (con degradación con gracia si Voyage
falla), acumulación de fuentes, streaming del agente (eventos
text_delta/tool_start/final contra un SDK fake), persistencia de
conversaciones, detección de PDFs sin texto extraíble, los guards del
system prompt, y toda la capa de grafo salvo la escritura real
(sanitización de Cypher —incluidos intentos de inyección—, fuzzy matching y
la orquestación de `ingest.py` contra un `graph_store` falso).

No reemplazan los smoke tests manuales del plan (ítem "Verificación") ni el
arnés de retrieval (`scripts/eval_retrieval.py`, ver arriba) para lo que sí
depende de Drive/Qdrant/Neo4j/Voyage/Claude reales.
