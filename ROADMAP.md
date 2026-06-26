# Sensei Roadmap

This document outlines planned features, future directions, and monetization ideas for Sensei.

## Recently shipped (2026-06)

- [x] **Verified 79% real token savings** (tiktoken) — CSV-schema JSON compaction + log triage; reproducible benchmark + ≥60% guardrail test
- [x] **OpenAI + Anthropic compression gateway** — drop-in proxy (`/v1/chat/completions`, `/v1/messages`) with client-key passthrough; routes Claude Code / Codex / Cursor / any SDK
- [x] **Agent-aware compression** — compresses `tool_result` payloads (cache-safe), leaves the system prompt byte-exact
- [x] **Money-saved dashboard** — `SavingsTracker` + `/api/stats`, web StatsPanel hero, VS Code status bar
- [x] **VS Code extension** — chat panel, model selector, chat history, API-key entry, one-click tool routing
- [x] **Runtime settings API** (`/api/settings`) — provider/model/API key with no restart; persisted to `.env`
- [x] **Rust accelerator** (`sensei_core`, PyO3) — CSV hot path ~2× faster, byte-parity, optional
- [x] **AES-256-GCM encryption at rest** (XOR fallback) — authenticated, tamper-detecting
- [x] **Background-server logging** + Windows auto-start; console + `.exe` installers
- [x] **Sensei-Compressor** training scaffold (LLMLingua-2-style, trains on a 16 GB GPU)

## Current Status (v0.1.0)

- [x] Token compression pipeline (SmartCrusher, CodeCompressor, TextCompressor, CacheAligner, CCR)
- [x] 14+ model providers: Ollama, OpenAI, Claude, Gemini, OpenRouter, Groq, DeepSeek, Mistral, Together, Cohere, Fireworks, Perplexity, Z.ai, HuggingFace
- [x] One-command interactive installer (`python install.py`)
- [x] FastAPI backend with WebSocket streaming
- [x] React web UI with chat, stats, settings
- [x] Qt desktop application (PySide6)
- [x] CLI console application
- [x] Per-user sessions with local data isolation
- [x] Auth middleware, rate limiting, data encryption
- [x] Docker Compose deployment with Ollama GPU profile
- [x] Branch protection (PRs required for main)
- [x] Comprehensive test suite

## Short-term (v0.2.0) — Claude-like Client + Enterprise Readiness

### Claude-like Desktop Client
- [ ] **Clean, minimal chat interface** — Claude-inspired UI with zero clutter
- [ ] **Chat history sidebar** — Searchable, organized by date, pin favorites
- [ ] **File & image references** — Drag-and-drop PDFs, images, code files into chat
- [ ] **Model selector dropdown** — Switch between all 14+ providers mid-conversation
- [ ] **Streaming responses** — Token-by-token streaming with cancel button
- [ ] **Markdown rendering** — Code blocks with syntax highlighting, tables, LaTeX
- [ ] **Copy / regenerate / edit messages** — Full message control like Claude
- [ ] **Keyboard-first navigation** — Cmd+K command palette, arrow keys, Enter to send
- [ ] **Low-memory mode** — Lazy-load conversations, virtual scrolling, minimal DOM
- [ ] **Offline indicator** — Show connection status, queue messages when offline
- [ ] **System prompt editor** — Per-conversation custom instructions
- [ ] **Token counter** — Live display of tokens used / saved per message

### Enterprise & Company Features
- [ ] **SSO / SAML integration** — Connect to Okta, Azure AD, Google Workspace
- [ ] **Role-based access control (RBAC)** — Admin, user, readonly roles
- [ ] **Audit logging** — Track all model calls, file accesses, config changes
- [ ] **Data residency controls** — Force all data to stay within specified directory
- [ ] **Compliance exports** — GDPR data export, SOC2 audit trail generation
- [ ] **Shared prompt library** — Team-level prompt templates and system prompts
- [ ] **Usage analytics dashboard** — Token usage, cost tracking, team metrics
- [ ] **API key rotation** — Automatic key rotation with zero downtime
- [ ] **Custom model endpoints** — Connect to private/on-prem model servers

### Security & Data Safety
- [ ] **AES-256 encryption at rest** — Upgrade from XOR to proper AES-256-GCM
- [ ] **TLS 1.3 for all connections** — Encrypted in transit to model provider
- [ ] **API key vault** — Encrypted storage with master password / keyfile
- [ ] **Sandboxed code execution** — Docker-based isolation for code tools
- [ ] **Input sanitization layer** — XSS prevention, prompt injection detection
- [ ] **Rate limit per-user and per-IP** — Granular control
- [ ] **Session token rotation** — Prevent token replay attacks
- [ ] **Data auto-purge** — Configurable TTL for sessions, cache, memory
- [ ] **Zero-knowledge mode** — Provider can never see uncompressed data

