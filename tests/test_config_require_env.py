from app import config


def test_require_query_env_does_not_require_drive_or_neo4j(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(config, "VOYAGE_API_KEY", "x")
    monkeypatch.setattr(config, "GOOGLE_DRIVE_FOLDER_ID", None)
    monkeypatch.setattr(config, "NEO4J_PASSWORD", None)
    assert config.require_query_env() == []


def test_require_query_env_requires_anthropic_and_voyage(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "VOYAGE_API_KEY", None)
    assert set(config.require_query_env()) == {"ANTHROPIC_API_KEY", "VOYAGE_API_KEY"}


def test_require_env_still_requires_all_four(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "GOOGLE_DRIVE_FOLDER_ID", "NEO4J_PASSWORD"):
        monkeypatch.setattr(config, name, None)
    assert set(config.require_env()) == {"ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "GOOGLE_DRIVE_FOLDER_ID", "NEO4J_PASSWORD"}
