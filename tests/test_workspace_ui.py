"""Recorridos de usuario sin servicios externos ni gasto de modelos."""

import pytest
from streamlit.testing.v1 import AppTest

from app.agent import inbox, queries
from app.collaboration.store import EventStore
from tests.test_event_store import _email


@pytest.fixture
def workspace_ui(tmp_path):
    db = tmp_path / "workspace.sqlite3"
    folder = tmp_path / "queries"
    store = EventStore(db)
    script = f'''
from pathlib import Path
from app.ui.shell import render_app
from app.collaboration.store import EventStore
render_app(store=EventStore(Path({str(db)!r})), actor="tester@company.com", queries_dir=Path({str(folder)!r}))
'''
    return store, folder, lambda: AppTest.from_string(script, default_timeout=20).run()


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def _select(app, label):
    return next(widget for widget in app.selectbox if widget.label == label)


def _healthy(app):
    assert not app.exception
    assert not app.error


def test_empty_navigation_does_not_initialize_rag(workspace_ui, monkeypatch):
    def unavailable(*args, **kwargs):
        raise AssertionError("No se debe inicializar el RAG al navegar")

    monkeypatch.setattr(inbox.claude_agent, "_init_turn", unavailable)
    _, _, make_app = workspace_ui
    app = make_app()
    _healthy(app)
    assert app.title[0].value == "Eventos"
    assert any("Todavía no hay eventos" in info.value for info in app.info)
    assert all("Aprobar" not in button.label for button in app.button)
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    _healthy(app)
    assert _select(app, "Historial de consultas").value is None
    app.radio(key="workspace_page").set_value("Configuración").run()
    _healthy(app)
    assert app.title[0].value == "Configuración"


def test_review_archive_and_preserve_conversations(workspace_ui):
    store, _, make_app = workspace_ui
    event = store.create_event("Cena anual")
    message = store.ingest_email(_email(body_text="Propuesta completa para leer antes de confirmar"))
    app = make_app()
    assert any("Propuesta completa" in item.value for item in app.text)
    _button(app, "Confirmar asociación").click().run()
    _healthy(app)
    assert store.list_event_messages(event["id"])[0]["id"] == message["id"]
    assert [metric.value for metric in app.metric] == ["1", "0", "0"]
    _button(app, "Archivar evento").click().run()
    _healthy(app)
    assert store.list_events() == []
    assert any("Archivado" in caption.value for caption in app.caption)
    assert any("Propuesta completa" in item.value for item in app.text)


def test_save_reference_and_handle_deleted_query(workspace_ui):
    store, folder, make_app = workspace_ui
    event = store.create_event("Cena anual")
    record = queries.save_query(queries.new_query_id(), "Costo histórico", {"answer_text": "Costo con evidencia"}, queries_dir=folder)
    app = make_app()
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    _select(app, "Historial de consultas").set_value(record["id"]).run()
    _select(app, "Guardar en un evento").set_value(event["id"])
    _button(app, "Guardar como antecedente").click().run()
    _healthy(app)
    assert store.list_query_links(event["id"])[0]["query_id"] == record["id"]
    app.radio(key="workspace_page").set_value("Eventos").run()
    assert any("Costo con evidencia" in item.value for item in app.markdown)
    (folder / f"{record['id']}.json").unlink()
    app.run()
    assert any("Antecedente no disponible" in item.value for item in app.warning)
    _button(app, "Quitar vínculo").click().run()
    _healthy(app)
    assert store.list_query_links(event["id"]) == []


def test_session_continuity_survives_navigation_and_other_users(workspace_ui, monkeypatch):
    store, folder, make_app = workspace_ui
    event = store.create_event("Cena anual")
    message = store.ingest_email(_email(body_text="CORREO_ACTUAL_NO_DEBE_IR_AL_RAG"))
    store.confirm_event_message(event["id"], message["id"], "actor")
    selected = queries.save_query(queries.new_query_id(), "Mi investigación", {"answer_text": "Mi contexto"}, queries_dir=folder)
    app = make_app()
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    _select(app, "Historial de consultas").set_value(selected["id"]).run()
    app.radio(key="workspace_page").set_value("Eventos").run()
    queries.save_query(queries.new_query_id(), "Otra persona", {}, queries_dir=folder)
    second = make_app()
    second.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    assert _select(second, "Historial de consultas").value is None
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    assert _select(app, "Historial de consultas").value == selected["id"]
    calls = []

    def fake_stream(question, **kwargs):
        calls.append((question, kwargs))
        yield {"type": "tool_start", "label": "Consultando antecedentes"}
        yield {"type": "text_delta", "text": "Resultado histórico"}
        record = queries.save_query(queries.new_query_id(), question, {"answer_text": "Resultado histórico"}, references=kwargs["references"], queries_dir=folder)
        yield {"type": "final", "record": record}

    monkeypatch.setattr(inbox, "ask_streaming", fake_stream)
    app.text_area[0].set_value("Compará los costos")
    _button(app, "Consultar").click().run()
    _healthy(app)
    assert calls[0][1]["references"] == [selected["id"]]
    assert "additional_context" not in calls[0][1]
    assert "CORREO_ACTUAL" not in str(calls)
    assert _select(app, "Historial de consultas").value != selected["id"]
    next(check for check in app.checkbox if check.label.startswith("Continuar")).uncheck()
    app.text_area[0].set_value("Una pregunta independiente")
    _button(app, "Consultar").click().run()
    _healthy(app)
    assert calls[1][1]["references"] is None


