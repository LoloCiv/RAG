"""Prepara credenciales locales para importar en n8n sin imprimir secretos.

El archivo temporal debe eliminarse tras importar. OAuth se completa en navegador.
"""

import json
from pathlib import Path
import secrets

from dotenv import dotenv_values, set_key

from integrations.n8n.build_workflow import build_workflow

ROOT = Path(__file__).resolve().parents[2]


def main():
    destination = Path(__file__).parent / ".local"
    if (destination / "prepared.flag").exists():
        raise SystemExit("El piloto ya fue preparado. Editar las credenciales existentes en n8n; no sobrescribir OAuth.")
    env = ROOT / ".env"
    token = dotenv_values(env).get("N8N_WEBHOOK_TOKEN")
    if not token:
        token = secrets.token_urlsafe(40)
        set_key(env, "N8N_WEBHOOK_TOKEN", token)
    destination.mkdir(exist_ok=True)
    credentials = [
        {"id": "ragPilotInbound", "name": "RAG piloto · Bearer local", "type": "httpHeaderAuth",
         "data": {"name": "Authorization", "value": "Bearer " + token}},
        {"id": "ragPilotGmailReadonly", "name": "Gmail piloto · solo lectura", "type": "oAuth2Api",
         "data": {"grantType": "authorizationCode", "authUrl": "https://accounts.google.com/o/oauth2/v2/auth",
                  "accessTokenUrl": "https://oauth2.googleapis.com/token", "clientId": "", "clientSecret": "",
                  "scope": "https://www.googleapis.com/auth/gmail.readonly",
                  "authQueryParameters": "access_type=offline&prompt=consent", "authentication": "body"}}
    ]
    path = destination / "credentials.json"
    if path.exists():
        raise SystemExit("Ya hay un archivo de credenciales temporal. Revisarlo antes de repetir la preparación.")
    path.write_text(json.dumps(credentials), encoding="utf-8")
    workflow = build_workflow()
    for node in workflow["nodes"]:
        if node["name"] == "Recibir correo":
            node["credentials"] = {"httpHeaderAuth": {"id": "ragPilotInbound", "name": credentials[0]["name"]}}
        elif node["name"] == "Gmail solo lectura":
            node["credentials"] = {"oAuth2Api": {"id": "ragPilotGmailReadonly", "name": credentials[1]["name"]}}
    (destination / "workflow.json").write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
    (destination / "prepared.flag").write_text("Prepared once; do not overwrite OAuth.", encoding="utf-8")
    print("Preparación local lista. No repetir después de autorizar OAuth: reemplazaría esa credencial.")


if __name__ == "__main__":
    main()