### Low Latency & Performance
- [x] **HTTP/2 connection pooling** — Pooled keep-alive clients per upstream (~150 ms/request saved) + cache-preserving compression mode
- [ ] **Response prefetch** — Start compression while user is still typing
- [ ] **CCR cache warming** — Pre-populate cache on startup from last session
- [ ] **Streaming decompression** — Decompress CCR entries on-the-fly
- [ ] **WebSocket keep-alive** — Prevent connection drops during long responses
- [ ] **Request prioritization** — UI interactions prioritized over background tasks
- [ ] **Lazy model loading** — Only initialize provider when first message sent
- [ ] **Client-side caching** — Cache recent responses in browser / desktop app
- [ ] **Edge deployment** — Deploy Sensei close to users via CDN edge nodes

### Proxy & Networking
- [ ] **Reverse proxy support** — Nginx, Caddy, Traefik configuration templates
- [ ] **API proxy mode** — Sensei as a transparent proxy with compression for any LLM API
- [ ] **Load balancer support** — Multiple Sensei instances behind HAProxy
- [ ] **Custom DNS resolution** — Route requests through specific DNS for privacy
- [ ] **Tor / I2P support** — Route API requests through Tor for anonymity
- [ ] **Corporate proxy compatibility** — HTTP_PROXY / HTTPS_PROXY support
- [ ] **Request filtering** — Block specific models, providers, or content patterns
- [ ] **Response filtering** — Redact sensitive data before sending to model

### OpenClaw-style Multi-Channel
- [ ] **Discord bot integration** — Chat with Sensei from Discord servers
- [ ] **Telegram bot** — Use Sensei via Telegram
- [ ] **Slack integration** — Sensei as a Slack app
- [ ] **WhatsApp bridge** — Connect via WhatsApp Web
- [ ] **Matrix support** — Federated chat integration
- [ ] **Email assistant** — Send emails to Sensei, get responses
- [ ] **Webhook API** — Integrate Sensei into any platform via webhooks
- [ ] **Multi-agent routing** — Route different channels to different models/configs

### Improvements
- [ ] **Semantic compression** — Use embeddings to identify and remove redundant context
- [ ] **Adaptive compression** — Learn which compression strategies work best per user
- [ ] **CCR prefetch** — Predict which compressed originals the model will need
- [ ] **Graceful degradation** — Better error messages when providers are unavailable

### Testing
- [ ] **Frontend tests** — Vitest + React Testing Library
- [ ] **E2E tests** — Playwright for web UI
- [ ] **Load tests** — Locust or k6 for rate limiting validation
- [ ] **Coverage reporting** — pytest-cov + codecov integration
- [ ] **Security tests** — Penetration testing, fuzzing, OWASP compliance

## Medium-term (v0.3.0) — RAG, Agents, and Sensei-1 Model

### Sensei-1 Model (Fine-tuned from GLM-5.2)
- [ ] **Training pipeline** — LoRA / QLoRA fine-tuning from GLM-5.2 weights
- [ ] **Training data collection** — Opt-in conversation dataset (anonymized)
- [ ] **Compression-aware training** — Train model to work better with compressed prompts
- [ ] **Domain adaptation** — Code, math, creative writing specializations
- [ ] **DPO / RLHF alignment** — Preference optimization for helpfulness
- [ ] **Quantization** — GGUF, AWQ, GPTQ exports for efficient deployment
- [ ] **Model evaluation suite** — Benchmarks vs GLM-5.2, Claude, GPT-4o
- [ ] **Model card & release** — Open-source release on HuggingFace

### Features
- [ ] **Agent system** — Multi-step task execution with tool use
  - File operations (read, write, search)
  - Web search integration
  - Code execution sandbox
  - Custom tool plugins
- [ ] **RAG (Retrieval-Augmented Generation)** — Upload documents, chat with them
  - Vector embeddings stored locally (ChromaDB or FAISS)
  - Automatic chunking and indexing
  - Citation tracking
  - Multi-document queries
- [ ] **Conversation branching** — Fork conversations at any point
- [ ] **Prompt templates** — Save and reuse prompt templates
- [ ] **Shared conversations** — Export and import conversation files
- [ ] **Multi-model comparison** — Send same prompt to multiple models, compare outputs
- [ ] **Token budget alerts** — Warn when approaching API limits
- [ ] **Offline mode** — Queue messages when no provider is available
- [ ] **Voice input/output** — Whisper integration for speech-to-text
- [ ] **Image understanding** — Vision model support (GPT-4o vision, Gemini)

### Security
- [ ] **End-to-end encryption** — Encrypt data in transit to model provider
- [ ] **API key vault** — Encrypted storage for API keys with master password
- [ ] **Audit log** — Track all API calls and model interactions
- [ ] **Sandboxed code execution** — Isolated environment for code tools