def test_query_failure_retains_question_and_offers_retry(workspace_ui, monkeypatch):
    _, _, make_app = workspace_ui
    def unavailable(*args, **kwargs):
        raise ConnectionError("offline")
    monkeypatch.setattr(inbox, "ask_streaming", unavailable)
    app = make_app()
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    app.text_area[0].set_value("Pregunta que quiero conservar")
    _button(app, "Consultar").click().run()
    assert not app.exception
    assert app.text_area[0].value == "Pregunta que quiero conservar"
    assert any("podés volver a consultar" in item.value for item in app.error)


def test_create_event_and_selection_survive_navigation(workspace_ui):
    store, _, make_app = workspace_ui
    app = make_app()
    app.text_input[0].set_value("Evento nuevo")
    _button(app, "Crear evento").click().run()
    _healthy(app)
    first = store.list_events()[0]
    store.create_event("Otro evento")
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    app.radio(key="workspace_page").set_value("Eventos").run()
    _healthy(app)
    assert _select(app, "Elegí un evento").value == first["id"]


def test_unassigned_message_can_be_assigned_and_search_filters_results(workspace_ui):
    store, _, make_app = workspace_ui
    event = store.create_event("Cena anual")
    message = store.ingest_email(_email(labels=[], body_text="Condiciones especiales"))
    app = make_app()
    _select(app, "Asignar al evento").set_value(event["id"])
    _button(app, "Confirmar asociación").click().run()
    _healthy(app)
    assert store.list_pending_messages()["total"] == 0
    assert store.list_event_messages(event["id"])[0]["id"] == message["id"]
    next(field for field in app.text_input if field.label == "Buscar en asunto y contenido").set_value("Sin coincidencia").run()
    assert any("No hay conversaciones que coincidan" in info.value for info in app.info)
    next(field for field in app.text_input if field.label == "Buscar en asunto y contenido").set_value("ESPECIALES").run()
    assert any("Condiciones especiales" in item.value for item in app.text)


def test_similar_research_persists_and_can_be_linked_without_email_context(workspace_ui, monkeypatch):
    from app.similar_events import service
    from tests.test_similar_events import run_search

    store, folder, make_app = workspace_ui
    event = store.create_event("Cena actual")
    store.ingest_email(_email(body_text="CORREO_ACTUAL_NO_USAR"))
    calls = []
    def fake(request, **kwargs):
        calls.append(request.model_dump())
        return run_search(folder)
    monkeypatch.setattr(service, "find_similar_events", fake)
    app = make_app()
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    app.text_area(key="similar_description").set_value("Cena con catering")
    app.number_input(key="similar_attendees").set_value(150)
    _button(app, "Encontrar antecedentes").click().run()
    _healthy(app)
    assert calls == [{"description": "Cena con catering", "event_type": None, "attendees": 150, "location": None}]
    assert any("Cena Aurora" in item.value for item in app.subheader)
    _select(app, "Guardar en un evento").set_value(event["id"])
    _button(app, "Guardar como antecedente").click().run()
    assert len(store.list_query_links(event["id"])) == 1
    app.radio(key="workspace_page").set_value("Eventos").run()
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    _healthy(app)
    assert app.text_area(key="similar_description").value == "Cena con catering"
    assert any("Cena Aurora" in item.value for item in app.subheader)


def test_similar_error_keeps_draft_and_recovers(workspace_ui, monkeypatch):
    from app.similar_events import service
    _, _, make_app = workspace_ui
    def fail(*args, **kwargs):
        raise ConnectionError("offline")
    monkeypatch.setattr(service, "find_similar_events", fail)
    app = make_app()
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    app.text_area(key="similar_description").set_value("Cena corporativa")
    _button(app, "Encontrar antecedentes").click().run()
    assert not app.exception
    assert any("podés reintentar" in error.value for error in app.error)
    app.radio(key="workspace_page").set_value("Eventos").run()
    app.radio(key="workspace_page").set_value("Consultar antecedentes").run()
    assert app.text_area(key="similar_description").value == "Cena corporativa"
