from __future__ import annotations

from sensei.config import settings
from sensei.security.vault import KeyVault


def test_set_get_roundtrip_and_encrypted_on_disk(tmp_path):
    path = tmp_path / "vault.json"
    v = KeyVault(path)
    v.set_key("openai", "sk-secret-123")
    assert v.get_key("openai") == "sk-secret-123"
    # Survives a reload (decrypted from disk).
    assert KeyVault(path).get_key("openai") == "sk-secret-123"
    # The key is NOT stored in plaintext.
    assert b"sk-secret-123" not in path.read_bytes()


def test_master_password(tmp_path):
    path = tmp_path / "vault.json"
    KeyVault(path, password="hunter2").set_key("openai", "sk-x")
    # Right password reads it back.
    assert KeyVault(path, password="hunter2").get_key("openai") == "sk-x"
    # Wrong password can't (returns empty, doesn't crash).
    assert KeyVault(path, password="nope").get_key("openai") == ""


def test_apply_to_settings(tmp_path):
    v = KeyVault(tmp_path / "vault.json")
    v.set_key("groq", "sk-groq")
    orig = settings.groq_api_key
    try:
        assert v.apply_to_settings() >= 1
        assert settings.groq_api_key == "sk-groq"
    finally:
        settings.groq_api_key = orig
