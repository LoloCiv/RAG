# Espacio por evento y antecedentes históricos

## Recorrido de la primera entrega

1. En **Eventos**, crear o elegir un evento activo.
2. En **Por revisar**, abrir el correo completo y confirmar el evento sugerido
   o seleccionar otro evento activo. Los correos sin sugerencia están en
   **Correos sin asignar**, una bandeja general independiente.
3. En **Conversaciones**, buscar asunto/contenido o filtrar remitente, cuenta
   y fechas. Un hilo se identifica por cuenta de origen + thread; no se
   fusionan hilos de cuentas distintas. Se pagina de a 20 conversaciones.
4. En **Consultar antecedentes**, investigar eventos pasados. Se conserva
   el modo rápido predeterminado, modo profundo, streaming, citas, gráficos
   y feedback. La respuesta seleccionada en esta sesión es el contexto
   propuesto; desmarcar continuidad o elegir «Nueva consulta independiente»
   permite cambiar de tema. Otras respuestas se agregan explícitamente.
5. Elegir un evento activo y **Guardar como antecedente**. La misma consulta
   se puede guardar en varios eventos. En el evento se muestran la respuesta,
   sus fuentes y quién guardó la referencia. Quitar el vínculo conserva el
   archivo original de consulta.

Las fechas y los filtros se muestran en UTC; los offsets de origen se
normalizan para ordenar. Un filtro encuentra hilos que tienen al menos un
mensaje coincidente, y al expandir se muestran todos sus mensajes confirmados
en orden cronológico. El orden de los hilos usa su actividad más reciente.
Los adjuntos muestran únicamente metadatos; no se descargan ni se procesan.

## Separación de información

El espacio actual reúne comunicaciones; el RAG consulta documentos históricos.
Seleccionar un evento o guardar una referencia no incorpora sus correos al
prompt ni altera el índice de Drive. El evento actual no necesita documentos
en la nube. Resúmenes, decisiones, pendientes e integraciones con plataformas
de trabajo actuales quedan para entregas posteriores.

**Configuración** concentra sincronización y diagnóstico. Las conexiones se
prueban al solicitarlas; abrir un evento no inicializa el agente ni exige
Qdrant/Neo4j disponibles. No se agregan llamadas automáticas a modelos.

## Persistencia y compatibilidad

`EventStore` aplica una migración aditiva e idempotente al abrir SQLite:
crea `event_query_links(event_id, query_id, saved_by, saved_at)` y los índices
de consultas, conservando las tablas y registros previos. La clave primaria
es `(event_id, query_id)`. Las altas/bajas se auditan con la identidad actual;
repetir un vínculo no duplica el registro ni cambia su autor original.

Las consultas siguen en `data/queries/`. Se valida su existencia antes de
asociarlas. Si el archivo falta posteriormente, la UI muestra «Antecedente
no disponible» y permite quitar el vínculo. No se copian respuestas ni se
migran los JSON. Los cambios no modifican modelos, embeddings ni contratos
HTTP/MCP. Los correos y el historial del evento se conservan al archivarlo;
solo los eventos activos aceptan nuevas asociaciones.

Las operaciones comerciales heredadas conservan datos y módulos, pero no
aparecen en la navegación. Mantener `ENABLE_OUTBOUND=false`; no hay controles
de envío en esta interfaz. Gmail real, OAuth corporativo y el despliegue del
piloto siguen requiriendo la configuración documentada por separado.

## Validación local

```powershell
./venv/Scripts/python.exe -m pytest -q
```

Las pruebas de `test_event_workspace.py` usan SQLite/JSON temporales para
aislamiento, agrupación, filtros, paginación, migración, archivo y auditoría.
`test_workspace_ui.py` recorre navegación, revisión, antecedentes ausentes,
continuidad entre pantallas y dos sesiones, streaming simulado y recuperación
de errores mediante Streamlit AppTest. No usan consultas pagas ni correos reales.

Al modificar módulos de `app/ui/`, reiniciar Streamlit para evitar módulos
cacheados. La entrada sigue siendo `run_streamlit.bat` / `streamlit_app.py`.
