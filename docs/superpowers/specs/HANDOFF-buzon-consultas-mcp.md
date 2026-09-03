Retomo trabajo en el proyecto RAG en
`C:\Users\Laure\Desktop\RAG\events-rag-poc` (repo git, rama
`buzon-consultas-mcp`, creada desde `main`, ya tiene 1 commit con la
spec — no está mergeada ni pusheada).

Hay una spec de diseño ya escrita, commiteada y **aprobada por mí**
(vino de una sesión de brainstorming completa: exploración del código,
preguntas, 2-3 approaches considerados, decisiones con sus razones) en:

    docs/superpowers/specs/2026-09-03-buzon-de-consultas-mcp-design.md

Léela completa primero — tiene el contexto completo (por qué se
abandona el chat conversacional por un "buzón de consultas" stateless,
con evidencia de dos bugs reales que costó arreglar en esta misma
semana por culpa del historial multi-turno), y el diseño detallado de
4 fases:

1. **Buzón**: reemplaza el chat de Streamlit por consulta única
   stateless. Nuevo módulo `app/agent/queries.py` (log de consultas
   append-only), se borra `app/agent/conversations.py`.
2. **Citar consultas previas**: como "responder citando" de WhatsApp
   pero con un selector (`st.multiselect`, no autocomplete `@` real —
   ver por qué en la spec §2.2). Nuevo módulo `app/agent/inbox.py`.
3. **Servidor MCP**: expone el buzón como una tool MCP (`query_events_kb`)
   vía stdio, consumible desde Claude Desktop/Code o un sistema más
   grande. Incluye la decisión de reentrancia (lock global, con las 2
   alternativas descartadas y por qué) y la verificación de que el SDK
   `mcp` no tiene el problema de DLL nativa que ya nos jorobó una vez
   con `voyageai`.
4. **Modelo/costo**: YA INVESTIGADA Y RESUELTA con fuentes oficiales.
   Conclusión: el agente ya está en el modelo óptimo (Sonnet 5 es el
   más barato que soporta programmatic tool calling, que el proyecto
   necesita). La única acción real es separar el modelo de extracción
   de entidades del grafo (que no usa PTC) a Haiku 4.5 — más barato,
   cero impacto en el agente.

La spec tiene, para cada fase: archivos exactos a crear/modificar/
borrar, interfaces con firmas completas, el esquema JSON exacto de
cada registro, decisiones con sus razones (y qué alternativas se
descartaron y por qué), lista de tests a escribir por nombre, riesgos
explícitos, y una sección "Lo que NO hacer" para no reabrir decisiones
ya tomadas.

**Importante — convención de naming del proyecto** (está al principio
de la spec, no te la saltees): identificadores en inglés
(`search_knowledge_base`, `answer_text`, `run_turn`), docstrings/
comentarios/mensajes de log/texto de UI en español explicando el *por
qué*. Mantenela.

Seguí desde acá:

1. Usá el skill `superpowers:writing-plans` para convertir esa spec en
   un implementation plan con pasos TDD bien granulares (test que
   falla → implementación mínima → verde → commit), guardado en
   `docs/superpowers/plans/YYYY-MM-DD-buzon-de-consultas-mcp.md`. La
   spec ya trae casi todo lo que ese skill pide (interfaces, archivos,
   tests por nombre) — el trabajo real ahí es convertir cada test
   nombrado en código real de test.
2. Ejecutá las Fases 1-3 en orden, TDD estricto, con
   `superpowers:executing-plans` o `superpowers:subagent-driven-development`
   (tu criterio). Corré los tests con
   `./venv/Scripts/python.exe -m pytest -q` — el Python global del
   sistema NO tiene las dependencias del proyecto, usá ese venv
   siempre.
3. La Fase 4 (modelo) es un cambio chico y ya resuelto — el único
   trabajo real es el ítem 1 de esa fase (separar `EXTRACTION_MODEL` de
   `CLAUDE_MODEL`), con su test. No hace falta re-investigar nada.
4. Al cerrar cada fase (suite completa en verde), avisame el resultado
   antes de seguir con la siguiente — mismo patrón que usé en la
   sesión anterior (arreglo de los dos bugs de historial multi-turno:
   TDD por tarea → suite completa → aviso → yo decido merge).
5. Antes de tocar Streamlit en vivo para verificar (Fases 1-2) o de
   conectar el server MCP (Fase 3), fijate que Docker tenga arriba los
   contenedores `neo4j` y `frosty_lalande` (`docker ps`; `docker start`
   si están "Exited") — gotcha que ya hizo perder tiempo antes.
6. Para levantar la app en vivo con el Browser tool: ya existe
   `run_streamlit.bat` en la raíz del proyecto y un
   `.claude/launch.json` apuntándole (en
   `C:\Users\Laure\Desktop\RAG\.claude\launch.json`, fuera del repo).
   Si no está, recrealo: `.bat` que hace `cd /d` a la raíz del
   proyecto y corre `venv\Scripts\python.exe -m streamlit run
   streamlit_app.py --server.headless true`. Ojo: Streamlit cachea
   módulos en `sys.modules` — al tocar código bajo `app/`, hay que
   reiniciar el server (parar y volver a levantar), no alcanza con
   recargar la página.

No pushees nada a `origin` sin que yo lo pida explícitamente.
