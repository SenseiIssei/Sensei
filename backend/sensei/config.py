from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env from the repo root regardless of the process working directory, so
# the settings API and the server agree on one file.
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENSEI_",
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Model provider
    model_provider: Literal["auto", "local", "api"] = "auto"

    # API provider selection
    api_provider: Literal[
        "zai", "openrouter", "huggingface", "openai", "anthropic",
        "google", "groq", "mistral", "together", "deepseek", "cohere",
        "fireworks", "perplexity", "custom"
    ] = "openrouter"

    # Local model
    local_model_path: str = ""
    local_backend: Literal["llama.cpp", "vllm", "ollama"] = "ollama"
    local_gpu_layers: int = 0
    local_context_size: int = 32768
    local_port: int = 8080

    # Ollama (local, free, no API key)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "glm-5.2"

    # Z.ai API (GLM original)
    zai_api_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zai_api_key: str = ""
    zai_api_model: str = "glm-5.2"

    # OpenRouter API (aggregator — access all models)
    openrouter_api_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    openrouter_api_model: str = "zhipuai/glm-5.2"

    # HuggingFace API
    huggingface_api_base_url: str = "https://api-inference.huggingface.co/models"
    huggingface_api_key: str = ""
    huggingface_api_model: str = "THUDM/glm-5.2-744b"

    # OpenAI API (GPT-4o, GPT-4o-mini, o1, o3, etc.)
    openai_api_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_api_model: str = "gpt-4o"

    # Anthropic / Claude API (Claude 3.5 Sonnet, Opus, Haiku)
    anthropic_api_base_url: str = "https://api.anthropic.com/v1"
    anthropic_api_key: str = ""
    anthropic_api_model: str = "claude-3-5-sonnet-20241022"

    # Google Gemini API (Gemini 2.0 Flash, Pro, etc.)
    google_api_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    google_api_key: str = ""
    google_api_model: str = "gemini-2.0-flash"

    # Groq API (ultra-fast inference, Llama, Mixtral, etc.)
    groq_api_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: str = ""
    groq_api_model: str = "llama-3.3-70b-versatile"

    # Mistral API (Mistral Large, Codestral, etc.)
    mistral_api_base_url: str = "https://api.mistral.ai/v1"
    mistral_api_key: str = ""
    mistral_api_model: str = "mistral-large-latest"

    # Together AI API (Llama, Qwen, DeepSeek, etc.)
    together_api_base_url: str = "https://api.together.xyz/v1"
    together_api_key: str = ""
    together_api_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    # DeepSeek API (DeepSeek V3, R1, etc.)
    deepseek_api_base_url: str = "https://api.deepseek.com/v1"
    deepseek_api_key: str = ""
    deepseek_api_model: str = "deepseek-chat"

    # Cohere API (Command R+, etc.)
    cohere_api_base_url: str = "https://api.cohere.com/v1"
    cohere_api_key: str = ""
    cohere_api_model: str = "command-r-plus"

    # Fireworks AI API (Llama, Qwen, etc.)
    fireworks_api_base_url: str = "https://api.fireworks.ai/inference/v1"
    fireworks_api_key: str = ""
    fireworks_api_model: str = "accounts/fireworks/models/llama-v3p3-70b-instruct"

    # Perplexity API (Sonar, etc.)
    perplexity_api_base_url: str = "https://api.perplexity.ai"
    perplexity_api_key: str = ""
    perplexity_api_model: str = "sonar-pro"

    # Legacy single API (backward compat)
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""

    # Compression
    compression_enabled: bool = True
    ccr_ttl_hours: int = 24
    ccr_cache_dir: str = ".sensei_cache"
    output_shaper: bool = False
    # Price assumption for the "money saved" dashboard (USD per 1M input tokens).
    usd_per_million_tokens: float = 3.0
    # Compress system prompts at the gateway too (where IDE tools hide most of
    # their tokens). Lossy — disable for byte-exact system prompts.
    gateway_compress_system: bool = True
    # Cache-preserving mode: only compress the newest message (the fresh tool
    # output), leaving earlier turns byte-exact so provider prompt caches still
    # hit. Big latency win for agents like Claude Code; slightly less total
    # compression. Recommended ON when routing a cache-heavy agent.
    gateway_preserve_cache: bool = False

    # Memory
    memory_enabled: bool = True
    memory_dir: str = ".sensei_memory"

    # Server
    host: str = "0.0.0.0"
    port: int = 7000
    # Optional rotating log file for the (often hidden) background server.
    log_file: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:7000"

    # Security
    auth_enabled: bool = False
    auth_token: str = ""
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    max_message_length: int = 32_768
    data_encryption_enabled: bool = True
    # Audit log (metadata only — never prompt contents).
    audit_enabled: bool = True
    audit_file: str = ".sensei_audit.jsonl"
    # Data auto-purge: drop expired sessions/CCR + audit entries older than N
    # days, every purge_interval_minutes (0 disables the loop).
    audit_max_days: int = 30
    purge_interval_minutes: int = 60
    # DLP: redact secrets (and optionally PII) before prompts leave the machine.
    redaction_enabled: bool = False
    redaction_pii: bool = False
    # Request policy: block models (comma-separated substrings) or content
    # (comma-separated regexes) at the gateway. Empty = allow everything.
    blocked_models: str = ""
    blocked_patterns: str = ""
    # Encrypted API-key vault. Optional master password; otherwise machine key.
    vault_file: str = ".sensei_vault.json"
    vault_password: str = ""

    # Sessions
    session_timeout_minutes: int = 60
    session_dir: str = ".sensei_sessions"

    # Webhook API: an authenticated entry point for external platforms (Slack,
    # Zapier, bots). Disabled unless both are set.
    webhook_enabled: bool = False
    webhook_token: str = ""

    # RBAC: when enabled, admin-only endpoints (settings, audit, purge) require a
    # user JWT with the admin role. admin_emails (comma-separated) get that role
    # at registration. Off by default so local/self-hosted use needs no auth.
    rbac_enabled: bool = False
    admin_emails: str = ""

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
