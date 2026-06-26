from __future__ import annotations

from fastapi.testclient import TestClient

import sensei.routers.settings as settings_router
from sensei.config import settings
from sensei.main import app


def test_get_settings():
    client = TestClient(app)
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "provider" in data
    assert "model" in data
    assert "api_key_set" in data
    assert any(p["id"] == "openrouter" for p in data["catalog"])


def test_put_settings_updates_live_and_persists(tmp_path, monkeypatch):
    import sensei.security.vault as vaultmod

    client = TestClient(app)
    monkeypatch.setattr(settings_router, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(vaultmod, "_vault", vaultmod.KeyVault(tmp_path / "vault.json"))

    orig = (
        settings.api_provider,
        settings.groq_api_key,
        settings.groq_api_model,
        settings.model_provider,
    )
    try:
        resp = client.put(
            "/api/settings",
            json={"provider": "groq", "api_key": "test-key", "model": "llama-3.3-70b-versatile"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "groq"
        assert data["api_key_set"] is True
        assert data["model"] == "llama-3.3-70b-versatile"
        # Live settings updated, so a real request would use the new provider.
        assert settings.api_provider == "groq"
        # Non-secret config goes to .env...
        env_text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "SENSEI_API_PROVIDER=groq" in env_text
        # ...but the API key lives ONLY in the encrypted vault, never plaintext.
        assert vaultmod.get_vault().get_key("groq") == "test-key"
        assert "test-key" not in env_text
        assert b"test-key" not in (tmp_path / "vault.json").read_bytes()
    finally:
        (
            settings.api_provider,
            settings.groq_api_key,
            settings.groq_api_model,
            settings.model_provider,
        ) = orig
        settings_router.registry._provider_cache.clear()


def test_put_settings_rejects_unknown_provider():
    client = TestClient(app)
    resp = client.put("/api/settings", json={"provider": "nope"})
    assert resp.status_code == 400
