# Gmail de prueba mediante n8n

El piloto lee una etiqueta de una cuenta de prueba. Incorpora correo a la
coordinación actual con confirmación humana; no lo incorpora a la búsqueda histórica.
No envía mensajes, modifica Gmail ni descarga adjuntos.

## Instancia aislada

Desde la raíz del proyecto:

```powershell
docker compose -f integrations/n8n/compose.yaml up -d
```

Abrir http://localhost:5678 y crear la cuenta administradora local. Puede usar
el mismo correo que otra instalación: esta tiene base y credenciales independientes.
Imagen oficial fijada por digest, versión verificada **2.37.10**.
Solo publica `127.0.0.1:5678`; el volumen `rag-gmail-pilot_pilot_data` conserva
cuenta, clave de cifrado, credenciales y workflows. No modifica el n8n anterior.
`docker compose -f integrations/n8n/compose.yaml stop` detiene el piloto. No usar
`down -v` si se quiere conservar la configuración.

Si `docker` no está en el PATH, en Windows con Docker Desktop el ejecutable
suele estar en `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe`.

Importar `integrations/n8n/gmail-pilot.workflow.json`: queda desactivado.
El motor es `gmail-pilot.js`; regenerar el JSON después de editarlo con
`./venv/Scripts/python.exe integrations/n8n/build_workflow.py`.

## Credenciales

Se necesitan dos: **Gmail piloto · solo lectura**, tipo genérico **OAuth2 API**,
y **RAG piloto · Bearer local**, tipo **Header Auth**, nombre `Authorization`,
valor `Bearer <N8N_WEBHOOK_TOKEN>` del `.env` local.

La preparación opcional crea el Bearer y la plantilla OAuth sin imprimir secretos:

```powershell
./venv/Scripts/python.exe -m integrations.n8n.prepare_local
docker compose -f integrations/n8n/compose.yaml exec -T n8n n8n import:credentials --input=/pilot/.local/credentials.json
docker compose -f integrations/n8n/compose.yaml exec -T n8n n8n import:workflow --input=/pilot/.local/workflow.json
Remove-Item -LiteralPath integrations/n8n/.local/credentials.json
```

Ejecutar una sola vez. `.local/prepared.flag` impide sobrescribir OAuth. Si falla
una importación, reintentar ese comando después de corregirla, sin repetir la
preparación. `.local/` y `.env` están excluidos de Git. Tras importar, los secretos
quedan cifrados en n8n; eliminar el archivo temporal como indica el último comando.

En Google Cloud habilitar Gmail API, agregar la cuenta piloto como test user si
la aplicación OAuth está en testing y crear un cliente tipo **Web application**.
En Credentials de n8n, abrir la credencial preparada y completar Client ID y
Client Secret. Autorizar la cuenta desde el navegador. No compartir secretos en
el chat ni incluirlos en el workflow.

| Campo | Valor |
|---|---|
| Redirect URI en Google | `http://localhost:5678/rest/oauth2-credential/callback` |
| Grant type | Authorization Code |
| Authorization URL | `https://accounts.google.com/o/oauth2/v2/auth` |
| Access Token URL | `https://oauth2.googleapis.com/token` |
| Scope | `https://www.googleapis.com/auth/gmail.readonly` |
| Auth URI query parameters | `access_type=offline&prompt=consent` |
| Authentication | Body |

La credencial nativa Gmail puede solicitar permisos adicionales; este piloto usa
OAuth genérico y HTTP. Si el cliente tenía permisos anteriores más amplios,
revocar esa autorización y consentir únicamente el alcance de lectura.

## Receptor

Se mantiene `POST /n8n/email/inbound` y Bearer. El bind predeterminado sigue
siendo localhost; para Docker, usar una terminal dedicada:

```powershell
$env:WEBHOOK_HOST = '0.0.0.0'
./venv/Scripts/python.exe -m app.webhook_server
```

Docker conecta a `http://host.docker.internal:8787/n8n/email/inbound`.
El bind permite conexiones por las interfaces del host; no abrir puertos del
router. Mantener `ENABLE_OUTBOUND=false`. El receptor funciona separado de
Streamlit y debe seguir abierto. Retirar esa variable y reiniciarlo devuelve el
bind local. Configuración muestra la última incorporación local de un correo,
no su fecha original ni la última ejecución de n8n.

## Recorrido

Crear `Evento/piloto-gmail` en Gmail y aplicarla a mensajes seleccionados. Para
cambiarla, editar el literal de `initialState(...)` en **Configurar etiqueta**.
Crear un evento **Piloto Gmail** permite sugerirlo por su slug; sin coincidencia,
el correo llega a revisión general.

Ejecutar manualmente **RAG · Gmail piloto de solo lectura** antes de publicar
la programación de cinco minutos. Obtiene la cuenta y nombres de etiquetas,
recorre todas las páginas sin filtro de fecha ni leído/no leído y pide cada
mensaje con `format=full`. Incluye correos antiguos recién etiquetados y utiliza
la fecha de recepción de Gmail (`internalDate`). Normaliza MIME anidado,
texto/HTML, direcciones, etiquetas y metadatos de adjuntos.

Identidad externa: `gmail:<cuenta codificada>:<id Gmail>`. Repetir una ejecución
conserva un solo registro y no revierte confirmaciones humanas. HTTP
408/429/500/502/503/504 y fallos transitorios de conexión se reintentan hasta
tres veces, con dos segundos de espera. Autenticación y payload fallan enseguida.
La concurrencia de producción del piloto es una ejecución; evitar ejecutar
manualmente mientras la programación está en marcha durante la primera prueba.

UTF-8, ASCII, Latin-1 y Windows-1252 están soportados. Charset desconocido o
cuerpo externalizado como attachmentId dejan error visible, sin entregar texto
incompleto. No se solicita el endpoint de descarga de adjuntos.

## Diagnóstico y cierre

Abrir **Executions**, elegir la ejecución fallida y el nodo con error. 401/403:
revisar OAuth o Bearer según el nodo. 422: revisar payload. 429/5xx: reintentar
después de recuperar el servicio. Las ejecuciones fallidas conservan datos para
diagnóstico local y se purgan a los siete días; las exitosas de producción no
guardan datos. Los correos pueden aparecer en ejecuciones fallidas: limitar
el acceso a esta instancia.

Prueba con cuenta real: etiquetar un correo leído antiguo y otro no leído,
ejecutar, comprobar **Por revisar**, repetir y verificar que la cantidad no
aumenta; confirmar uno desde la interfaz. Solo entonces publicar la programación
si se quiere dejar funcionando.

La suite usa el mismo JavaScript del workflow, Node.js y SQLite temporal.
También se ejecutó el grafo completo en n8n con Gmail simulado: dos páginas,
un 503 recuperado y dos entregas del mismo ID produjeron un registro. El workflow
temporal fue archivado. La cuenta real requiere su consentimiento de Google.

Fuentes oficiales: [OAuth local](https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/),
[HTTP Request](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/).
