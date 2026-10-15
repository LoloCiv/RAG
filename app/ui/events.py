"""El evento actual organiza comunicaciones y referencias elegidas por el equipo."""

import streamlit as st

from app.agent import queries
from app.ui.components import display_date, pagination, render_message, render_query


def _flash(message: str) -> None:
    st.session_state["workspace_notice"] = message
    st.rerun()


def render_pending(store, actor: str, *, event=None) -> None:
    event_id = event["id"] if event else None
    scope = event_id or "general"
    page_key = f"pending_page_{scope}"
    result = store.list_pending_messages(event_id, page=st.session_state.get(page_key, 1))
    if not result["items"]:
        st.info("No hay mensajes por revisar en esta bandeja.")
        return
    st.caption("Abrí el mensaje, revisá su contenido y elegí el evento al que corresponde.")
    active = store.list_events()
    names = {item["id"]: item["name"] for item in active}
    choices = list(names)
    archived = event is not None and event["status"] == "archived"
    if archived:
        st.info("Este evento está archivado. Las sugerencias se conservan para consulta.")
    for message in result["items"]:
        key = f"review_{scope}_{message['id']}"
        label = f"{message['subject'] or 'Sin asunto'} · {message['sender']} · {display_date(message['received_at'])}"
        with st.expander(label):
            render_message(message)
            if not archived:
                if choices:
                    with st.form(key):
                        target = st.selectbox("Asignar al evento", choices, index=choices.index(event_id) if event_id in choices else None, format_func=names.get, key=f"target_{key}", placeholder="Elegí un evento activo")
                        confirmed = st.form_submit_button("Confirmar asociación", type="primary")
                    if confirmed:
                        if target is None:
                            st.warning("Elegí el evento al que corresponde este mensaje.")
                        else:
                            store.confirm_event_message(target, message["id"], actor)
                            _flash(f"Correo confirmado para {names[target]}.")
                else:
                    st.info("Creá un evento activo para asociar este mensaje.")
    pagination(result, page_key)


def render_conversations(store, event: dict) -> None:
    scope = event["id"]
    options = store.conversation_filters(scope)
    search = st.text_input("Buscar en asunto y contenido", key=f"search_{scope}", placeholder="Ej.: catering, presupuesto, menú…")
    with st.expander("Filtros de conversación"):
        left, right = st.columns(2)
        sender = left.selectbox("Remitente", [None, *options["senders"]], format_func=lambda value: value or "Todos", key=f"sender_{scope}")
        account = right.selectbox("Cuenta de origen", [None, *options["accounts"]], format_func=lambda value: value or "Todas", key=f"account_{scope}")
        left, right = st.columns(2)
        start = left.date_input("Desde (UTC)", value=None, key=f"from_{scope}")
        end = right.date_input("Hasta (UTC)", value=None, key=f"to_{scope}")
    if start and end and start > end:
        st.warning("La fecha inicial debe ser anterior o igual a la fecha final.")
        return
    page_key = f"conversation_page_{scope}"
    signature = (search, sender, account, str(start), str(end))
    if st.session_state.get(f"filters_{scope}") != signature:
        st.session_state[page_key] = 1
        st.session_state[f"filters_{scope}"] = signature
    result = store.list_conversations(scope, search=search, sender=sender, account_email=account, date_from=str(start) if start else None, date_to=str(end) if end else None, page=st.session_state.get(page_key, 1))
    if not result["items"]:
        st.info("No hay conversaciones que coincidan. Ajustá los filtros o revisá los correos pendientes.")
        return
    st.caption("Los filtros encuentran conversaciones; al abrirlas se muestra el hilo completo.")
    for thread in result["items"]:
        latest = thread["messages"][-1]
        label = f"{latest['subject'] or 'Sin asunto'} · {latest['sender']} · {thread['account_email']} · {display_date(latest['received_at'])} · {len(thread['messages'])} mensajes"
        with st.expander(label):
            for index, message in enumerate(thread["messages"]):
                if index:
                    st.divider()
                render_message(message)
    pagination(result, page_key)


