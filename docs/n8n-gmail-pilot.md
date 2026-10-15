# n8n: piloto de memoria de correo por evento

El flujo es **solo lectura**: n8n incorpora mensajes al Centro de
Conocimiento; nunca envía correos ni modifica Gmail.

## Convención de etiquetas

Cada integrante etiqueta los correos que quiere compartir con el formato
`Evento/<slug>`. Por ejemplo, para el evento **Cena anual**, usar
`Evento/cena-anual`. La etiqueta limita el alcance y además permite al
servidor sugerir el evento correcto; una persona lo confirma en la web.

## Un workflow por cuenta corporativa

1. Crear una credencial Gmail OAuth2 de solo lectura para la cuenta de ese
   integrante. No reutilizar credenciales personales.
2. Usar un trigger/poll de Gmail cada 5 minutos filtrado por la etiqueta
   `Evento/` o por una etiqueta concreta durante la primera prueba.
3. Convertir el resultado al siguiente contrato y enviar un HTTP `POST` a
   `http://host.docker.internal:8787/n8n/email/inbound` si n8n corre en
   Docker, o a `http://127.0.0.1:8787/n8n/email/inbound` si corre en el mismo
   host sin contenedor.
4. Incluir `Authorization: Bearer <N8N_WEBHOOK_TOKEN>`.

```json
{
  "external_message_id": "gmail-message-id-estable",
  "account_email": "persona@empresa.com",
  "thread_id": "gmail-thread-id",
  "sender": "proveedor@example.com",
  "recipients": ["persona@empresa.com"],
  "cc": [],
  "subject": "Asunto original",
  "body_text": "Cuerpo de texto plano",
  "labels": ["Evento/cena-anual"],
  "attachments": [{"name": "propuesta.pdf", "mime_type": "application/pdf"}],
  "received_at": "2026-09-03T12:00:00+00:00",
  "thread_url": "https://mail.google.com/mail/u/0/#all/<thread-id>"
}
```

`external_message_id` es obligatorio e idempotente: si n8n reintenta el
mismo mensaje, el servidor conserva un solo registro. No enviar adjuntos ni
tokens OAuth al endpoint; solo sus metadatos y el texto que el equipo eligió
compartir.

## Verificación

Después de incorporar un correo, abrir el evento en la web y confirmar la
sugerencia. Recién entonces aparece en la timeline y puede ser usado como
contexto para resúmenes o consultas. Si no hay confirmación, el mensaje no
entra en el conocimiento del evento.
