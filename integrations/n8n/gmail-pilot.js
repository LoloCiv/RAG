// Motor puro compartido por los nodos Code y las pruebas, sin credenciales.
function initialState(label = 'Evento/piloto-gmail') {
  return { label, stage: 'profile', retry: 0, account: '', labels: {}, ids: [],
    pageToken: '', nextPageToken: '', seenPages: [], processed: 0, pages: 0 };
}

function requestUrl(state) {
  const root = 'https://gmail.googleapis.com/gmail/v1/users/me';
  switch (state.stage) {
    case 'profile': return root + '/profile';
    case 'labels': return root + '/labels';
    case 'list': return root + '/messages?maxResults=100&includeSpamTrash=true&labelIds=' +
      encodeURIComponent(state.labelId) + (state.pageToken ? '&pageToken=' + encodeURIComponent(state.pageToken) : '');
    case 'message': return root + '/messages/' + encodeURIComponent(state.ids[0]) + '?format=full';
    case 'inbound': return 'http://host.docker.internal:8787/n8n/email/inbound';
    default: throw new Error('Etapa inesperada: ' + state.stage);
  }
}

function header(part, name) {
  return (part.headers || []).filter(h => h.name.toLowerCase() === name.toLowerCase()).map(h => h.value).join(', ');
}

function decodeText(data, charset = 'utf-8') {
  const bytes = Buffer.from(data.replace(/-/g, '+').replace(/_/g, '/'), 'base64');
  const normalized = charset.toLowerCase();
  if (['utf-8', 'utf8', 'us-ascii', 'ascii'].includes(normalized)) return bytes.toString('utf8');
  if (['iso-8859-1', 'latin1', 'windows-1252'].includes(normalized)) {
    // La mayoría del correo histórico occidental utiliza Latin-1 o Windows-1252.
    const windows = '€\u0081‚ƒ„…†‡ˆ‰Š‹Œ\u008dŽ\u008f\u0090‘’“”•–—˜™š›œ\u009džŸ';
    return Array.from(bytes, b => normalized === 'windows-1252' && b >= 128 && b <= 159 ? windows[b - 128] : String.fromCharCode(b)).join('');
  }
  throw new Error('Charset no soportado: ' + charset + '. Revisar el mensaje en Gmail.');
}

function decodeHeader(value) {
  return value.replace(/=\?([^?]+)\?([bq])\?([^?]*)\?=/gi, (_, charset, mode, data) => {
    const encoded = mode.toLowerCase() === 'b' ? data : Buffer.from(data.replace(/_/g, ' ').replace(/=([0-9a-f]{2})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16))), 'latin1').toString('base64');
    return decodeText(encoded, charset);
  });
}

function addresses(value) {
  // Separar comas solo fuera de comillas y de la dirección entre ángulos.
  const parts = []; let current = '', quoted = false, depth = 0, escaped = false;
  for (const char of decodeHeader(value)) {
    if (char === '"' && !escaped) quoted = !quoted;
    if (!quoted && char === '<') depth++;
    if (!quoted && char === '>') depth--;
    if (char === ',' && !quoted && depth === 0) { parts.push(current); current = ''; }
    else current += char;
    escaped = char === '\\' && !escaped;
  }
  parts.push(current);
  return parts.map(s => s.trim()).filter(Boolean);
}

function htmlToText(html) {
  const named = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', aacute: 'á', eacute: 'é', iacute: 'í', oacute: 'ó', uacute: 'ú', ntilde: 'ñ' };
  return html.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, '')
    .replace(/<(br|\/p|\/div|\/li|\/tr)\b[^>]*>/gi, '\n').replace(/<[^>]+>/g, '')
    .replace(/&(#x[\da-f]+|#\d+|\w+);/gi, (full, entity) => {
      if (entity[0] !== '#') return named[entity] ?? full;
      const number = entity[1].toLowerCase() === 'x' ? parseInt(entity.slice(2), 16) : parseInt(entity.slice(1), 10);
      return number <= 0x10ffff ? String.fromCodePoint(number) : full;
    }).trim();
}

