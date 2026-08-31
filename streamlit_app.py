"""UI del POC: chat con el agente + boton de resync de Google Drive.

Corre todo en un solo proceso (sin FastAPI/Inngest): esta pantalla llama
directo a app/ingestion/pipeline.py y app/agent/claude_agent.py.

Para levantarlo: `streamlit run streamlit_app.py` (con el venv activado).
"""

import logging

import streamlit as st

from app.config import GOOGLE_DRIVE_FOLDER_ID, require_env
from app.graph.neo4j_client import Neo4jGraphStore
from app.ingestion import manifest, pipeline
from app.logging_conf import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Agente de Eventos (POC)", page_icon="📋", layout="wide")


@st.cache_data(ttl=60, show_spinner=False)
def graph_stats() -> dict:
    """Conteos del grafo para el sidebar.

    Deja propagar la excepcion de conexion a proposito: quien la llama la
    muestra como un warning, no como un error fatal. Que Neo4j este apagado
    no tiene que romper el chat -- el agente hoy usa el camino vectorial, el
    grafo todavia no esta enganchado.
    """
    store = Neo4jGraphStore()
    try:
        return store.stats()
    finally:
        store.close()

# --- Estado de sesion ---
# api_messages: historial en formato Anthropic (lo que se le manda a run_turn
#   en cada turno) -- se guarda el message.content completo del agente, no
#   solo el texto, para no perder contexto de tool calls entre turnos.
# display_messages: version simplificada solo para renderizar el chat
#   (texto + fuentes + charts), separada de api_messages para no ensuciar
#   la UI con el detalle interno de cada tool call.
if "api_messages" not in st.session_state:
    st.session_state.api_messages = []
if "display_messages" not in st.session_state:
    st.session_state.display_messages = []


# --- Sidebar: config + resync de Drive ---
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
                graph_stats.clear()  # el resync acaba de mover el grafo
                st.success(result.summary)
                if result.failed:
                    with st.expander(f"⚠️ {len(result.failed)} archivo(s) con error"):
                        for name, err in result.failed:
                            st.write(f"**{name}**: {err}")
            except Exception as e:
                logger.exception("Fallo el resync de Drive")
                st.error(f"No se pudo sincronizar: {e}")

    # Estado del grafo de conocimiento. Cacheado porque Streamlit re-ejecuta
    # este archivo entero en cada interaccion, y no hace falta reconectarse a
    # Neo4j para redibujar el sidebar (el resync limpia el cache al terminar).
    try:
        _stats = graph_stats()
        col_e, col_r = st.columns(2)
        col_e.metric("Entidades", _stats["entities"])
        col_r.metric("Relaciones", _stats["relationships"])
        st.caption("Grafo en [Neo4j Browser](http://localhost:7474)")
    except Exception as e:  # noqa: BLE001 - ver docstring de graph_stats
        st.warning(f"Grafo no disponible: {e}")

    man = manifest.load_manifest()
    if man:
        st.caption(f"{len(man)} archivo(s) ingeridos")
        with st.expander("Ver detalle"):
            st.dataframe(
                [
                    {
                        "archivo": entry["file_name"],
                        "tipo": entry["mime_type"].split(".")[-1],
                        "ultima ingesta": entry["last_ingested_at"],
                    }
                    for entry in man.values()
                ],
                hide_index=True,
                use_container_width=True,
            )


# --- Chat principal ---
st.title("📋 Agente de Eventos (POC)")
st.caption("Preguntá sobre eventos, presupuestos y proveedores. Pedí gráficos si querés ver los números.")

for msg in st.session_state.display_messages:
    with st.chat_message(msg["role"]):
        st.write(msg["text"])
        if msg.get("sources"):
            with st.expander(f"Fuentes ({len(msg['sources'])})"):
                for src in msg["sources"]:
                    st.write(f"- {src}")
        for chart_path in msg.get("chart_paths", []):
            st.image(chart_path)

user_input = st.chat_input("Escribí tu pregunta...")

if user_input:
    st.session_state.display_messages.append({"role": "user", "text": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    st.session_state.api_messages.append({"role": "user", "content": user_input})

    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                # Import diferido: si claude_agent.py todavia no esta
                # implementado, el error aparece recien al usar el chat,
                # no al arrancar la app (el resync de Drive puede probarse
                # igual mientras tanto).
                from app.agent import claude_agent

                result = claude_agent.run_turn(st.session_state.api_messages)

                st.session_state.api_messages.append(
                    {"role": "assistant", "content": result["response_content"]}
                )

                answer_text = result.get("answer_text", "")
                sources = result.get("sources", [])
                chart_paths = result.get("chart_paths", [])

                st.write(answer_text)
                if sources:
                    with st.expander(f"Fuentes ({len(sources)})"):
                        for src in sources:
                            st.write(f"- {src}")
                for chart_path in chart_paths:
                    st.image(chart_path)

                st.session_state.display_messages.append(
                    {"role": "assistant", "text": answer_text, "sources": sources, "chart_paths": chart_paths}
                )
            except Exception as e:
                logger.exception("Fallo el turno del agente")
                # No se agrega nada a api_messages en el error: si el
                # usuario reintenta, el historial que se le manda a Claude
                # queda consistente (sin un turno de asistente a medio
                # completar).
                st.session_state.api_messages.pop()  # saca el user turn que no se pudo responder
                st.error(f"Ocurrió un error: {e}")
