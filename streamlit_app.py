"""UI del POC: buzon de consultas stateless y administracion de Drive."""

import logging

import streamlit as st

from app.agent import claude_agent, queries
from app.config import GOOGLE_DRIVE_FOLDER_ID, require_env
from app.graph.neo4j_client import Neo4jGraphStore
from app.ingestion import manifest, pipeline
from app.logging_conf import setup_logging

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
st.caption("Mandá tu consulta sobre eventos, presupuestos y proveedores. Cada consulta es independiente.")


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


user_input = st.chat_input("Escribí tu pregunta...")
if user_input:
    with st.chat_message("user"):
        st.write(user_input)
    with st.chat_message("assistant"):
        progress = st.empty()
        progress.markdown("*Pensando...*")
        final_record = {}

        def _stream_answer_text():
            saved_record = None
            for event in claude_agent.run_turn_streaming([{"role": "user", "content": user_input}]):
                if event["type"] == "text_delta":
                    progress.empty()
                    yield event["text"]
                elif event["type"] == "tool_start":
                    progress.markdown(f"*{event['label']}*")
                elif event["type"] == "final":
                    saved_record = queries.save_query(queries.new_query_id(), user_input, event["result"])
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
