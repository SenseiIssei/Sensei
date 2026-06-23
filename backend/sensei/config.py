from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENSEI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Model provider
    model_provider: Literal["auto", "local", "api"] = "auto"

    # API provider selection
    api_provider: Literal["zai", "openrouter", "huggingface", "custom"] = "openrouter"

    # Local model
    local_model_path: str = ""
    local_backend: Literal["llama.cpp", "vllm", "ollama"] = "ollama"
    local_gpu_layers: int = 0
    local_context_size: int = 32768
    local_port: int = 8080

    # Ollama (local, free, no API key)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "glm-5.2"

    # Z.ai API
    zai_api_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zai_api_key: str = ""
    zai_api_model: str = "glm-5.2"

    # OpenRouter API
    openrouter_api_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    openrouter_api_model: str = "zhipuai/glm-5.2"

    # HuggingFace API
    huggingface_api_base_url: str = "https://api-inference.huggingface.co/models"
    huggingface_api_key: str = ""
    huggingface_api_model: str = "THUDM/glm-5.2-744b"

    # Legacy single API (backward compat)
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""

    # Compression
    compression_enabled: bool = True
    ccr_ttl_hours: int = 24
    ccr_cache_dir: str = ".sensei_cache"
    output_shaper: bool = False

    # Memory
    memory_enabled: bool = True
    memory_dir: str = ".sensei_memory"

    # Server
    host: str = "0.0.0.0"
    port: int = 7000
    cors_origins: str = "http://localhost:5173,http://localhost:7000"

    # Security
    auth_enabled: bool = False
    auth_token: str = ""
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    max_message_length: int = 32_768
    data_encryption_enabled: bool = True

    # Sessions
    session_timeout_minutes: int = 60
    session_dir: str = ".sensei_sessions"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ccr_cache_path(self) -> Path:
        p = Path(self.ccr_cache_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def memory_path(self) -> Path:
        p = Path(self.memory_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def session_path(self) -> Path:
        p = Path(self.session_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
