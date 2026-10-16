from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env from the repo root regardless of the process working directory, so
# the settings API and the server agree on one file.
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# Where per-user data lives, for every Sensei process on the machine. Already
# the home of the integrations manifest and its backups; the savings ledger and
# the CCR store join it so the tray server and an editor-spawned `sensei mcp`
# are looking at the same numbers.
SENSEI_HOME = Path.home() / ".sensei"

# The defaults these settings ship with. Compared against, rather than assumed:
# a value that differs is one the user chose, and it is used verbatim.
_CCR_CACHE_DEFAULT = ".sensei_cache"
_SAVINGS_DB_DEFAULT = ".sensei_savings.db"


def _adopt_legacy_ledger(target: Path) -> None:
    """Carry an existing ledger over to the shared location, once.

    Before this move the ledger sat next to whichever process wrote it, so an
    upgrade would silently reset the dashboard to zero — the one number the user
    installed Sensei to watch. If the new path is empty and an old one is right
    here in the working directory, it moves rather than starts over.

    Copied, not renamed, and only when the destination does not exist, so this
    can never overwrite a ledger that already has data in it.
    """
    if target.exists():
        return
    legacy = Path(_SAVINGS_DB_DEFAULT)
    if not legacy.is_file():
        return
    try:
        import shutil

        shutil.copy2(legacy, target)
        for suffix in ("-wal", "-shm"):
            side = legacy.with_name(legacy.name + suffix)
            if side.is_file():
                shutil.copy2(side, target.with_name(target.name + suffix))
    except OSError:  # pragma: no cover — a read-only or vanished source
        pass


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
        "zai",
        "openrouter",
        "huggingface",
        "openai",
        "anthropic",
        "google",
        "groq",
        "mistral",
        "together",
        "deepseek",
        "cohere",
        "fireworks",
        "perplexity",
        "custom",
    ] = "openrouter"

    # Local model
    local_model_path: str = ""
    local_backend: Literal["llama.cpp", "vllm", "ollama"] = "ollama"
    local_gpu_layers: int = 0
    local_context_size: int = 32768
    local_port: int = 8080

    # Ollama (local, free, no API key)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"

    # Z.ai API (GLM original)
    zai_api_base_url: str = "https://api.z.ai/api/paas/v4"
    zai_api_key: str = ""
    zai_api_model: str = "glm-5.3"

    # OpenRouter API (aggregator — access all models)
    openrouter_api_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    openrouter_api_model: str = "~anthropic/claude-sonnet-latest"

    # HuggingFace Inference Providers (OpenAI-compatible router; the old
    # api-inference.huggingface.co/models endpoint does not speak /chat/completions)
    huggingface_api_base_url: str = "https://router.huggingface.co/v1"
    huggingface_api_key: str = ""
    huggingface_api_model: str = "openai/gpt-oss-120b"

    # OpenAI API (GPT-6 Astra / Sol / Luna)
    openai_api_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_api_model: str = "gpt-6.1-sol"

    # Anthropic / Claude API (Claude 5: Fable, Opus, Sonnet, Haiku)
    anthropic_api_base_url: str = "https://api.anthropic.com/v1"
    anthropic_api_key: str = ""
    anthropic_api_model: str = "claude-sonnet-5-5"

    # Google Gemini API, through its OpenAI-compatible endpoint. The bare
    # /v1beta base has no /chat/completions route — requests 404'd there.
    google_api_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    google_api_key: str = ""
    google_api_model: str = "gemini-3.8-flash"

    # Groq API (ultra-fast inference: gpt-oss, Llama, Qwen)
    groq_api_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: str = ""
    groq_api_model: str = "openai/gpt-oss-120b"

    # Mistral API (Mistral Large, Codestral, etc.)
    mistral_api_base_url: str = "https://api.mistral.ai/v1"
    mistral_api_key: str = ""
    mistral_api_model: str = "mistral-large-latest"

    # Together AI API (GLM, Kimi, Qwen, DeepSeek, gpt-oss)
    together_api_base_url: str = "https://api.together.ai/v1"
    together_api_key: str = ""
    together_api_model: str = "zai-org/GLM-5.3"

    # DeepSeek API (V4 Flash / V4 Pro)
    deepseek_api_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_api_model: str = "deepseek-flash"

    # Cohere, through its OpenAI-compatibility API (the native /v1 chat endpoint
    # takes a different request shape and rejected every forwarded request).
    cohere_api_base_url: str = "https://api.cohere.ai/compatibility/v1"
    cohere_api_key: str = ""
    cohere_api_model: str = "command-a-plus-05-2026"

    # Fireworks AI API (GLM, Kimi, Qwen)
    fireworks_api_base_url: str = "https://api.fireworks.ai/inference/v1"
    fireworks_api_key: str = ""
    fireworks_api_model: str = "accounts/fireworks/models/glm-5p3"

    # Perplexity API (Sonar, etc.)
    perplexity_api_base_url: str = "https://api.perplexity.ai"
    perplexity_api_key: str = ""
    perplexity_api_model: str = "sonar-pro"

    # ── Providers added without pinning a model name ────────────────────────
    #
    # Every entry above ships a default model id, and every one of those is a
    # guess with a shelf life: the catalog still offered gpt-4o and
    # claude-3.5-sonnet long after both were superseded, and a wrong id fails at
    # request time with a message about the model, not about the stale default.
    #
    # These leave the model empty and are listed in `_LIVE_MODEL_PROVIDERS`, so
    # the UI asks the provider what it actually serves today. A name Sensei has
    # never heard of works the moment the provider ships it.

    # Moonshot AI (Kimi)
    moonshot_api_base_url: str = "https://api.moonshot.ai/v1"
    moonshot_api_key: str = ""
    moonshot_api_model: str = ""

    # Alibaba DashScope (Qwen), OpenAI-compatible endpoint
    dashscope_api_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    dashscope_api_key: str = ""
    dashscope_api_model: str = ""

    # xAI (Grok)
    xai_api_base_url: str = "https://api.x.ai/v1"
    xai_api_key: str = ""
    xai_api_model: str = ""

    # Cerebras
    cerebras_api_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_api_key: str = ""
    cerebras_api_model: str = ""

    # DeepInfra
    deepinfra_api_base_url: str = "https://api.deepinfra.com/v1/openai"
    deepinfra_api_key: str = ""
    deepinfra_api_model: str = ""

    # ── Local servers ───────────────────────────────────────────────────────
    # No key, no account, nothing leaves the machine. Each speaks the OpenAI
    # wire format, so Sensei needs only the address.

    # LM Studio
    lmstudio_api_base_url: str = "http://localhost:1234/v1"
    lmstudio_api_key: str = ""
    lmstudio_api_model: str = ""

    # llama.cpp server
    llamacpp_api_base_url: str = "http://localhost:8080/v1"
    llamacpp_api_key: str = ""
    llamacpp_api_model: str = ""

    # vLLM
    vllm_api_base_url: str = "http://localhost:8000/v1"
    vllm_api_key: str = ""
    vllm_api_model: str = ""

    # Legacy single API (backward compat)
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""

    # Compression
    compression_enabled: bool = True
    # Strip characters that cost a token each and render as nothing: zero-width
    # spaces, byte-order marks, word joiners. Measured at 40% overhead on source
    # carrying one per line, which is what pasting out of a web interface does.
    #
    # Also removes bidi overrides and isolates — the Trojan Source vector
    # (CVE-2021-42574), where code renders in one order and compiles in another.
    strip_invisible: bool = True
    # Replace no-break spaces with ordinary ones. Off by default: an NBSP is
    # deliberate in typeset prose, and it is reported either way.
    strip_nbsp: bool = False
    # Replace the middle of any line over 500 characters with a marker.
    #
    # Off, because it is deletion rather than compression and it fires on a
    # distinction the user cannot see: a document with paragraph breaks passes
    # through whole, while the same text pasted out of a PDF is one long line
    # and loses almost all of it. Measured on one document both ways — 160
    # sentences kept with the breaks, 2 without.
    #
    # On, the marker states how much went and that the original is retrievable,
    # so a model reading it can ask rather than answer around the gap.
    text_truncate_paragraphs: bool = False
    # How hard to compress source code.
    #   safe        remove what a compiler ignores (comments, docstrings, blank
    #               lines) and never touch string literals. Code that reaches
    #               the model as a tool result — a file an agent may edit next
    #               by exact string match — passes through byte-exact.
    #   aggressive  also rewrite code in tool results and fold long import
    #               blocks. More savings; agents' exact-match edits can fail.
    code_compression: Literal["safe", "aggressive"] = "safe"

    # ── Compression pipeline (compression/*; owned by the compression work) ──
    # Lossy steps: search-result caps, log and test-output noise, row sampling
    # in large JSON arrays, minified-line and base64 elision, HTML extraction.
    # Every cut leaves `[sensei: <what>; retrieve ccr=<id>]` in place, and the
    # original is in the CCR store under that id. Off keeps only transforms
    # that lose nothing (folds, grouping, tables, minification).
    compression_lossy: bool = True
    # Long prose in tool results.
    #   rules       rewrite verbose phrasing, never drop a sentence (TextCompressor)
    #   extractive  keep whole sentences by relevance to the user's question and
    #               mark the dropped ones (TextCrusher), then the rules pass
    compression_prose: Literal["rules", "extractive"] = "rules"
    # ── end compression pipeline ──

    ccr_ttl_hours: int = 24
    ccr_cache_dir: str = ".sensei_cache"
    # Ask the model for terser answers. Output tokens cost roughly 4-5x input
    # tokens. Off by default: this changes what the model writes, which is the
    # user's call, not ours.
    output_shaper: bool = False
    # Fraction of requests deliberately left unshaped, so the effect can be
    # measured against a control instead of asserted. Setting this to 0 turns
    # the measurement off, not the shaping.
    output_holdout: float = 0.1
    # Override the instruction appended to the last user message. Empty means
    # the built-in one — see sensei/output_shaping.py.
    output_shaper_instruction: str = ""
    # Price assumption for the "money saved" dashboard (USD per 1M input tokens).
    usd_per_million_tokens: float = 3.0
    # Keep a local ledger of savings so the dashboard survives a restart.
    # This is not telemetry: the file never leaves the machine, and it stores
    # counters and a model name per request — never prompt or response text.
    # Set to false and the totals go back to being per-process and in-memory.
    savings_persist: bool = True
    savings_db: str = ".sensei_savings.db"

    # Ask GitHub once a day whether a newer release exists, and show it in the
    # dashboard and tray. Off by default: it is a request to a third party, and
    # Sensei makes none unless you ask. `sensei update --check` works either way.
    update_check: bool = False

    # MCP proxy: other MCP servers (REA, GhidraMCP, filesystem, GitHub, …)
    # behind `sensei_find_tools` / `sensei_call_tool`, with compressed results.
    # Empty = ~/.sensei/mcp-servers.json. Same format as Claude Desktop's.
    mcp_servers_file: str = ""
    # A tool result longer than this (after compression) comes back as a first
    # page plus a ccr_id; `sensei_retrieve` pages through the rest.
    mcp_page_chars: int = 12_000
    # How long a row is kept. The dashboard's longest view is a year.
    savings_retention_days: int = 400
    # Compress system prompts at the gateway too (where IDE tools hide most of
    # their tokens). Lossy — disable for byte-exact system prompts.
    gateway_compress_system: bool = True
    # Compress only the newest message, leaving earlier turns untouched.
    #
    # Do not turn this on to protect a prompt cache. It does the opposite, and
    # the old comment here recommending it for cache-heavy agents was wrong.
    #
    # Compression is deterministic, so the transformed prefix is byte-identical
    # from one turn to the next and the provider's cache hits either way. This
    # setting makes the decision depend on *position*: a message compressed
    # while it was newest arrives uncompressed on the following turn, the bytes
    # change, and the cache misses — every turn, on exactly the agents the
    # comment recommended it for. Measured: prefix hash stable with this off,
    # different with it on.
    #
    # Left in place for the case it is actually good for — keeping older turns
    # verbatim because you want them verbatim, accepting the cache cost.
    gateway_preserve_cache: bool = False
    # Retry a provider that answered 429/5xx (or could not be reached) before
    # giving up. Only ever before the first byte reaches the client — a stream
    # that has started is never replayed. Retry-After is honoured up to
    # upstream_retry_max_wait seconds.
    upstream_retries: int = 2
    upstream_retry_max_wait: float = 8.0
    # Last resort when the provider stays down: send the same request to a
    # local server instead (Ollama, llama.cpp, LM Studio and vLLM all speak
    # /v1/messages, /v1/chat/completions and /v1/responses now). Off by
    # default — a different model answering is a decision, not a default. The
    # response carries `X-Sensei-Fallback` so the switch is never silent.
    fallback_enabled: bool = False
    fallback_base_url: str = "http://localhost:11434"
    fallback_model: str = ""  # empty → ollama_model

    # ── Cache-aware gateway (sensei/gateway/*) ──────────────────────────────
    # Live zone: per conversation, replay what was forwarded last turn byte for
    # byte and compress only the messages that are new. Keeps the provider's
    # prompt cache warm and the history append-only (which Claude's preserved
    # thinking checks). The store is in memory only and holds no more than
    # gateway_live_zone_max_mb of forwarded messages.
    gateway_live_zone: bool = True
    gateway_live_zone_ttl_seconds: int = 7200
    gateway_live_zone_max_sessions: int = 256
    gateway_live_zone_max_mb: int = 256
    # The provider cache lifetime assumed for miss attribution when a request
    # does not say (`cache_control.ttl: "1h"` is honoured).
    gateway_cache_ttl_seconds: int = 300
    # Inject `sensei_retrieve` so the model can fetch the exact original behind
    # a compression marker; the gateway answers the call itself.
    gateway_retrieve_tool: bool = True
    # Answer the call inside the gateway and hide the extra round from the
    # client. Off by default: the client then sees the call, answers "no such
    # tool", and the gateway puts the original into that result on the next
    # request — one more round trip, nothing hidden that has to be recreated.
    # Never used when the response carries thinking or reasoning.
    gateway_retrieve_intercept: bool = False
    gateway_retrieve_max_rounds: int = 3
    gateway_retrieve_max_chars: int = 60_000
    gateway_retrieve_in_streams: bool = True
    # What a retrieve was answered with, and hidden exchanges, per conversation
    # and credential — on disk, so a restart forwards the same history. Holds
    # original tool output (like the CCR store); empty path = ~/.sensei.
    gateway_state_persist: bool = True
    gateway_state_db: str = ""
    gateway_state_ttl_hours: int = 168
    # Lossy blocks saving fewer tokens than this get no retrieve marker.
    gateway_ccr_min_saved_tokens: int = 50
    # Tool definitions: strip JSON-schema annotations the model never needs
    # ($schema, $comment, examples, title, …). Always safe.
    gateway_tool_schema_compaction: bool = True
    # Opt-in: shorten tool descriptions to this many chars (0 = off).
    gateway_tool_description_max_chars: int = 0
    # Opt-in: Anthropic tool search (defer_loading) for first-party Anthropic
    # requests with at least gateway_tool_search_min_tools tools.
    gateway_tool_search: bool = False
    gateway_tool_search_min_tools: int = 12
    # Cross-turn: a new tool result that repeats an earlier one is replaced by
    # a reference to it. Only ever applied to new messages.
    gateway_dedup: bool = True
    gateway_dedup_min_lines: int = 4
    gateway_dedup_min_chars: int = 200
    # A Read result superseded by an Edit of the same file becomes a stub —
    # only where the history is not cached and carries no thinking blocks.
    gateway_stale_reads: bool = True
    # Claude subscription (OAuth) requests keep their tools exactly as sent.
    gateway_oauth_tool_changes: bool = False
    # Opt-in: rule-based model router, JSON list of
    # {"to_model": ..., "max_input_tokens": N, "require_no_tools": bool,
    #  "from_models": [...], "tool_results_only": bool}.
    gateway_model_router: str = ""
    # Opt-in: exact response cache for non-streaming temperature-0 requests.
    gateway_response_cache: bool = False
    gateway_response_cache_ttl_seconds: int = 3600
    gateway_response_cache_max_entries: int = 512
    # Opt-in: per-tool token budgets, "Claude Code=5000000,Codex=2000000",
    # over a rolling window. Over budget → 429 with a message saying so.
    gateway_tool_budgets: str = ""
    gateway_tool_budget_window_hours: float = 24.0

    # Memory
    memory_enabled: bool = True
    memory_dir: str = ".sensei_memory"

    # RAG: local document store + BM25 retrieval (no embedding model needed).
    rag_file: str = ".sensei_rag.json"

    # Watched sources: re-fetch URLs on an interval, re-index changed pages into
    # RAG, and POST a change alert to the per-watch notify_url or this default.
    watch_file: str = ".sensei_watch.json"
    watch_check_interval_minutes: int = 30
    watch_notify_url: str = ""

    # Keep looking for AI tools while the server runs, and point any newly
    # installed one at the gateway. On by default: a tool that is installed but
    # not routed produces no error, just a smaller number on the dashboard.
    # Only ever adds, and never touches a tool disconnected by hand.
    auto_connect: bool = True
    auto_connect_interval_seconds: int = 30

    # ── Integrations: tool-output hooks and remote MCP (integrations area) ──
    # Claude Code, Copilot CLI, Gemini CLI, Cursor and the opencode/Kilo plugin
    # POST tool output to /hooks/* and get a compressed version back. Every
    # hook fails open: off, slow or broken, the tool keeps its original output.
    hook_compression: bool = True
    # Outputs shorter than this go through untouched: below a couple of
    # thousand characters the retrieve hint costs about what compression saves.
    hook_min_chars: int = 2000
    # Replace an output only if this share of its tokens would be saved.
    hook_min_saving: float = 0.15
    # Glob results longer than this are cut, with the full list retrievable.
    hook_max_paths: int = 300
    # Bearer token for `sensei mcp --transport streamable-http`. Empty means
    # generated on first use and kept in ~/.sensei/mcp-token (owner-only).
    mcp_http_token: str = ""

    # Agent: read-only tools sandboxed to agent_root; bounded ReAct loop.
    agent_root: str = "."
    agent_max_steps: int = 6
    agent_max_steps_deep: int = 12  # "deep research" preset (more tool hops)

    # Optional learned prose compressor (the trained Sensei-Compressor). Off by
    # default; falls back to the rule-based TextCompressor if disabled, the
    # checkpoint is missing, or torch/transformers aren't installed.
    learned_compressor_enabled: bool = False
    learned_compressor_path: str = "G:/Projects/Sensei/models/sensei-compressor"
    learned_keep_threshold: float = 0.5
    learned_max_length: int = 256

    # Optional semantic RAG (off by default → zero-dep BM25). Any OpenAI-compatible
    # /embeddings endpoint; falls back to BM25 if a call fails.
    embeddings_enabled: bool = False
    embeddings_base_url: str = "https://api.openai.com/v1"
    embeddings_model: str = "text-embedding-3-small"
    embeddings_api_key: str = ""
    # Web fetch (SSRF-guarded; blocks private/loopback hosts). Web search needs a
    # Brave Search API key. Code execution is OFF by default and NOT sandboxed —
    # it runs on the host, so only enable it on a machine you control.
    web_fetch_enabled: bool = True
    brave_api_key: str = ""
    code_exec_enabled: bool = False
    code_exec_timeout: int = 5

    # Server
    # Loopback by default: a self-hosted workspace holding your API keys and
    # conversations should not be reachable from the LAN unless you say so.
    # Set SENSEI_HOST=0.0.0.0 to expose it (the Docker image does exactly that,
    # where the container boundary is the isolation).
    host: str = "127.0.0.1"
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

    # SSO via OpenID Connect (token-exchange flow). Off by default. The frontend
    # gets an ID token from the IdP and exchanges it at /api/auth/oidc.
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_audience: str = ""  # defaults to client_id when blank
    oidc_jwks_uri: str = ""  # optional override; else discovered from the issuer

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @staticmethod
    def _shared(value: str, default: str, name: str) -> Path:
        """Resolve a path that every Sensei process on the machine must agree on.

        Left at its default it lands in ``~/.sensei``. It used to be relative,
        and so resolved against whatever directory the process happened to start
        in. That is fine while there is one process, and Sensei is not one
        process: the tray server runs from its install directory, while an
        editor spawns `sensei mcp` in whatever project the user has open.

        The result was a savings ledger per project, none of which the dashboard
        could see — for a product whose whole promise is showing what you saved.

        An explicit setting is honoured exactly as written, relative or not:
        someone who configures a path means that path.
        """
        if value != default:
            return Path(value).expanduser()
        return SENSEI_HOME / name

    @property
    def ccr_cache_path(self) -> Path:
        p = self._shared(self.ccr_cache_dir, _CCR_CACHE_DEFAULT, "cache")
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

    @property
    def mcp_servers_path(self) -> Path:
        if self.mcp_servers_file:
            return Path(self.mcp_servers_file).expanduser()
        return SENSEI_HOME / "mcp-servers.json"

    @property
    def savings_db_path(self) -> Path:
        explicit = self.savings_db != _SAVINGS_DB_DEFAULT
        p = self._shared(self.savings_db, _SAVINGS_DB_DEFAULT, "savings.db")
        p.parent.mkdir(parents=True, exist_ok=True)
        if not explicit:
            # Only ever into the shared location. Doing it for a configured path
            # meant a caller who asked for an empty database at a specific place
            # got whatever happened to be lying in the working directory instead
            # — which is how this broke eight ledger tests that each expected to
            # start from nothing.
            _adopt_legacy_ledger(p)
        return p


settings = Settings()
