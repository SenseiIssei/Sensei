from __future__ import annotations

import pytest

from sensei.config import Settings


class TestConfig:
    def test_default_settings(self):
        s = Settings()
        assert s.model_provider == "auto"
        assert s.compression_enabled is True
        assert s.memory_enabled is True
        assert s.host == "0.0.0.0"
        assert s.port == 7000

    def test_multi_provider_defaults(self):
        s = Settings()
        assert s.api_provider == "openrouter"
        assert s.ollama_host == "http://localhost:11434"
        assert s.ollama_model == "glm-5.2"
        assert s.openrouter_api_base_url == "https://openrouter.ai/api/v1"
        assert s.zai_api_base_url == "https://open.bigmodel.cn/api/paas/v4"

    def test_security_defaults(self):
        s = Settings()
        assert s.auth_enabled is False
        assert s.rate_limit_enabled is True
        assert s.rate_limit_requests == 60
        assert s.max_message_length == 32768
        assert s.data_encryption_enabled is True

    def test_session_defaults(self):
        s = Settings()
        assert s.session_timeout_minutes == 60
        assert s.session_dir == ".sensei_sessions"

    def test_cors_origin_list(self):
        s = Settings()
        origins = s.cors_origin_list
        assert isinstance(origins, list)
        assert "http://localhost:5173" in origins

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SENSEI_PORT", "8000")
        monkeypatch.setenv("SENSEI_AUTH_ENABLED", "true")
        s = Settings()
        assert s.port == 8000
        assert s.auth_enabled is True
