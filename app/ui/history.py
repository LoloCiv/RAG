"""Consultas al histórico sin incorporar comunicaciones del evento seleccionado."""

import logging

import streamlit as st

from app.agent import queries
from app.ui.components import render_query

logger = logging.getLogger(__name__)


def selected_references(viewing_id, continue_selected, additional):
    """La continuidad depende de la selección de esta sesión, nunca del último JSON global."""
    return list(dict.fromkeys(([viewing_id] if viewing_id and continue_selected else []) + list(additional)))


def render_history(store, actor: str, queries_dir) -> None:
    st.title("Consultar antecedentes")
    st.caption("Investigá eventos pasados, compará proveedores y recuperá presupuestos con sus fuentes.")
    st.info("Las respuestas consultan el archivo histórico. Los correos del evento en curso se organizan en Eventos.")
    general, similar = st.tabs(["Consultas e historial", "Encontrar eventos similares"])
    with general:
        _render_general(store, actor, queries_dir)
    with similar:
        from app.ui.similar_events import render_similar_search

        render_similar_search(store, actor, queries_dir)


def _render_general(store, actor, queries_dir):
    recent = queries.list_queries(queries_dir)
    titles = {item["id"]: item["title"] or "Consulta sin título" for item in recent}
    if "pending_query_id" in st.session_state:
        st.session_state["selected_query_id"] = st.session_state.pop("pending_query_id")
    if st.session_state.get("selected_query_id") not in titles:
        st.session_state["selected_query_id"] = None
    # Streamlit elimina los valores de widgets que desaparecen al navegar;
    # una clave independiente conserva la elección real de esta persona.
    st.session_state["viewing_query_id"] = st.session_state.get("selected_query_id")

    def remember_selection():
        st.session_state["selected_query_id"] = st.session_state["viewing_query_id"]

    viewing_id = st.selectbox("Historial de consultas", [None, *titles], format_func=lambda value: titles.get(value, "Nueva consulta independiente"), key="viewing_query_id", on_change=remember_selection)
    record = queries.load_query(viewing_id, queries_dir) if viewing_id else None
    if record:
        with st.container(border=True):
            st.subheader(record["question"])
            render_query(record, key=f"history_{viewing_id}", queries_dir=queries_dir)
            active = store.list_events()
            if active:
                names = {event["id"]: event["name"] for event in active}
                with st.form(f"save_reference_{viewing_id}"):
                    target = st.selectbox("Guardar en un evento", list(names), index=None, format_func=names.get, placeholder="Elegí un evento activo")
                    save = st.form_submit_button("Guardar como antecedente")
                if save:
                    if target is None:
                        st.warning("Elegí un evento activo para guardar esta referencia.")
                    else:
                        store.link_query(target, viewing_id, actor, queries_dir=queries_dir)
                        st.success(f"Antecedente guardado en {names[target]}.")
            else:
                st.caption("Creá un evento activo para guardar esta investigación como antecedente.")
    elif viewing_id:
        st.warning("Esta consulta ya no está disponible. Podés iniciar una nueva.")
    with st.form("historical_query_form"):
        st.subheader("Nueva pregunta")
        continuation = False
        if record:
            continuation = st.checkbox("Continuar con la respuesta que estoy viendo", value=True, key=f"continue_{viewing_id}")
        other = [identifier for identifier in titles if identifier != viewing_id]
        additional = st.multiselect("Agregar otras respuestas como contexto", other, format_func=titles.get) if other else []
        mode = st.radio("Modo de respuesta", ["Rápida", "Profunda"], horizontal=True)
        question = st.text_area("¿Qué querés saber del histórico?", placeholder="Ej.: ¿Qué proveedores de catering usamos en eventos similares?", height=110)
        submitted = st.form_submit_button("Consultar", type="primary")
    if not submitted:
        return
    if not question.strip():
        st.warning("Escribí una pregunta para consultar los antecedentes.")
        return
    # Importar el agente al consultar permite navegar aun si faltan sus servicios.
    from app.agent import inbox

    references = selected_references(viewing_id if record else None, continuation, additional)
    progress = st.empty()
    progress.info("Preparando la consulta al histórico…")
    final_record = {}

    def stream_text():
        for event in inbox.ask_streaming(question.strip(), references=references or None, queries_dir=queries_dir, response_mode="fast" if mode == "Rápida" else "deep"):
            if event["type"] == "text_delta":
                progress.empty()
                yield event["text"]
            elif event["type"] == "tool_start":
                progress.info(event["label"])
            elif event["type"] == "final":
                final_record.update(event["record"])

    try:
        st.write_stream(stream_text())
        if not final_record.get("id"):
            raise RuntimeError("La consulta no devolvió una respuesta completa")
        st.session_state["pending_query_id"] = final_record["id"]
        st.rerun()
    except Exception:
        logger.exception("No se pudo completar la consulta histórica")
        st.error("No pudimos completar la consulta. Tu pregunta sigue en el formulario: podés volver a consultar o revisar Configuración.")
    finally:
        progress.empty()
