"""Genera el workflow sin secretos a partir del mismo motor que ejercitan las pruebas."""

import json
from pathlib import Path

ROOT = Path(__file__).parent
ENGINE = (ROOT / "gmail-pilot.js").read_text(encoding="utf-8")


def build_workflow():
    nodes, connections = [], {}

    def node(name, kind, parameters, x, y, version=1, **extras):
        nodes.append(dict(id=name.lower().replace(" ", "-"), name=name, type="n8n-nodes-base." + kind,
                          typeVersion=version, position=[x, y], parameters=parameters, **extras))

    def code(name, source, x, y):
        node(name, "code", {"jsCode": source, "mode": "runOnceForAllItems"}, x, y, version=2)

    def edge(source, target, output=0):
        main = connections.setdefault(source, {"main": []})["main"]
        while len(main) <= output:
            main.append([])
        main[output].append({"node": target, "type": "main", "index": 0})

    def condition(name, expression, x, y):
        node(name, "if", {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict", "version": 2},
             "conditions": [{"id": name, "leftValue": expression, "rightValue": True,
                             "operator": {"type": "boolean", "operation": "true", "singleValue": True}}], "combinator": "and"}, "options": {}}, x, y, version=2.2)

    node("Ejecutar manualmente", "manualTrigger", {}, 0, 0)
    node("Cada cinco minutos", "scheduleTrigger", {"rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}}, 0, 180, version=1.2)
    code("Configurar etiqueta", ENGINE + "\nreturn [{json: initialState('Evento/piloto-gmail')}];", 240, 0)
    code("Preparar solicitud", ENGINE + "\nconst state = $input.first().json; return [{json: {...state, request_url: requestUrl(state)}}];", 480, 0)
    condition("Enviar al RAG", "={{ $json.stage === 'inbound' }}", 710, 0)
    for name, credential, y in [("Gmail solo lectura", "oAuth2Api", 160), ("Recibir correo", "httpHeaderAuth", -160)]:
        params = {"url": "={{ $json.request_url }}", "authentication": "genericCredentialType", "genericAuthType": credential,
                  "options": {"timeout": 30000, "redirect": {"redirect": {"followRedirects": False}},
                              "response": {"response": {"fullResponse": True, "neverError": True, "responseFormat": "json"}}}}
        if credential == "httpHeaderAuth":
            params.update(method="POST", sendBody=True, specifyBody="json", jsonBody="={{ JSON.stringify($json.payload) }}")
        node(name, "httpRequest", params, 930, y, version=4.2, onError="continueRegularOutput")
        handler = "Procesar " + name
        code(handler, ENGINE + "\nreturn [{json: transition($('Preparar solicitud').item.json, $input.first().json)}];", 1170, y)
        edge(name, handler)
        edge(handler, "Reintentar con espera")
    condition("Reintentar con espera", "={{ $json.retry > 0 }}", 1410, 0)
    node("Esperar dos segundos", "wait", {"amount": 2, "unit": "seconds"}, 1410, 240, version=1.1, webhookId="rag-gmail-retry")
    condition("Quedan solicitudes", "={{ $json.stage !== 'done' }}", 1650, 0)
    code("Resumen", "return [{json: {cuenta: $json.account, etiqueta: $json.label, paginas: $json.pages, correos_procesados: $json.processed, resultado: 'Ingresados a revisión; los duplicados se conservan una sola vez.'}}];", 1880, 0)
    edge("Ejecutar manualmente", "Configurar etiqueta")
    edge("Cada cinco minutos", "Configurar etiqueta")
    edge("Configurar etiqueta", "Preparar solicitud")
    edge("Preparar solicitud", "Enviar al RAG")
    edge("Enviar al RAG", "Recibir correo")
    edge("Enviar al RAG", "Gmail solo lectura", 1)
    edge("Reintentar con espera", "Esperar dos segundos")
    edge("Esperar dos segundos", "Preparar solicitud")
    edge("Reintentar con espera", "Quedan solicitudes", 1)
    edge("Quedan solicitudes", "Preparar solicitud")
    edge("Quedan solicitudes", "Resumen", 1)
    return {"id": "ragGmailPilot", "name": "RAG · Gmail piloto de solo lectura", "active": False, "nodes": nodes,
            "connections": connections, "settings": {"executionOrder": "v1", "saveExecutionProgress": True,
            "saveDataSuccessExecution": "none", "saveDataErrorExecution": "all", "timezone": "America/Argentina/Buenos_Aires"}, "pinData": {}}


if __name__ == "__main__":
    (ROOT / "gmail-pilot.workflow.json").write_text(json.dumps(build_workflow(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
