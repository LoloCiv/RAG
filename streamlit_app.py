"""UI del POC: buzon de consultas stateless y administracion de Drive."""

import logging

import streamlit as st

from app.agent import inbox, queries
from app.config import GOOGLE_DRIVE_FOLDER_ID, require_env
from app.graph.neo4j_client import Neo4jGraphStore
from app.ingestion import manifest, pipeline
from app.logging_conf import setup_logging
from app.operations import work_items
from app.operations.metrics import summarize_work_items
from app.operations.providers import ClaudeOperationsProvider
from app.operations.service import generate_draft

setup_logging()
logger = logging.getLogger(__name__)
st.set_page_config(page_title="Agente de Eventos (POC)", page_icon="📋", layout="wide")


@st.cache_data(ttl=60, show_spinner=False)
def graph_stats() -> dict:
    """Neo4j puede degradar sin romper el buzon, que conserva la busqueda vectorial."""
    store = Neo4jGraphStore()
    try:
        return store.stats()
    finally:
        store.close()


if "viewing_id" not in st.session_state:
    st.session_state.viewing_id = None
if "viewing_work_item_id" not in st.session_state:
    st.session_state.viewing_work_item_id = None

with st.sidebar:
    st.header("Operaciones comerciales")
    _work_items = work_items.list_work_items()
    for _item in _work_items:
        _label = f"{_item['supplier_name']} · {_item['event_name'] or 'sin evento'}"
        _active = _item["id"] == st.session_state.viewing_work_item_id
        if st.button(("📌 " if _active else "") + _label, key=f"work_{_item['id']}", use_container_width=True):
            st.session_state.viewing_work_item_id = _item["id"]
            st.rerun()
    with st.expander("Indicadores del piloto"):
        _operations_metrics = summarize_work_items(_work_items)
        st.metric("Work items", _operations_metrics["total"])
        if _operations_metrics["average_seconds_to_draft"] is not None:
            st.metric("Promedio hasta borrador", f"{_operations_metrics['average_seconds_to_draft'] / 60:.1f} min")
        if _operations_metrics["average_seconds_to_resolution"] is not None:
            st.metric("Promedio hasta resolución", f"{_operations_metrics['average_seconds_to_resolution'] / 60:.1f} min")
        if _operations_metrics["approval_without_edit_rate"] is not None:
            st.metric("Aprobados sin edición", f"{_operations_metrics['approval_without_edit_rate']:.0%}")
        if _operations_metrics["external_actions_without_approval"]:
            st.error("Hay entregas sin aprobación en la auditoría.")
    st.divider()

with st.sidebar:
    st.header("Consultas recientes")
    for _query in queries.list_queries():
        _label = _query["title"] or "(sin título)"
        _active = _query["id"] == st.session_state.viewing_id
        if st.button(("📬 " if _active else "") + _label, key=f"q_{_query['id']}", use_container_width=True):
            st.session_state.viewing_id = _query["id"]
            st.rerun()
    st.divider()

with st.sidebar:
    st.header("Configuracion")
    missing = require_env()
    if missing:
        st.error("Faltan variables de entorno: " + ", ".join(missing) + "\n\nRevisa tu archivo .env (ver .env.example).")
    st.caption(f"Carpeta de Drive: `{GOOGLE_DRIVE_FOLDER_ID or '(no configurada)'}`")
    if st.button("🔄 Resincronizar Google Drive", disabled=not GOOGLE_DRIVE_FOLDER_ID):
        with st.spinner("Sincronizando con Google Drive..."):
            try:
                result = pipeline.run_resync(GOOGLE_DRIVE_FOLDER_ID)
                graph_stats.clear()
                st.success(result.summary)
                if result.failed:
                    with st.expander(f"⚠️ {len(result.failed)} archivo(s) con error"):
                        for name, error in result.failed:
                            st.write(f"**{name}**: {error}")
                if result.warnings:
                    with st.expander(f"📄 {len(result.warnings)} archivo(s) con advertencia"):
                        for name, warning in result.warnings:
                            st.write(f"**{name}**: {warning}")
            except Exception as error:
                logger.exception("Fallo el resync de Drive")
                st.error(f"No se pudo sincronizar: {error}")
    try:
        _stats = graph_stats()
        col_e, col_r = st.columns(2)
        col_e.metric("Entidades", _stats["entities"])
        col_r.metric("Relaciones", _stats["relationships"])
        st.caption("Grafo en [Neo4j Browser](http://localhost:7474)")
    except Exception as error:
        st.warning(f"Grafo no disponible: {error}")
    _manifest = manifest.load_manifest()
    if _manifest:
        st.caption(f"{len(_manifest)} archivo(s) ingeridos")
        with st.expander("Ver detalle"):
            st.dataframe([{"archivo": item["file_name"], "tipo": item["mime_type"].split(".")[-1], "ultima ingesta": item["last_ingested_at"]} for item in _manifest.values()], hide_index=True, use_container_width=True)

st.title("📋 Agente de Eventos (POC)")
st.caption("Bandeja de operaciones y consultas con evidencia sobre eventos, presupuestos y proveedores.")


def _render_sources(sources: list[dict]) -> None:
    """Presenta nombres legibles y conserva el enlace a Drive cuando existe."""
    with st.expander(f"Fuentes ({len(sources)})"):
        for source in sources:
            if source.get("drive_url"):
                st.write(f"- [{source['file_name']}]({source['drive_url']})")
            else:
                st.write(f"- {source['file_name']}")


_FEEDBACK_INDEX_TO_VALUE = {0: "down", 1: "up"}
_FEEDBACK_VALUE_TO_INDEX = {"down": 0, "up": 1}


