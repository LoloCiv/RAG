# Encontrar eventos similares

En **Consultar antecedentes → Encontrar eventos similares**, describir el evento
nuevo. Tipo, asistentes y ubicación son preferencias opcionales; no hace falta
crear un evento actual. La búsqueda enviada y sus resultados se conservan al
navegar. Cada investigación se guarda en el historial y puede vincularse a varios
eventos activos con **Guardar como antecedente**.

Hasta cinco tarjetas muestran coincidencias, diferencias, información faltante
y fragmentos de evidencia. Las lecciones registradas se distinguen de sugerencias
derivadas. Precios con fecha, moneda y alcance originales: no son cotizaciones
actuales. Un brief no demuestra la realización de lo planificado.

## Recuperación y compatibilidad

`app/similar_events/service.py` genera hasta tres consultas, recupera hasta 20
fragmentos por consulta, deduplica y rerankea 18. El modelo identifica hasta ocho
candidatos y se recuperan hasta ocho fragmentos por nombre para reunir información
dispersa. Otro reranking conserva hasta 22 fragmentos adicionales; el modelo
produce como máximo cinco tarjetas.

Reutiliza colección, embeddings, reranker y `CLAUDE_MODEL`. No crea catálogo,
reingiere contenido ni modifica consultas generales. No recibe evento actual,
correos, sesión compartida ni grafo de comunicaciones: solo colección histórica.

Pydantic valida `SimilarEventRequest` y `SimilarEventResult`. Las citas conservan
`source_id`, `chunk_index`, archivo y pestaña, sin inventar páginas. Cada cita debe
pertenecer a la evidencia recuperada y contener texto existente en ese fragmento.
Las identidades deben corresponder a un solo candidato; se rechazan mezclas de
homónimos. Estados futuros, en curso, cancelados o planificados se excluyen;
fechas futuras también. La síntesis recibe instrucciones para mostrar
contradicciones y mantener desconocido el campo en conflicto.

**Límite:** validar una cita no demuestra automáticamente que respalde
semánticamente una afirmación. Identificación de eventos e interpretación de
briefs dependen del modelo y requieren revisión contra las fuentes. Esta entrega
ofrece antecedentes encontrados, no una búsqueda exhaustiva.

Los JSON agregan opcionalmente `similar_events`, `usage` y `model`; los anteriores
siguen siendo legibles. Una salida inválida no se guarda como investigación
exitosa. Los errores conservan el formulario y permiten reintentar.

## Evaluación

`evals/similar_events.json` contiene cena corporativa, casamiento, cumpleaños y
ausencia de antecedentes sobre archivos conocidos. Los nombres esperados son
una base revisable: recuperar un brief no implica devolverlo como realizado.

Evaluar registros guardados como `<case_id>.json`, sin llamadas externas:

```powershell
./venv/Scripts/python.exe -m scripts.evaluate_similar_events --records data/evaluations/similar-events
```

Con autorización para enviar la evidencia a Claude/Voyage, agregar `--run-live`
ejecuta los cuatro casos y guarda resultados e informe. Consume llamadas a los
proveedores configurados. Mide recall de archivos y eventos, integridad de citas,
latencia y tokens de descubrimiento/síntesis. Tokens de embeddings y reranking
no están instrumentados: no representa costo total ni lo estima.

La revisión humana comprueba afirmaciones, contradicciones, homónimos, fechas,
presupuestos versus costos finales y alternativas. `claim_support_review` queda
pendiente hasta esa revisión. La evaluación real está pendiente de autorización;
no se publica un baseline de calidad basado en simulaciones.

```powershell
./venv/Scripts/python.exe -m pytest -q
```

La suite cubre preferencias, vacíos, enriquecimiento, citas fabricadas, identidad,
homónimos, contradicciones, fechas desconocidas/futuras, conservación de costos,
navegación, errores, guardado y aislamiento del correo actual.
