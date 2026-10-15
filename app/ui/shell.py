"""Navegación independiente de las conexiones del RAG."""

import logging

import streamlit as st

from app import config
from app.collaboration.auth import require_allowed_email
from app.collaboration.store import EventStore
from app.ui.events import render_events
from app.ui.history import render_history

logger = logging.getLogger(__name__)

STYLE = """
<style>
  .stApp { background: #F6F8FB; color: #172033; }
  .block-container { max-width: 1180px; padding-top: 2.6rem; padding-bottom: 4rem; }
  [data-testid="stSidebar"] { background: #fff; border-right: 1px solid #E2E8F0; }
  h1 { font-size: 2.15rem !important; letter-spacing: -.035em; }
  h2, h3 { letter-spacing: -.02em; }
  [data-testid="stMetric"] { background: white; border: 1px solid #E2E8F0; border-radius: 12px; padding: 1rem 1.2rem; }
  [data-testid="stMetricLabel"] { color: #526079; }
  [data-testid="stMetricValue"] { color: #172033; font-size: 1.85rem; }
  [data-testid="stForm"], [data-testid="stExpander"], [data-testid="stVerticalBlockBorderWrapper"] { background: #fff; border-radius: 12px; border-color: #E2E8F0; }
  [data-testid="stForm"] { padding: 1.25rem; }
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #526079 !important; }
  [data-testid="stSidebar"] label[data-baseweb="radio"] { padding: .55rem .7rem; border-radius: 8px; margin: .15rem 0; }
  [data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked) { background: #EFF6FF; color: #1D4ED8; font-weight: 600; }
  [data-testid="stText"] { white-space: pre-wrap; overflow-wrap: anywhere; }
  [data-testid="stExpander"] summary p { overflow-wrap: anywhere; }
  [data-baseweb="tab-list"] { gap: 1rem; flex-wrap: wrap; }
  button:focus-visible, a:focus-visible { outline: 3px solid #2563EB; outline-offset: 2px; }
  @media (max-width: 700px) {
    .block-container { padding: 1.2rem 1rem 2rem; }
    h1 { font-size: 1.8rem !important; }
    [data-testid="stHorizontalBlock"] { flex-direction: column; gap: .7rem; }
    [data-testid="stColumn"] { width: 100% !important; flex: 1 1 100% !important; min-width: 0 !important; }
    [data-baseweb="tab-list"] { gap: .4rem; }
  }
</style>
"""


def current_actor() -> str:
    if not config.AUTH_REQUIRED:
        return config.DEVELOPMENT_ACTOR_EMAIL
    if not getattr(st.user, "is_logged_in", False):
        st.title("Centro de conocimiento")
        st.info("Ingresá con tu cuenta corporativa para acceder al espacio compartido.")
        if st.button("Ingresar con Google", type="primary"):
            st.login()
        st.stop()
    try:
        return require_allowed_email(getattr(st.user, "email", None), config.ALLOWED_EMAIL_DOMAIN)
    except PermissionError as error:
        st.error(str(error))
        if st.button("Cerrar sesión"):
            st.logout()
        st.stop()


def render_app(*, store=None, actor=None, queries_dir=None) -> None:
    st.set_page_config(page_title="Centro de conocimiento", page_icon="✦", layout="wide")
    st.markdown(STYLE, unsafe_allow_html=True)
    actor = actor if actor is not None else current_actor()
    queries_dir = queries_dir if queries_dir is not None else config.QUERIES_DIR
    if "next_workspace_page" in st.session_state:
        st.session_state["workspace_page"] = st.session_state.pop("next_workspace_page")
    if "next_show_archived" in st.session_state:
        st.session_state["include_archived_events"] = st.session_state.pop("next_show_archived")
    with st.sidebar:
        st.markdown("### Centro de conocimiento")
        st.caption("CONTEXTO PARA TU EQUIPO")
        page = st.radio("Navegación", ["Eventos", "Consultar antecedentes", "Configuración"], key="workspace_page", label_visibility="collapsed")
        st.divider()
        st.caption("ESPACIO COMPARTIDO")
        st.caption(actor)
        st.caption("Comunicaciones actuales y referencias históricas, en su lugar.")
        if config.AUTH_REQUIRED and st.button("Cerrar sesión"):
            st.logout()
    if "workspace_notice" in st.session_state:
        st.success(st.session_state.pop("workspace_notice"))
    try:
        if page == "Configuración":
            from app.ui.settings import render_settings

            render_settings(store)
        else:
            store = store if store is not None else EventStore(config.COLLABORATION_DB_PATH)
            if page == "Eventos":
                render_events(store, actor, queries_dir)
            else:
                render_history(store, actor, queries_dir)
    except Exception:
        logger.exception("No se pudo mostrar el espacio de trabajo")
        st.error("No pudimos completar esta acción. Volvé a cargar la vista para recuperar el estado más reciente.")
        if st.button("Volver a cargar"):
            st.rerun()
