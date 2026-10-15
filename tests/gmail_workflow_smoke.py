"""Servidor Gmail ficticio para ejecutar el grafo n8n sin OAuth ni datos reales.

Uso: python -m tests.gmail_workflow_smoke --output <directorio temporal>
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.collaboration.store import EventStore
from integrations.n8n.build_workflow import build_workflow
from tests.test_gmail_pilot import message


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    workflow = build_workflow()
    workflow["id"] = "ragGmailSmoke"
    workflow["name"] = "TEST TEMPORAL · Gmail simulado"
    for node in workflow["nodes"]:
        if node["type"].endswith("httpRequest"):
            node["parameters"]["authentication"] = "none"
            node["parameters"].pop("genericAuthType", None)
        if node["name"] == "Preparar solicitud":
            node["parameters"]["jsCode"] += ""  # Cambia destinos; el motor original se prueba sin alteraciones.
            node["parameters"]["jsCode"] = node["parameters"]["jsCode"].replace(
                "request_url: requestUrl(state)",
                "request_url: requestUrl(state).replace('https://gmail.googleapis.com/gmail/v1/users/me', 'http://host.docker.internal:18787').replace('http://host.docker.internal:8787', 'http://host.docker.internal:18787')")
    (args.output / "workflow.json").write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
    with TemporaryDirectory(prefix="rag-gmail-smoke-") as folder:
        store = EventStore(Path(folder) / "test.sqlite3")
        store.create_event("Piloto Gmail")
        state = {"get_count": 0, "post_count": 0, "ids": [], "paths": [], "retry_injected": False}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def reply(self, body, status=200):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())
            def do_GET(self):
                state["paths"].append(self.path)
                if self.path == "/profile":
                    self.reply({"emailAddress": "test@example.com"})
                elif self.path == "/labels":
                    self.reply({"labels": [{"id": "L", "name": "Evento/piloto-gmail"}, {"id": "INBOX", "name": "INBOX"}]})
                elif self.path.startswith("/messages?"):
                    if "pageToken=" in self.path:
                        self.reply({"messages": [{"id": "old-labelled"}]})
                    else:
                        self.reply({"messages": [{"id": "old-labelled"}], "nextPageToken": "next"})
                elif self.path.startswith("/messages/old-labelled"):
                    if not state["retry_injected"]:
                        state["retry_injected"] = True
                        self.reply({"error": "temporary"}, 503)
                    else:
                        state["get_count"] += 1
                        self.reply(message())
                elif self.path == "/status":
                    self.reply(state)
                else:
                    self.reply({"error": "unexpected"}, 404)
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                record = store.ingest_email(payload)
                state["post_count"] += 1
                state["ids"].append(record["id"])
                (args.output / "result.json").write_text(json.dumps(state), encoding="utf-8")
                self.reply(record, 201)
        print("Gmail simulado listo en 18787", flush=True)
        ThreadingHTTPServer(("0.0.0.0", 18787), Handler).serve_forever()


if __name__ == "__main__":
    main()
