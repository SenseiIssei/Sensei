# Sensei Roadmap

This document outlines planned features, future directions, and monetization ideas for Sensei.

## Current Status (v0.1.0)

- [x] Token compression pipeline (SmartCrusher, CodeCompressor, TextCompressor, CacheAligner, CCR)
- [x] Multi-provider model support (Ollama, OpenRouter, Z.ai, HuggingFace)
- [x] FastAPI backend with WebSocket streaming
- [x] React web UI with chat, stats, settings
- [x] Qt desktop application (PySide6)
- [x] CLI console application
- [x] Per-user sessions with local data isolation
- [x] Auth middleware, rate limiting, data encryption
- [x] Docker Compose deployment with Ollama profile
- [x] Comprehensive test suite

## Short-term (v0.2.0)

### Features
- [ ] **Document upload & processing** — PDF, Markdown, code files with automatic compression
- [ ] **Conversation search** — Full-text search across all conversation history
- [ ] **Model switching mid-conversation** — Switch providers without losing context
- [ ] **Export conversations** — Markdown, JSON, plain text export
- [ ] **Custom system prompts** — Per-conversation system prompt configuration
- [ ] **Streaming stats dashboard** — Real-time compression ratio visualization
- [ ] **Keyboard shortcuts** — Full keyboard navigation in web UI
- [ ] **Dark/light theme toggle** — Currently dark-only, add light theme

### Improvements
- [ ] **Semantic compression** — Use embeddings to identify and remove redundant context
- [ ] **Adaptive compression** — Learn which compression strategies work best per user
- [ ] **CCR prefetch** — Predict which compressed originals the model will need
- [ ] **Connection pooling** — Reuse HTTP connections across requests
- [ ] **Graceful degradation** — Better error messages when providers are unavailable

### Testing
- [ ] **Frontend tests** — Vitest + React Testing Library
- [ ] **E2E tests** — Playwright for web UI
- [ ] **Load tests** — Locust or k6 for rate limiting validation
- [ ] **Coverage reporting** — pytest-cov + codecov integration

## Medium-term (v0.3.0)

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
- [ ] **Conversation branching** — Fork conversations at any point
- [ ] **Prompt templates** — Save and reuse prompt templates
- [ ] **Shared conversations** — Export and import conversation files
- [ ] **Multi-model comparison** — Send same prompt to multiple models, compare outputs
- [ ] **Token budget alerts** — Warn when approaching API limits
- [ ] **Offline mode** — Queue messages when no provider is available

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

## Long-term (v1.0.0)

### Features
- [ ] **Plugin system** — Third-party extensions for compression, tools, UI
- [ ] **Fine-tuning pipeline** — Fine-tune GLM-5.2 on your conversation history
- [ ] **Model quantization tools** — Built-in GGUF quantization for local deployment
- [ ] **Distributed inference** — Split model across multiple GPUs/machines
- [ ] **Voice input/output** — Whisper integration for speech-to-text
- [ ] **Image generation** — Integration with Stable Diffusion / Flux
- [ ] **Code IDE plugin** — VS Code extension using Sensei backend
- [ ] **Mobile responsive UI** — Tablet and phone-optimized web interface
- [ ] **Collaborative sessions** — Multiple users in one conversation (local network)

### Monetization Ideas

These are ideas to sustain development while keeping the core product free and open source:

1. **Hosted Sensei Cloud** (freemium)
   - Free tier: 100 messages/month with compression
   - Pro tier ($9/mo): 10,000 messages, priority compression, RAG
   - Team tier ($49/mo): 50,000 messages, shared conversations, audit logs
   - All tiers use the same open-source code — paying for managed hosting

2. **Enterprise License**
   - Self-hosted with support, SLA, custom integrations
   - On-premise deployment assistance
   - Custom compression strategies for specific industries

3. **Marketplace**
   - Sell premium prompt templates
   - Custom compression plugins
   - Industry-specific agent tools
   - Revenue share with plugin authors

4. **API Service**
   - "Compression-as-a-Service" API — send prompts, get compressed versions back
   - Usage-based pricing for non-Sensei users who want token savings
   - Free tier: 1,000 compressions/month

5. **Desktop App Pro**
   - Free Qt GUI with basic features
   - One-time $19 "Pro" unlock: themes, export, search, templates
   - All features remain in open-source code, Pro is a convenience license

6. **Sponsorships & Grants**
   - GitHub Sponsors
   - Open-source AI grants
   - Corporate sponsorship for specific features

### Principles
- **Core will always be free and open source** (MIT license)
- **No paywalled features in the codebase** — Pro features are convenience layers
- **No telemetry or tracking** — Even in paid tiers
- **Self-hosting always supported** — Cloud is optional, never required
- **Community first** — PRs from community always welcome

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
- Multi-provider support: Ollama, OpenRouter, Z.ai, HuggingFace
- Web UI, Qt GUI, CLI, REST API
- Per-user sessions, auth, rate limiting, data encryption
- Docker Compose deployment
- Comprehensive test suite