def render_references(store, event: dict, actor: str, queries_dir) -> None:
    links = store.list_query_links(event["id"])
    st.caption("Investigaciones sobre eventos pasados, guardadas como referencia para este evento.")
    if not links:
        st.info("Todavía no hay antecedentes guardados.")
        if st.button("Consultar antecedentes", key="research_from_event", type="primary"):
            st.session_state["next_workspace_page"] = "Consultar antecedentes"
            st.rerun()
    for link in links:
        record = queries.load_query(link["query_id"], queries_dir)
        key = f"reference_{event['id']}_{link['query_id']}"
        with st.expander(record["question"] if record else "Antecedente no disponible"):
            st.caption(f"Guardado por {link['saved_by']} · {display_date(link['saved_at'])}")
            if record:
                render_query(record, key=key, queries_dir=queries_dir)
                if st.button("Abrir consulta histórica", key=f"open_{key}"):
                    st.session_state["pending_query_id"] = record["id"]
                    st.session_state["next_workspace_page"] = "Consultar antecedentes"
                    st.rerun()
            else:
                st.warning("Antecedente no disponible. El archivo de la consulta falta o no se puede leer.")
            if st.button("Quitar vínculo", key=f"unlink_{key}"):
                store.unlink_query(event["id"], link["query_id"], actor)
                _flash("Vínculo eliminado. La consulta original se conserva.")


def render_events(store, actor: str, queries_dir) -> None:
    st.title("Eventos")
    st.caption("Un espacio compartido para reunir conversaciones y recuperar antecedentes útiles.")
    listing, general = st.tabs(["Mis eventos", "Correos sin asignar"])
    with general:
        st.subheader("Correos sin asignar")
        render_pending(store, actor)
    with listing:
        with st.expander("Crear evento"):
            with st.form("create_event", clear_on_submit=True):
                name = st.text_input("Nombre del evento", placeholder="Ej.: Cena anual 2026")
                create = st.form_submit_button("Crear evento", type="primary")
            if create:
                try:
                    created = store.create_event(name)
                except ValueError as error:
                    st.warning(str(error))
                else:
                    st.session_state["selected_event_id"] = created["id"]
                    st.session_state["include_archived_events"] = created["status"] == "archived"
                    _flash("Evento disponible en el listado.")
        st.session_state["show_archived"] = st.session_state.get("include_archived_events", False)

        def remember_archived():
            st.session_state["include_archived_events"] = st.session_state["show_archived"]

        show_archived = st.checkbox("Mostrar también archivados", key="show_archived", on_change=remember_archived)
        events = store.list_events(include_archived=show_archived)
        names = {item["id"]: f"{item['name']} · {'Archivado' if item['status'] == 'archived' else 'Activo'}" for item in events}
        choices = list(names)
        if not choices:
            st.info("Todavía no hay eventos activos. Creá uno para empezar a organizar las comunicaciones del equipo.")
            return
        if st.session_state.get("selected_event_id") not in choices:
            st.session_state["selected_event_id"] = choices[0]
        st.session_state["event_selection"] = st.session_state["selected_event_id"]

        def remember_event():
            st.session_state["selected_event_id"] = st.session_state["event_selection"]

        selected = st.selectbox("Elegí un evento", choices, format_func=names.get, key="event_selection", on_change=remember_event)
        event = next(item for item in events if item["id"] == selected)
        st.subheader(event["name"])
        st.caption("Archivado · historial disponible" if event["status"] == "archived" else "Activo · comunicaciones del equipo")
        counts = store.event_counts(selected)
        cols = st.columns(3)
        for col, label, field in zip(cols, ("Correos confirmados", "Por revisar", "Antecedentes"), ("confirmed", "pending", "references")):
            col.metric(label, counts[field])
        conversations, pending, references = st.tabs(["Conversaciones", f"Por revisar ({counts['pending']})", "Antecedentes guardados"])
        with conversations:
            render_conversations(store, event)
        with pending:
            render_pending(store, actor, event=event)
        with references:
            render_references(store, event, actor, queries_dir)
        if event["status"] == "active":
            with st.expander("Administrar evento"):
                st.caption("Archivar conserva las conversaciones y los antecedentes. El evento deja de aceptar asociaciones nuevas.")
                if st.button("Archivar evento", key=f"archive_{selected}"):
                    store.archive_event(selected, actor)
                    st.session_state["next_show_archived"] = True
                    _flash("Evento archivado. Su información continúa disponible.")
