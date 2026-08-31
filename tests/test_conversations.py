"""Persistencia de conversaciones (Fase 5): un JSON por conversacion,
mismo patron que app/ingestion/manifest.py. Todo testeado contra
directorios temporales (tmp_path) -- sin tocar data/conversations/ real.
"""

import json

from anthropic.types.beta import BetaTextBlock

from app.agent.conversations import (
    list_conversations,
    load_conversation,
    new_conversation_id,
    save_conversation,
)


def test_new_conversation_id_es_unico():
    assert new_conversation_id() != new_conversation_id()


def test_save_and_load_conversation_roundtrip(tmp_path):
    conv_id = new_conversation_id()
    api_messages = [{"role": "user", "content": "hola"}]
    display_messages = [{"role": "user", "text": "hola", "sources": [], "chart_paths": []}]

    save_conversation(conv_id, api_messages, display_messages, conversations_dir=tmp_path)
    loaded = load_conversation(conv_id, conversations_dir=tmp_path)

    assert loaded["id"] == conv_id
    assert loaded["api_messages"] == api_messages
    assert loaded["display_messages"] == display_messages
    assert loaded["title"] == "hola"
    assert "created_at" in loaded and "updated_at" in loaded


def test_load_conversation_inexistente_devuelve_none(tmp_path):
    assert load_conversation("no-existe", conversations_dir=tmp_path) is None


def test_save_conversation_serializa_content_blocks_pydantic_del_sdk(tmp_path):
    # api_messages en turnos de assistant trae bloques tipados del SDK de
    # Anthropic (Pydantic), no dicts planos -- tienen que quedar
    # serializados como JSON valido, no explotar ni guardarse como objeto.
    conv_id = new_conversation_id()
    api_messages = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": [BetaTextBlock(type="text", text="respuesta")]},
    ]
    display_messages = [{"role": "user", "text": "hola", "sources": [], "chart_paths": []}]

    save_conversation(conv_id, api_messages, display_messages, conversations_dir=tmp_path)

    # El archivo en disco tiene que ser JSON valido de punta a punta.
    raw = (tmp_path / f"{conv_id}.json").read_text(encoding="utf-8")
    on_disk = json.loads(raw)
    assert on_disk["api_messages"][1]["content"] == [{"type": "text", "text": "respuesta", "citations": None}]

    loaded = load_conversation(conv_id, conversations_dir=tmp_path)
    assert loaded["api_messages"][1]["content"][0]["text"] == "respuesta"


def test_save_conversation_preserva_created_at_pero_actualiza_updated_at(tmp_path):
    conv_id = new_conversation_id()
    display_messages = [{"role": "user", "text": "primera", "sources": [], "chart_paths": []}]

    save_conversation(conv_id, [], display_messages, conversations_dir=tmp_path)
    primera = load_conversation(conv_id, conversations_dir=tmp_path)

    save_conversation(conv_id, [], display_messages, conversations_dir=tmp_path)
    segunda = load_conversation(conv_id, conversations_dir=tmp_path)

    assert segunda["created_at"] == primera["created_at"]


def test_titulo_se_deriva_del_primer_mensaje_de_usuario_y_trunca(tmp_path):
    conv_id = new_conversation_id()
    texto_largo = "x" * 100
    display_messages = [{"role": "user", "text": texto_largo, "sources": [], "chart_paths": []}]

    save_conversation(conv_id, [], display_messages, conversations_dir=tmp_path)
    loaded = load_conversation(conv_id, conversations_dir=tmp_path)

    assert len(loaded["title"]) <= 61  # 60 + el "…" de corte
    assert loaded["title"].startswith("x" * 60)


def test_list_conversations_ordena_por_updated_at_descendente(tmp_path):
    id_vieja = new_conversation_id()
    id_nueva = new_conversation_id()
    msgs = [{"role": "user", "text": "hola", "sources": [], "chart_paths": []}]

    save_conversation(id_vieja, [], msgs, conversations_dir=tmp_path)
    save_conversation(id_nueva, [], msgs, conversations_dir=tmp_path)
    # Forzar que id_nueva tenga updated_at estrictamente mayor sin depender
    # de la resolucion del reloj entre las dos llamadas.
    data = json.loads((tmp_path / f"{id_nueva}.json").read_text(encoding="utf-8"))
    data["updated_at"] = "2099-01-01T00:00:00+00:00"
    (tmp_path / f"{id_nueva}.json").write_text(json.dumps(data), encoding="utf-8")

    result = list_conversations(conversations_dir=tmp_path)

    assert [c["id"] for c in result] == [id_nueva, id_vieja]


def test_list_conversations_devuelve_solo_metadata(tmp_path):
    conv_id = new_conversation_id()
    msgs = [{"role": "user", "text": "hola", "sources": [], "chart_paths": []}]
    save_conversation(conv_id, [], msgs, conversations_dir=tmp_path)

    [entry] = list_conversations(conversations_dir=tmp_path)

    assert set(entry.keys()) == {"id", "title", "updated_at"}
