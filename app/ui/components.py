"""Presentación compartida de evidencia, mensajes y navegación paginada."""

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

from app.agent import queries


def display_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%d/%m/%Y · %H:%M UTC")
    except (ValueError, AttributeError):
        return value or "Fecha no disponible"


def safe_url(value: str | None) -> bool:
    try:
        parsed = urlparse(value or "")
        return parsed.scheme in {"https", "http"} and bool(parsed.netloc)
    except ValueError:
        return False


def render_message(message: dict) -> None:
    st.text(message.get("subject") or "Sin asunto")
    st.caption(f"De: {message['sender']} · {display_date(message['received_at'])}")
    st.caption(f"Cuenta de origen: {message['account_email']}")
    for label, field in (("Para", "recipients"), ("CC", "cc")):
        if message.get(field):
            st.text(f"{label}: " + ", ".join(str(value) for value in message[field]))
    # Texto plano conserva el correo como evidencia y no interpreta HTML externo.
    st.text(message.get("body_text") or "Este mensaje no tiene cuerpo de texto.")
    if message.get("attachments"):
        st.caption("Adjuntos · metadatos disponibles")
        for attachment in message["attachments"]:
            if isinstance(attachment, dict):
                name = attachment.get('name') or attachment.get('filename') or 'Sin nombre'
                size = f" · {attachment['size']} bytes" if attachment.get('size') is not None else ""
                st.text(f"{name} · {attachment.get('mime_type', 'Tipo no informado')}{size}")
            else:
                st.text(str(attachment))
    if safe_url(message.get("thread_url")):
        st.link_button("Abrir correo original", message["thread_url"])


def render_query(record: dict, *, key: str, queries_dir: Path) -> None:
    st.caption("REFERENCIA HISTÓRICA")
    if record.get("similar_events") is not None:
        from app.ui.similar_events import render_similar_result

        render_similar_result(record["similar_events"])
    else:
        st.markdown(record.get("answer_text", ""))
    if record.get("elapsed_ms") is not None:
        st.caption(f"{display_date(record.get('created_at', ''))} · Respuesta en {record['elapsed_ms'] / 1000:.1f} s")
    if record.get("sources"):
        with st.expander(f"Fuentes verificables · {len(record['sources'])}"):
            for source in record["sources"]:
                name = source.get("file_name") or "Fuente sin nombre"
                if safe_url(source.get("drive_url")):
                    st.link_button(name, source["drive_url"])
                else:
                    st.text(name)
    for chart in record.get("chart_paths", []):
        if Path(chart).is_file():
            st.image(chart)
        else:
            st.caption("Gráfico no disponible en este equipo.")
    values = {0: "down", 1: "up"}
    feedback = st.feedback("thumbs", key=f"feedback_{key}", default={"down": 0, "up": 1}.get(record.get("feedback")))
    if values.get(feedback) != record.get("feedback"):
        queries.set_feedback(record["id"], values.get(feedback), queries_dir)


def save_reference(store, actor, queries_dir, record, *, key):
    active = store.list_events()
    if not active:
        st.caption("Creá un evento activo para guardar esta investigación como antecedente.")
        return
    names = {event["id"]: event["name"] for event in active}
    with st.form(f"save_reference_{key}"):
        target = st.selectbox("Guardar en un evento", list(names), index=None, format_func=names.get, placeholder="Elegí un evento activo")
        save = st.form_submit_button("Guardar como antecedente")
    if save:
        if target is None:
            st.warning("Elegí un evento activo para guardar esta referencia.")
        else:
            store.link_query(target, record["id"], actor, queries_dir=queries_dir)
            st.success(f"Antecedente guardado en {names[target]}.")


def pagination(result: dict, key: str) -> None:
    pages = max(1, (result["total"] + result["page_size"] - 1) // result["page_size"])
    st.caption(f"{result['total']} resultados · Página {result['page']} de {pages}")
    if pages <= 1:
        return
    previous, following = st.columns(2)
    if previous.button("Anterior", key=f"prev_{key}", disabled=result["page"] == 1):
        st.session_state[key] = result["page"] - 1
        st.rerun()
    if following.button("Siguiente", key=f"next_{key}", disabled=result["page"] == pages):
        st.session_state[key] = result["page"] + 1
        st.rerun()
