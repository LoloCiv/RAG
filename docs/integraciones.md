# Integraciones

Cómo se conecta el buzón con el resto: MCP, el piloto de correo con n8n y el
módulo comercial heredado.

## Servidor MCP

El buzón también se expone como servidor [MCP](https://modelcontextprotocol.io)
por stdio, para que lo consuma cualquier cliente compatible (Claude Desktop,
Claude Code, un motor de flujos) sin acoplarse a este repo:

```bash
venv\Scripts\python.exe -m app.mcp_server      # o el script: events-rag-mcp
```

Expone **una sola tool**, `query_events_kb(question)`, stateless: cada
llamada es una consulta independiente. Devuelve el texto de la respuesta con
sus fuentes y los gráficos generados como imágenes embebidas (un path local
no le sirve a un cliente remoto). Cada consulta queda además en el mismo log
de `data/queries/` que la UI.

Para un servidor de solo consulta alcanzan `ANTHROPIC_API_KEY` y
`VOYAGE_API_KEY` (la base ya tiene que estar ingerida); si Neo4j no está, el
agente degrada solo a búsqueda vectorial. Configuración para Claude Desktop
(`claude_desktop_config.json`), usando el Python del venv por ruta absoluta:

```json
{
  "mcpServers": {
    "events-rag": {
      "command": "C:\\ruta\\al\\proyecto\\events-rag-poc\\venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp_server"]
    }
  }
}
```

Limitación conocida: `app/agent/tools.py` guarda estado por turno a nivel
módulo, así que los turnos se **serializan con un lock** (`app/agent/inbox.py`).
Es correcto para stdio, que atiende a un cliente; antes de exponerlo por HTTP
con varios usuarios hay que migrar ese estado a uno por request.

## Piloto de correo con n8n (solo lectura)

El piloto colaborativo usa correo corporativo en modo lectura: cada persona
etiqueta los mensajes que quiere compartir como `Evento/<slug>`, n8n los
sincroniza periódicamente y el equipo confirma el evento antes de que formen
parte de las conversaciones confirmadas. Los resúmenes de correo quedan para
una entrega posterior. El workflow y el contrato detallado
están en [docs/n8n-gmail-pilot.md](n8n-gmail-pilot.md).

El piloto Gmail incluye [Docker Compose](../integrations/n8n/compose.yaml) y un
[workflow importable desactivado](../integrations/n8n/gmail-pilot.workflow.json).
La instancia local en puerto 5678 tiene su propio volumen y conserva la instalación
anterior. La cuenta de prueba debe autorizar OAuth de solo lectura en el navegador.

Para el servidor privado, copiar `.streamlit/secrets.toml.example` a
`.streamlit/secrets.toml`, completar OAuth de Google y definir
`AUTH_REQUIRED=true` y `ALLOWED_EMAIL_DOMAIN=empresa.com`. En desarrollo
local la autenticación permanece explícitamente desactivada por defecto.

## Encontrar eventos similares

En **Consultar antecedentes → Encontrar eventos similares**, describí un evento
y agregá preferencias opcionales de tipo, asistentes y ubicación. Recupera hasta
cinco antecedentes históricos con coincidencias, diferencias y evidencia, y permite
guardar la investigación en un evento actual. No utiliza sus correos en la búsqueda.
Detalles, límites y evaluación: [similar-events.md](similar-events.md).

## Integración comercial heredada con n8n

Esta sección documenta contratos conservados por compatibilidad. La interfaz
actual no presenta generación de borradores ni aprobaciones de envío.
Mantener `ENABLE_OUTBOUND=false`: las rutas outbox/sent/failed responden 404.
Para el piloto de comunicaciones actuales, usar el endpoint de correo
`POST /n8n/email/inbound` (ver «Piloto de correo con n8n», arriba).

Iniciá el webhook en otra terminal:

```bash
venv\Scripts\python.exe -m app.webhook_server
```

n8n conserva las credenciales de Gmail o WhatsApp Business Cloud y llama al
servidor local con `Authorization: Bearer <N8N_WEBHOOK_TOKEN>`:

- `POST /n8n/inbound`: recibe un mensaje normalizado con `message_id`,
  `channel` (`email` o `whatsapp`), `supplier_name` y `text`; también acepta
  `event_name`, `thread_key`, `received_at` y `attachments`.
- `GET /n8n/outbox`: devuelve solo work items aprobados y pendientes.
- `POST /n8n/outbox/{id}/sent`: n8n confirma el envío con
  `external_message_id` después de que el canal lo aceptó.
- `POST /n8n/outbox/{id}/failed`: registra un error recuperable de entrega.

El flujo comercial anterior era: mensaje entrante → borrador con evidencia → edición y
revisión explícita de fuentes y aprobación humana en Streamlit → n8n toma el
work item → confirmación de envío. No hay una ruta que saltee la aprobación
humana, ni se aprueba un item sin texto de borrador.

El módulo heredado de indicadores calcula tiempos hasta borrador/resolución,
tasa de aprobación sin edición y detecta en la auditoría cualquier entrega
que carezca de una aprobación previa. La corrección semántica de las fuentes
queda deliberadamente como revisión humana, registrada antes de aprobar.
