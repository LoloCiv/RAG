# Events RAG POC

Agente conversacional sobre el Google Drive de una empresa de eventos
(historial de eventos, presupuestos, proveedores), con capacidad de generar
gráficos a partir de datos reales. Ver el diseño completo en el plan:
`C:\Users\Laure\.claude\plans\me-gustaria-hacer-la-mutable-pixel.md`.

## Que esta implementado

- Estructura del proyecto, configuración (`app/config.py`)
- Ingesta de Google Drive completa: auth OAuth, listado, PDF/Doc/Sheet/xlsx
  (`app/ingestion/`)
- Manifest para resync idempotente
- Embeddings con Voyage AI (`app/rag/embeddings.py`) y wrapper de Qdrant
  (`app/rag/vector_db.py`)
- Agente Claude con `tool_runner`, `search_knowledge_base` /
  `get_source_table` y generación de gráficos (`app/agent/`)
- UI de Streamlit (`streamlit_app.py`)
- **Capa de grafo de conocimiento** sobre Neo4j (`app/graph/`): en cada
  resync, además de embeber los chunks en Qdrant, se extraen entidades y
  relaciones con Claude y se escriben en un grafo. Corre al lado del camino
  vectorial, no lo reemplaza. Todavía **no** está enganchado al agente de
  chat — eso es el sub-proyecto siguiente.

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
`NEO4J_DATABASE` y `GRAPH_DEDUP_THRESHOLD` (0-100, default `90`: cuán
parecidos tienen que ser dos nombres para tratarlos como la misma entidad).

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

## Tests

```bash
pytest
```

Cubren la lógica pura que no necesita credenciales ni servicios corriendo:
dispatch de mimeType, forma del payload, esquema de `source_id`, parseo de
PDF, y toda la capa de grafo salvo la escritura real (sanitización de Cypher
—incluidos intentos de inyección—, fuzzy matching y la orquestación de
`ingest.py` contra un `graph_store` falso). No reemplazan los smoke tests
manuales del plan (ítem "Verificación") para los flujos que sí dependen de
Drive/Qdrant/Neo4j/Claude reales.
