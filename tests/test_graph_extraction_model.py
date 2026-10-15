from types import SimpleNamespace

from app.graph import extraction


def test_graph_extraction_uses_extraction_model_not_agent_model(monkeypatch):
    captured = {}

    class FakeMessages:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(parsed_output=extraction.ExtractionResult(entities=[], relationships=[]))

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(extraction, "_get_client", lambda: fake_client)
    monkeypatch.setattr(extraction, "EXTRACTION_MODEL", "extraction-model")

    extraction.extract_from_document("texto", "archivo.pdf")

    assert captured["model"] == "extraction-model"
