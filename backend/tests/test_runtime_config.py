import importlib


def test_config_defaults_are_localhost(monkeypatch):
    for key in ("APP_URL", "API_BASE_URL", "APP_BASE_URL", "PORTAL_RETURN_URL", "ALLOWED_ORIGINS"):
        monkeypatch.delenv(key, raising=False)
    import app.config as config
    config = importlib.reload(config)
    assert config.APP_URL == "http://localhost:3000"
    assert config.API_BASE_URL == "http://localhost:8000"
    assert config.PORTAL_RETURN_URL == "http://localhost:3000"
    assert config.allowed_origins() == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_config_uses_canonical_production_values(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://grantrx.com/")
    monkeypatch.setenv("API_BASE_URL", "https://api.grantrx.com/")
    monkeypatch.setenv("PORTAL_RETURN_URL", "https://grantrx.com/account/")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://grantrx.com,https://www.grantrx.com")
    import app.config as config
    config = importlib.reload(config)
    assert config.APP_URL == "https://grantrx.com"
    assert config.API_BASE_URL == "https://api.grantrx.com"
    assert config.PORTAL_RETURN_URL == "https://grantrx.com/account"
    assert config.allowed_origins() == ["https://grantrx.com", "https://www.grantrx.com"]
