# Centro de conocimiento para equipos de eventos

Un RAG sobre el Google Drive de una empresa de eventos, pensado como **buzón de
consultas** y no como chatbot: cada pregunta es independiente, se responde con
fuentes verificables y queda registrada. Se usa desde una UI en Streamlit o,
como una tool más, desde cualquier cliente [MCP](https://modelcontextprotocol.io).

> **Proyecto personal / POC.** Los datos de `sample_data/` son **ficticios**:
> los genera `sample_data/generate_samples.py` para una empresa inventada
> ("Eventos Aurora"). Ningún dato real forma parte del repo. Licencia [MIT](LICENSE).

## Qué hace

- **Consultar antecedentes.** Preguntas sobre eventos, presupuestos y proveedores,
  con respuesta citada (archivo + link a Drive) y gráficos cuando hay números.
  Modo *Rápida* para lo cotidiano y *Profunda* para comparaciones y tablas.
  Una consulta puede citar explícitamente otras anteriores.
- **Encontrar eventos similares.** Describís un evento nuevo y recupera hasta
  cinco antecedentes con coincidencias, diferencias, proveedores y costos, donde
  **cada afirmación lleva una cita textual que se verifica contra el fragmento
  recuperado**; lo que no está documentado queda como "no documentado".
- **Eventos.** Espacio compartido que reúne los correos de cada evento en curso
  (Gmail en solo lectura vía n8n, con confirmación humana antes de asociarlos).
- **Servidor MCP.** Una única tool stateless, `query_events_kb`, para integrarlo
  en sistemas más grandes.

## Arquitectura

```
Google Drive ─► ingesta (PDF / Doc / Sheet / xlsx)
                 ├─► Qdrant   vectores (Voyage) + reranking
                 └─► Neo4j    grafo de entidades y relaciones (extraídas con Claude)
                                   │
 Streamlit ─┐                      ▼
 Servidor MCP ┴─► buzón ─► agente Claude (tool_runner)
                              ├─ search_knowledge_base   (vectores + mapa del grafo)
                              ├─ get_source_table        (llamada programática desde code_execution)
                              └─ code_execution          (cálculos y gráficos)

 n8n (Gmail, solo lectura) ─► webhook con Bearer ─► SQLite (eventos y correo compartido)
```

## Decisiones de diseño que vale la pena mirar

- **Buzón en vez de chat.** El historial multi-turno obligaba a reconstruir
  exactamente cada ronda de tool calls; dos bugs reales de historial corrupto
  salieron de ahí. Se reemplazó por consultas *single-shot* con citas explícitas.
  Ver [fases 3 a 5](docs/fases-3-a-5.md).
- **Generación con citas verificables.** Los fragmentos recuperados se tratan como
  datos no confiables (anti prompt-injection) y una cita que no aparece
  literalmente en su fuente invalida la respuesta. Ver [eventos similares](docs/similar-events.md).
- **Costo medido, no supuesto.** Prompt caching, programmatic tool calling y un
  mapa de grafo, evaluados contra un baseline congelado. Una pregunta mejoró
  78 % en tiempo y otra empeoró; se identificó la causa y se mitigó, aunque una
  sola remedición no alcanza para darla por resuelta. Ver
  [optimización del agente](docs/optimizacion-del-agente.md).
- **Modelo elegido por una restricción, no por precio de lista.** El agente
  depende de programmatic tool calling, que Haiku 4.5 no soporta; entre los que
  sí lo soportan, Sonnet 5 era el más barato a septiembre de 2026. La extracción
  del grafo, que no lo usa, corre en Haiku. Ver el
  [análisis](docs/superpowers/specs/2026-09-03-buzon-de-consultas-mcp-design.md).
- **Retrieval evaluado.** Golden set de 14 preguntas: el reranking subió el MRR
  de 0.90 a 1.00 con Recall@k = 1.00. Ver [evaluación](docs/evaluacion-de-retrieval.md).
- **Seguro por defecto.** Servicios atados a `127.0.0.1`, webhook con Bearer
  token, envíos externos deshabilitados (`ENABLE_OUTBOUND=false`) y Gmail de
  solo lectura. Ver [integraciones](docs/integraciones.md).

## Inicio rápido

Requiere Python 3.11+, Docker y claves de Anthropic y Voyage AI.

```bash
python -m venv venv
venv\Scripts\activate
pip install -e .
copy .env.example .env
```

Completá las claves en `.env`, levantá Qdrant y Neo4j (puertos atados a
`127.0.0.1`; elegí tu propia password y ponela también en `NEO4J_PASSWORD`):

```bash
docker run -d -p 127.0.0.1:6333:6333 qdrant/qdrant
docker run -d --name neo4j -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 -e NEO4J_AUTH=neo4j/<tu-password> neo4j:5-community
```

```bash
streamlit run streamlit_app.py
```

La ingesta de Drive necesita credenciales OAuth de Google. La guía completa
(Drive, Neo4j, variables) está en [docs/setup.md](docs/setup.md).

## Tests

```bash
venv\Scripts\python.exe -m pytest -q
```

261 tests. Corren **sin credenciales ni servicios**: todo lo externo está
reemplazado por fakes. Para lo que sí depende de Drive, Qdrant, Neo4j, Voyage y
Claude reales están `scripts/eval_retrieval.py` y `scripts/benchmark_agent.py`.

## Estructura

| Ruta | Qué contiene |
|---|---|
| `app/agent/` | agente, tools, buzón (`inbox.py`) y log de consultas |
| `app/rag/`, `app/graph/` | embeddings, Qdrant, reranking · grafo en Neo4j |
| `app/ingestion/` | Google Drive → chunks, tablas y manifest de resync |
| `app/similar_events/` | búsqueda de antecedentes con citas verificadas |
| `app/collaboration/`, `app/ui/` | eventos y correo compartido · interfaz Streamlit |
| `app/mcp_server.py`, `app/webhook_server.py` | servidor MCP · webhook para n8n |
| `app/operations/` | módulo comercial heredado, fuera de la interfaz |
| `integrations/n8n/` | Docker Compose y workflow del piloto de Gmail |
| `scripts/`, `evals/` | evaluación de retrieval, benchmark y golden sets |
| `docs/` | guías, mediciones y, en `superpowers/`, specs y planes de cada cambio |

## Documentación

[Instalación](docs/setup.md) ·
[Integraciones](docs/integraciones.md) ·
[Espacio por evento](docs/event-workspace.md) ·
[Eventos similares](docs/similar-events.md) ·
[Piloto Gmail con n8n](docs/n8n-gmail-pilot.md) ·
[Capa de grafo](docs/capa-de-grafo.md) ·
[Optimización del agente](docs/optimizacion-del-agente.md) ·
[Evaluación de retrieval](docs/evaluacion-de-retrieval.md) ·
[Fases 3 a 5](docs/fases-3-a-5.md)

## Limitaciones conocidas

- Es un POC de un solo usuario; el servidor MCP serializa los turnos con un lock
  porque el estado por turno es global al módulo. Antes de exponerlo por HTTP con
  varios usuarios hay que moverlo a estado por request.
- Los PDF escaneados no se leen (sin OCR): se ingieren pero quedan marcados.
- El fuzzy matching del grafo no une alias sin texto en común ("DJ Marco Vidal"
  / "Marco Vidal").
- La bandeja comercial con aprobación de borradores quedó como módulo heredado,
  sin pantalla en la interfaz actual.

## Licencia

[MIT](LICENSE).
