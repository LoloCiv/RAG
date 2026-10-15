"""Tarjetas verificables y formulario persistente para buscar experiencias anteriores."""

import logging

import streamlit as st

from app.agent import queries
from app.similar_events.models import SimilarEventRequest, SimilarEventResult

logger = logging.getLogger(__name__)


def render_similar_result(data: dict) -> None:
    from app.ui.components import safe_url

    result = SimilarEventResult.model_validate(data)
    evidence = {item.id: item for item in result.evidence}
    st.caption("Criterios de búsqueda: " + " · ".join(filter(None, [result.criteria.description, result.criteria.event_type, f"{result.criteria.attendees} asistentes" if result.criteria.attendees else None, result.criteria.location])))
    if not result.events:
        st.info("No encontramos antecedentes suficientes. Probá ampliar la descripción o quitar preferencias.")
    for number, event in enumerate(result.events, 1):
        with st.container(border=True):
            st.subheader(f"{number}. {event.event_name}")
            status = "Realización documentada" if event.status == "completed" else "Realización no confirmada en las fuentes"
            st.caption(f"{event.event_date or 'Fecha no documentada'} · {status}")
            cited = []

            def references(citations):
                indices = []
                for citation in citations:
                    if citation not in cited:
                        cited.append(citation)
                    indices.append(str(cited.index(citation) + 1))
                return " [" + ", ".join(indices) + "]" if indices else ""

            st.caption("Identidad y fecha" + references([*event.identity_citations, *event.date_citations, *event.status_citations]))
            for label, facts in (("Características documentadas", event.characteristics), ("Por qué puede servir", event.similarities), ("Diferencias y contradicciones", event.differences), ("Proveedores documentados", event.suppliers), ("Lecciones registradas", event.lessons), ("Sugerencias derivadas del análisis", event.suggestions)):
                if facts:
                    st.markdown(f"**{label}**")
                    for fact in facts:
                        st.write("• " + fact.text + references(fact.citations))
            if event.costs:
                st.markdown("**Costos históricos · no son cotizaciones actuales**")
                for cost in event.costs:
                    st.write(f"{cost.amount_text} · {cost.currency or 'Moneda no documentada'}" + references(cost.citations))
                    st.caption(f"Fecha: {cost.date_text or 'no documentada'} · Alcance: {cost.scope or 'no documentado'}")
            if event.missing_information:
                st.markdown("**Información faltante**")
                for missing in event.missing_information:
                    st.write("• " + missing)
            with st.expander(f"Ver evidencia · {len(cited)} fragmentos"):
                for index, citation in enumerate(cited, 1):
                    source = evidence.get(citation.evidence_id)
                    if source is None:
                        st.warning("La referencia guardada no está disponible.")
                        continue
                    location = f" · Pestaña: {source.sheet_tab}" if source.sheet_tab else ""
                    st.text(f"[{index}] {source.file_name}{location}")
                    st.text(citation.quote)
                    if safe_url(source.drive_url):
                        st.link_button("Abrir documento", source.drive_url)
    for warning in result.warnings:
        st.caption(warning)


def render_similar_search(store, actor, queries_dir) -> None:
    from app.ui.components import render_query, save_reference

    st.subheader("Encontrar eventos similares")
    st.caption("Describí lo que estás preparando. Las preferencias ayudan a encontrar antecedentes; también mostramos alternativas y sus diferencias.")
    saved = st.session_state.get("similar_search_draft", {})
    with st.form("similar_events_form"):
        description = st.text_area("Descripción del evento nuevo", value=saved.get("description", ""), placeholder="Ej.: Cena corporativa para 150 personas, con catering y presentaciones", key="similar_description")
        left, right = st.columns(2)
        kind = left.text_input("Tipo de evento (opcional)", value=saved.get("event_type", ""), key="similar_type")
        attendees = right.number_input("Asistentes (opcional)", min_value=1, max_value=1_000_000, value=saved.get("attendees"), step=1, key="similar_attendees")
        location = st.text_input("Ubicación (opcional)", value=saved.get("location", ""), key="similar_location")
        submitted = st.form_submit_button("Encontrar antecedentes", type="primary")
    if submitted:
        st.session_state["similar_search_draft"] = {"description": description, "event_type": kind, "attendees": attendees, "location": location}
        try:
            request = SimilarEventRequest(description=description, event_type=kind or None, attendees=attendees, location=location or None)
        except ValueError:
            st.warning("Escribí una descripción de al menos tres caracteres y revisá los campos del formulario.")
        else:
            progress = st.empty()
            try:
                from app.similar_events.service import find_similar_events

                record = find_similar_events(request, queries_dir=queries_dir, progress=progress.info)
                st.session_state["selected_similar_query_id"] = record["id"]
            except Exception:
                logger.exception("Falló la búsqueda de eventos similares")
                st.error("No pudimos completar la búsqueda. Tu descripción se conserva: podés reintentar o revisar Configuración.")
            finally:
                progress.empty()
    identifier = st.session_state.get("selected_similar_query_id")
    if identifier:
        record = queries.load_query(identifier, queries_dir)
        if record:
            st.divider()
            render_query(record, key=f"similar_{identifier}", queries_dir=queries_dir)
            save_reference(store, actor, queries_dir, record, key=f"similar_{identifier}")
        else:
            st.warning("La investigación guardada ya no está disponible. Podés volver a buscar.")