def _render_query(record: dict, include_text: bool = True) -> None:
    """Centraliza el render para consultas nuevas y recuperadas del sidebar."""
    if include_text:
        st.write(record["answer_text"])
    if record.get("sources"):
        _render_sources(record["sources"])
    for chart_path in record.get("chart_paths", []):
        st.image(chart_path)
    current_index = _FEEDBACK_VALUE_TO_INDEX.get(record.get("feedback"))
    new_index = st.feedback("thumbs", key=f"fb_{record['id']}", default=current_index)
    new_feedback = _FEEDBACK_INDEX_TO_VALUE.get(new_index)
    if new_feedback != record.get("feedback"):
        queries.set_feedback(record["id"], new_feedback)
        record["feedback"] = new_feedback


def _render_work_item(record: dict) -> None:
    """Hace visible la evidencia y separa propuesta, aprobacion y envio externo."""
    st.subheader(f"{record['supplier_name']} · {record['event_name'] or 'Sin evento'}")
    st.caption(f"Canal: {record['channel']} · Estado: `{record['status']}`")
    for message in record["messages"]:
        with st.chat_message("user" if message["direction"] == "inbound" else "assistant"):
            st.write(message["text"])
            st.caption(message["received_at"])

    if record.get("evidence"):
        with st.expander("Evidencia usada para el borrador", expanded=False):
            st.write(record["evidence"].get("answer_text", ""))
            if record["evidence"].get("sources"):
                _render_sources(record["evidence"]["sources"])

    if record["status"] == "needs_review":
        if not record.get("draft"):
            if st.button("Generar borrador con evidencia", type="primary", key=f"generate_{record['id']}"):
                with st.spinner("Buscando evidencia y preparando borrador..."):
                    try:
                        generate_draft(record["id"], ClaudeOperationsProvider())
                        st.rerun()
                    except Exception as error:
                        logger.exception("Fallo la generacion del borrador")
                        st.error(f"No se pudo generar el borrador: {error}")
            return

        edited_text = st.text_area("Borrador para revisar", value=record["draft"]["text"], height=180, key=f"draft_{record['id']}")
        actor = st.text_input("Quién revisa", value="Operaciones", key=f"actor_{record['id']}")
        evidence_verified = st.checkbox(
            "Revisé la evidencia y sus fuentes antes de aprobar",
            key=f"evidence_{record['id']}",
        )
        save_col, approve_col, reject_col = st.columns(3)
        if save_col.button("Guardar edición", key=f"save_{record['id']}"):
            work_items.edit_draft(record["id"], edited_text, actor)
            st.rerun()
        if approve_col.button("Aprobar envío", type="primary", key=f"approve_{record['id']}", disabled=not evidence_verified):
            try:
                if edited_text != record["draft"]["text"]:
                    work_items.edit_draft(record["id"], edited_text, actor)
                work_items.approve_work_item(record["id"], actor, evidence_verified=True)
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        reason = st.text_input("Motivo de rechazo", key=f"reason_{record['id']}")
        if reject_col.button("Rechazar", key=f"reject_{record['id']}"):
            try:
                work_items.reject_work_item(record["id"], actor, reason or "Requiere cambios")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        return

    if record.get("draft"):
        st.markdown("**Borrador aprobado**")
        st.write(record["draft"]["text"])
    if record["status"] == "approved":
        st.info("Aprobado: n8n puede tomar este envío pendiente. La aplicación no envía mensajes directamente.")
    elif record["status"] == "rejected":
        st.warning("Rechazado: " + record.get("rejection_reason", "Sin motivo registrado"))
    elif record["status"] == "sent":
        st.success("Enviado por n8n: " + record.get("delivery", {}).get("external_message_id", "sin id externo"))


if st.session_state.viewing_work_item_id:
    _work_item = work_items.load_work_item(st.session_state.viewing_work_item_id)
    if _work_item:
        _render_work_item(_work_item)
        st.divider()


with st.form("query_form", clear_on_submit=True):
    _recent = queries.list_queries()
    _titles = {query["id"]: query["title"] for query in _recent}
    references = st.multiselect(
        "Citar consultas anteriores (opcional)",
        options=list(_titles),
        format_func=lambda query_id: _titles[query_id],
    )
    question = st.text_area(
        "Tu consulta",
        height=120,
        placeholder="Preguntá sobre eventos, presupuestos y proveedores…",
    )
    submitted = st.form_submit_button("Enviar consulta", type="primary")

if submitted and question.strip():
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        progress = st.empty()
        progress.markdown("*Pensando...*")
        final_record = {}

        def _stream_answer_text():
            saved_record = None
            for event in inbox.ask_streaming(question, references=references or None):
                if event["type"] == "text_delta":
                    progress.empty()
                    yield event["text"]
                elif event["type"] == "tool_start":
                    progress.markdown(f"*{event['label']}*")
                elif event["type"] == "final":
                    saved_record = event["record"]
            final_record.update(saved_record or {})

        try:
            st.write_stream(_stream_answer_text())
            progress.empty()
            _render_query(final_record, include_text=False)
            st.session_state.viewing_id = final_record["id"]
        except Exception as error:
            progress.empty()
            logger.exception("Fallo la consulta")
            st.error(f"Ocurrió un error: {error}")
elif st.session_state.viewing_id:
    _viewed = queries.load_query(st.session_state.viewing_id)
    if _viewed:
        with st.chat_message("user"):
            st.write(_viewed["question"])
        with st.chat_message("assistant"):
            _render_query(_viewed)