function normalizeMessage(message, state) {
  if (!message.id || !message.threadId || !message.payload) throw new Error('Mensaje Gmail incompleto');
  const attachments = [];
  function body(part) {
    const disposition = header(part, 'content-disposition');
    if (part.filename || /attachment/i.test(disposition) || part.body?.attachmentId) {
      // No pedir /attachments: conservar únicamente metadatos, incluso de adjuntos inline.
      if (!part.filename && /^text\//.test(part.mimeType || '') && part.body?.attachmentId) {
        throw new Error('Cuerpo externalizado en Gmail: revisar el mensaje; no se descargan adjuntos');
      }
      attachments.push({filename: decodeHeader(part.filename || ''), mime_type: part.mimeType || '',
        size: part.body?.size || 0, attachment_id: part.body?.attachmentId || null, part_id: part.partId || null});
      return '';
    }
    const children = part.parts || [];
    if (part.mimeType === 'multipart/alternative') {
      const plain = children.find(child => child.mimeType === 'text/plain');
      return body(plain || children.find(child => child.mimeType === 'text/html') || children[0] || {});
    }
    if (children.length) return children.map(body).filter(Boolean).join('\n\n');
    if (!part.body?.data || !['text/plain', 'text/html'].includes(part.mimeType)) return '';
    const charset = /charset\s*=\s*"?([^;"\s]+)/i.exec(header(part, 'content-type'))?.[1] || 'utf-8';
    const decoded = decodeText(part.body.data, charset);
    return part.mimeType === 'text/html' ? htmlToText(decoded) : decoded;
  }
  const text = body(message.payload);
  const received = new Date(Number(message.internalDate));
  if (!message.internalDate || Number.isNaN(received.getTime())) throw new Error('Fecha de recepción Gmail inválida');
  const labels = (message.labelIds || []).map(id => {
    if (!state.labels[id]) throw new Error('Etiqueta desconocida: ' + id + '. Reejecutar para actualizar etiquetas.');
    return state.labels[id];
  });
  return {
    external_message_id: 'gmail:' + encodeURIComponent(state.account.toLowerCase()) + ':' + message.id,
    account_email: state.account.toLowerCase(), thread_id: message.threadId,
    sender: addresses(header(message.payload, 'from')).join(', '),
    recipients: addresses(header(message.payload, 'to')), cc: addresses(header(message.payload, 'cc')),
    subject: decodeHeader(header(message.payload, 'subject')), body_text: text, labels, attachments,
    received_at: received.toISOString(),
    thread_url: 'https://mail.google.com/mail/?authuser=' + encodeURIComponent(state.account) + '#all/' + message.threadId,
  };
}

function afterMessage(state) {
  state.ids.shift(); delete state.payload;
  if (state.ids.length) state.stage = 'message';
  else if (state.nextPageToken) { state.pageToken = state.nextPageToken; state.stage = 'list'; }
  else state.stage = 'done';
}

function transition(previous, response) {
  const state = JSON.parse(JSON.stringify(previous));
  const status = Number(response.statusCode || 0);
  const error = JSON.stringify(response.error || '');
  const transient = [408, 429, 500, 502, 503, 504].includes(status) ||
    (!status && /ECONN|ETIMEDOUT|EAI_AGAIN|timeout|socket hang up|timed out/i.test(error));
  if (transient && state.retry < 3) { state.retry++; return state; }
  if (status < 200 || status >= 300) {
    throw new Error('Falló ' + state.stage + ' (HTTP ' + (status || 'sin respuesta') + '). ' +
      (transient ? 'Agotados tres reintentos.' : 'Revisar credenciales o payload en esta ejecución; no se reintenta un error permanente.'));
  }
  state.retry = 0;
  const data = response.body;
  if (!data || typeof data !== 'object') throw new Error('Respuesta JSON inválida en ' + state.stage);
  switch (state.stage) {
    case 'profile':
      if (!data.emailAddress) throw new Error('Gmail no devolvió la cuenta');
      state.account = data.emailAddress; state.stage = 'labels'; break;
    case 'labels': {
      state.labels = Object.fromEntries((data.labels || []).map(label => [label.id, label.name]));
      const match = (data.labels || []).find(label => label.name === state.label);
      if (!match) throw new Error('Crear o corregir la etiqueta Gmail: ' + state.label);
      state.labelId = match.id; state.stage = 'list'; break;
    }
    case 'list':
      state.pages++;
      state.ids = [...new Set((data.messages || []).map(message => message.id))];
      state.nextPageToken = data.nextPageToken || '';
      if (state.nextPageToken && state.seenPages.includes(state.nextPageToken)) throw new Error('Gmail repitió el token de página');
      if (state.nextPageToken) state.seenPages.push(state.nextPageToken);
      if (state.ids.length) state.stage = 'message'; else afterMessage(state);
      break;
    case 'message':
      state.payload = normalizeMessage(data, state); state.stage = 'inbound'; break;
    case 'inbound':
      state.processed++; afterMessage(state); break;
    default: throw new Error('Etapa desconocida');
  }
  return state;
}
