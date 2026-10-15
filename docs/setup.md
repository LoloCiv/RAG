# Guía de instalación

Paso a paso para levantar el proyecto completo (ingesta, agente y UI). Las
variables de entorno de referencia están en [`.env.example`](../.env.example).

## 1. Entorno Python

```bash
python -m venv venv
venv\Scripts\activate
pip install -e .
```

## 2. Qdrant (Docker)

```bash
docker run -p 127.0.0.1:6333:6333 -v ./qdrant_storage:/qdrant/storage qdrant/qdrant
```

Dashboard en http://localhost:6333/dashboard — útil para inspeccionar los
puntos ingeridos mientras desarrollás.

Los puertos se publican solo en `127.0.0.1` a propósito: Qdrant no trae
autenticación por defecto, y un `-p 6333:6333` pelado lo expone en todas las
interfaces de la máquina.

## 3. Neo4j (Docker)

```bash
docker run -d --name neo4j -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 -v ./neo4j_data:/data -e NEO4J_AUTH=neo4j/<elegi-una-password> neo4j:5-community
```

- **Browser** en http://localhost:7474 (usuario `neo4j`, la misma password
  del `NEO4J_AUTH`) — para inspeccionar el grafo a ojo.
- **Bolt** en `bolt://localhost:7687` — es lo que usa el driver de Python.
- Reemplazá `<elegi-una-password>` por una propia (no la reutilices de otro
  servicio). Fijar `NEO4J_AUTH` en el `docker run` evita el flujo de
  "cambiá la contraseña" del primer login, y tiene que coincidir con
  `NEO4J_PASSWORD` del `.env`.
- Los puertos quedan atados a `127.0.0.1`: el grafo contiene el contenido
  extraído de tus documentos y no debería ser alcanzable desde la red.
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

## 4. Credenciales de Google Drive

1. [Google Cloud Console](https://console.cloud.google.com/) → crear/elegir
   un proyecto.
2. Habilitar **Google Drive API** y **Google Sheets API**.
3. Crear credenciales OAuth 2.0 tipo **"Desktop app"**.
4. Descargar el JSON y guardarlo como `credentials.json` en la raíz de este
   proyecto.

## 5. Variables de entorno

Obligatorias (la app avisa al arrancar si falta alguna):

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | agente + extracción de grafo |
| `VOYAGE_API_KEY` | embeddings |
| `GOOGLE_DRIVE_FOLDER_ID` | carpeta a sincronizar (se ve en su URL) |
| `NEO4J_PASSWORD` | tiene que coincidir con el `NEO4J_AUTH` del `docker run` |
| `N8N_WEBHOOK_TOKEN` | Bearer token para el webhook local de operaciones |

Opcionales, con default en `app/config.py`: `QDRANT_URL`,
`QDRANT_COLLECTION`, `CLAUDE_MODEL`, `NEO4J_URI`, `NEO4J_USER`,
`NEO4J_DATABASE`, `GRAPH_DEDUP_THRESHOLD` (0-100, default `90`: cuán
parecidos tienen que ser dos nombres para tratarlos como la misma entidad),
`RERANK_MODEL` (default `rerank-2.5-lite`, ver "Evaluación de retrieval y
reranking"), `RERANK_CANDIDATES` (default `20`: cuántos candidatos trae
Qdrant antes de rerankear), `EXTRACTION_MODEL` y `OPERATIONS_MODEL`
(ambos Haiku por defecto para extracción, clasificación y borradores).

## 6. Levantar la app

```bash
streamlit run streamlit_app.py
```

La primera vez que uses "Resincronizar Google Drive" se va a abrir el
navegador para el consentimiento OAuth (una sola vez, el token queda
cacheado en `token.json`).
