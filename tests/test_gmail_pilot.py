"""Ejercita el motor exacto del workflow con Gmail simulado y el endpoint real aislado."""

import base64
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from starlette.testclient import TestClient

from app import webhook_server

ROOT = Path(__file__).resolve().parents[1] / "integrations" / "n8n"
NODE = shutil.which("node")


def js(expression):
    if not NODE:
        pytest.skip("Node.js es necesario para probar el workflow n8n")
    result = subprocess.run([NODE, "-e", ROOT.joinpath("gmail-pilot.js").read_text(encoding="utf-8") +
                             "\nconsole.log(JSON.stringify(" + expression + "));"], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def encoded(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def message(identifier="old-labelled"):
    return {"id": identifier, "threadId": "thread", "internalDate": "1546300800000", "labelIds": ["L", "INBOX"],
            "payload": {"mimeType": "multipart/mixed", "headers": [
                {"name": "From", "value": '"Gómez, Ana" <ana@example.com>'},
                {"name": "To", "value": '"Equipo, Eventos" <events@example.com>, other@example.com'},
                {"name": "Subject", "value": "Cena"}], "parts": [
                {"mimeType": "multipart/alternative", "parts": [
                    {"mimeType": "text/plain", "body": {"data": encoded("Cuerpo completo, leído y antiguo.")}},
                    {"mimeType": "text/html", "body": {"data": encoded("<p>No duplicar</p>")}}]},
                {"mimeType": "application/pdf", "filename": "catering.pdf", "body": {"size": 500, "attachmentId": "A"}}]}}


def state():
    return {"account": "Test@Example.com", "labels": {"L": "Evento/piloto-gmail", "INBOX": "INBOX"}}


def test_mime_addresses_labels_attachment_metadata_and_account_identity():
    result = js(f"normalizeMessage({json.dumps(message())}, {json.dumps(state())})")
    assert result["body_text"] == "Cuerpo completo, leído y antiguo."
    assert len(result["recipients"]) == 2
    assert result["sender"] == '"Gómez, Ana" <ana@example.com>'
    assert result["received_at"].startswith("2019-")
    assert result["external_message_id"] == "gmail:test%40example.com:old-labelled"
    assert result["labels"] == ["Evento/piloto-gmail", "INBOX"]
    assert result["attachments"] == [{"filename": "catering.pdf", "mime_type": "application/pdf", "size": 500, "attachment_id": "A", "part_id": None}]
    other = js(f"normalizeMessage({json.dumps(message())}, {json.dumps({**state(), 'account': 'other@example.com'})})")
    assert other["external_message_id"] != result["external_message_id"]


def test_html_only_is_readable_and_encoded_headers_decode():
    mail = message()
    mail["payload"]["parts"] = [{"mimeType": "text/html", "body": {"data": encoded("<style>x</style><p>Cena &amp; café</p><p>&#225;</p>")}}]
    mail["payload"]["headers"].append({"name": "CC", "value": "=?UTF-8?B?" + base64.b64encode("José".encode()).decode() + "?= <jose@example.com>"})
    result = js(f"normalizeMessage({json.dumps(mail)}, {json.dumps(state())})")
    assert result["body_text"] == "Cena & café\ná"
    assert result["cc"] == ["José <jose@example.com>"]


def test_all_pages_and_old_read_messages_are_processed():
    result = js("""(() => {
      let s = initialState(); const urls = [];
      function step(body) { urls.push(requestUrl(s)); s = transition(s, {statusCode: 200, body}); }
      step({emailAddress:'test@example.com'});
      step({labels:[{id:'L',name:'Evento/piloto-gmail'},{id:'INBOX',name:'INBOX'}]});
      step({messages:[{id:'old-labelled'}], nextPageToken:'next'});
      step(MESSAGE); step({id:'saved'});
      step({messages:[{id:'old-labelled'}]});
      step(MESSAGE); step({id:'saved'});
      return {s, urls};
    })()""".replace("MESSAGE", json.dumps(message())))
    assert result["s"]["stage"] == "done"
    assert result["s"]["pages"] == 2
    assert result["s"]["processed"] == 2
    lists = [url for url in result["urls"] if "/messages?" in url]
    assert len(lists) == 2 and "pageToken=next" in lists[1]
    assert all("unread" not in url and "after" not in url for url in lists)
    assert not any("/attachments/" in url for url in result["urls"])


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_failure_has_three_retries_then_visible_error(status):
    result = js(f"""(() => {{ let s = initialState(); let attempts = 0;
      try {{ while (true) {{ attempts++; s = transition(s, {{statusCode: {status}}}); }} }}
      catch (e) {{return {{attempts, error:e.message}};}}
    }})()""")
    assert result["attempts"] == 4
    assert "tres reintentos" in result["error"]


@pytest.mark.parametrize("status", [400, 401, 403, 422])
def test_permanent_errors_fail_immediately(status):
    result = js(f"(() => {{try {{transition(initialState(), {{statusCode:{status}}});}} catch(e) {{return e.message;}}}})()")
    assert "no se reintenta" in result


def test_connection_retry_does_not_retry_oauth_configuration_errors():
    assert js("transition(initialState(), {error:'connect ECONNREFUSED'})")["retry"] == 1
    assert "no se reintenta" in js("(() => {try {transition(initialState(), {error:'OAuth credentials missing'});} catch(e) {return e.message;}})()")


def test_normalized_payload_reaches_review_without_duplicates_or_auto_confirmation(tmp_path, monkeypatch):
    db = tmp_path / "pilot.sqlite3"
    monkeypatch.setattr(webhook_server, "COLLABORATION_DB_PATH", db)
    monkeypatch.setattr(webhook_server, "N8N_WEBHOOK_TOKEN", "fake-token")
    store = webhook_server.EventStore(db)
    event = store.create_event("Piloto Gmail")
    assert store.last_email_received_at() is None
    payload = js(f"normalizeMessage({json.dumps(message())}, {json.dumps(state())})")
    client = TestClient(webhook_server.app)
    headers = {"authorization": "Bearer fake-token"}
    assert client.post("/n8n/email/inbound", json=payload).status_code == 401
    first = client.post("/n8n/email/inbound", json=payload, headers=headers)
    second = client.post("/n8n/email/inbound", json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["event_suggestion"]["state"] == "suggested"
    assert store.list_event_messages(event["id"]) == []
    assert store.last_email_received_at() > payload["received_at"]


def test_workflow_is_reproducible_inactive_and_contains_no_secrets():
    spec = importlib.util.spec_from_file_location("build_workflow", ROOT / "build_workflow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workflow = json.loads((ROOT / "gmail-pilot.workflow.json").read_text(encoding="utf-8"))
    assert workflow == module.build_workflow()
    assert workflow["active"] is False
    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert nodes["Cada cinco minutos"]["parameters"]["rule"]["interval"][0]["minutesInterval"] == 5
    assert nodes["Gmail solo lectura"]["parameters"]["genericAuthType"] == "oAuth2Api"
    assert not any("credentials" in node or node.get("retryOnFail") for node in nodes.values())


def test_webhook_listen_host_is_configurable(monkeypatch):
    calls = []
    monkeypatch.setattr(webhook_server, "require_webhook_env", lambda: [])
    monkeypatch.setattr(webhook_server, "WEBHOOK_HOST", "0.0.0.0")
    monkeypatch.setattr(webhook_server.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    webhook_server.main()
    assert calls == [{"host": "0.0.0.0", "port": 8787}]