### Deployment
- [ ] **Kubernetes manifests** — Helm chart for K8s deployment
- [ ] **Systemd service files** — Native Linux service installation
- [ ] **Windows installer** — MSI or NSIS installer for Qt GUI
- [ ] **macOS app bundle** — .dmg for Qt GUI
- [ ] **Reverse proxy guide** — Nginx/Caddy configuration templates
- [ ] **CI/CD pipeline** — GitHub Actions for auto-deploy

## Long-term (v1.0.0) — Platform & Ecosystem

### Features
- [ ] **Plugin system** — Third-party extensions for compression, tools, UI
- [ ] **Model quantization tools** — Built-in GGUF quantization for local deployment
- [ ] **Distributed inference** — Split model across multiple GPUs/machines
- [ ] **Image generation** — Integration with Stable Diffusion / Flux
- [ ] **Code IDE plugin** — VS Code extension using Sensei backend
- [ ] **Mobile responsive UI** — Tablet and phone-optimized web interface
- [ ] **Collaborative sessions** — Multiple users in one conversation (local network)
- [ ] **Live Canvas** — Agent-driven visual workspace (OpenClaw-style A2UI)
- [ ] **Skills marketplace** — Community-contributed agent skills and tools
- [ ] **Multi-agent orchestration** — Multiple specialized agents working together

### Enterprise Platform
- [ ] **Multi-tenant architecture** — Isolated workspaces for different teams
- [ ] **SSO + SCIM provisioning** — Automated user management
- [ ] **Compliance dashboard** — GDPR, HIPAA, SOC2 compliance controls
- [ ] **Data loss prevention (DLP)** — Prevent sensitive data from reaching models
- [ ] **Custom model hosting** — Deploy Sensei-1 on your own GPU infrastructure
- [ ] **Federated learning** — Train Sensei-1 across multiple organizations
- [ ] **Model governance** — Approval workflows for model changes
- [ ] **Cost center billing** — Track and bill AI usage per department

### Monetization Ideas

These are ideas to sustain development while keeping the core product free and open source:

1. **Hosted Sensei Cloud** (freemium)
   - Free tier: 100 messages/month with compression
   - Pro tier ($9/mo): 10,000 messages, priority compression, RAG
   - Team tier ($49/mo): 50,000 messages, shared conversations, audit logs
   - Enterprise ($499/mo): Unlimited, SSO, RBAC, custom models, SLA
   - All tiers use the same open-source code — paying for managed hosting

2. **Enterprise License**
   - Self-hosted with support, SLA, custom integrations
   - On-premise deployment assistance
   - Custom compression strategies for specific industries
   - Sensei-1 model licensing for commercial use
   - White-label Sensei for your brand

3. **Marketplace**
   - Sell premium prompt templates
   - Custom compression plugins
   - Industry-specific agent tools and skills
   - Fine-tuned model variants
   - Revenue share with plugin authors

4. **API Service**
   - "Compression-as-a-Service" API — send prompts, get compressed versions back
   - Usage-based pricing for non-Sensei users who want token savings
   - Free tier: 1,000 compressions/month
   - Enterprise: unlimited, dedicated infrastructure

5. **Desktop App Pro**
   - Free desktop client with basic features
   - One-time $19 "Pro" unlock: themes, export, search, templates
   - All features remain in open-source code, Pro is a convenience license

6. **Sensei-1 Model Licensing**
   - Open-source model free for personal/research use
   - Commercial license for enterprise deployment
   - Custom fine-tuning service for specific domains

7. **Sponsorships & Grants**
   - GitHub Sponsors
   - Open-source AI grants
   - Corporate sponsorship for specific features
   - NVIDIA / AMD GPU grants for model training

### Principles
- **Core will always be free and open source** (MIT license)
- **No paywalled features in the codebase** — Pro features are convenience layers
- **No telemetry or tracking** — Even in paid tiers
- **Self-hosting always supported** — Cloud is optional, never required
- **Community first** — PRs from community always welcome
- **Your data, your model** — Train on your data, keep your weights

## Contributing

We welcome contributions! Areas that need help:

- **Compression algorithms** — Better heuristics for code, JSON, prose
- **Model provider integrations** — New providers, better error handling
- **UI/UX** — Frontend improvements, accessibility, mobile
- **Testing** — More test coverage, E2E tests, performance benchmarks
- **Documentation** — Tutorials, guides, API docs, translations
- **DevOps** — CI/CD, Docker optimization, Kubernetes

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Changelog

### v0.1.0 (Initial Release)
- Token compression pipeline (60-95% reduction)
- 14+ model providers: Ollama, OpenAI, Claude, Gemini, OpenRouter, Groq, DeepSeek, Mistral, Together AI, Cohere, Fireworks, Perplexity, Z.ai, HuggingFace
- One-command installer (`python install.py`) with interactive provider selection
- Web UI, Qt GUI, CLI, REST API
- Per-user sessions, auth, rate limiting, data encryption
- Docker Compose deployment with optional Ollama GPU profile
- Comprehensive test suite
