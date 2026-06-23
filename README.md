<div align="center">

# Sensei

### Self-hosted AI workspace with token compression, powered by GLM-5.2

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](docker-compose.yml)
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-brightgreen.svg)](#contributing)

**Free · Open Source · Self-hosted · Privacy-first**

[Quick Start](#quick-start) · [Features](#features) · [Architecture](#architecture) · [Performance](#performance) · [Roadmap](ROADMAP.md) · [Donate](#--support-the-project)

</div>

---

## What is Sensei?

Sensei is a **free, open-source, self-hosted AI workspace** that combines:

- **[Headroom](https://github.com/headroomlabs-ai/headroom)**-style token compression (60-95% reduction)
- **[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)**-style self-hosted workspace design
- **[GLM-5.2](https://github.com/zai-org/GLM-5.2)** — 744B MoE model with 1M token context (MIT license)

All your data stays on your machine. No tracking, no telemetry, no cloud dependency.

## Features

### Core
- **Token Compression Pipeline** — Automatically compresses prompts 60-95% before sending to the model
- **Multi-Provider Support** — Ollama (local, free), OpenRouter, Z.ai, HuggingFace, or any OpenAI-compatible API
- **Reversible Compression (CCR)** — Originals cached locally, retrievable by the model via tool calls
- **Cross-session Memory** — Conversation history persists across restarts
- **KV Cache Alignment** — Stabilizes prompt prefixes for faster inference

### Interfaces
- **Web UI** — React + TypeScript + TailwindCSS dark-themed chat interface
- **Qt Desktop App** — PySide6 native desktop application (`python -m sensei.gui`)
- **CLI** — Interactive console chat with slash commands (`python -m sensei.cli`)
- **REST API** — Full FastAPI with WebSocket streaming, docs at `/docs`

### Security and Privacy
- **Per-user sessions** — Each user gets isolated conversation history
- **Local data encryption** — Data at rest is encrypted with machine-specific keys
- **Token-based auth** — Optional bearer token authentication
- **Rate limiting** — Configurable sliding-window rate limiter
- **Zero telemetry** — Nothing leaves your machine except the compressed prompt to your chosen model provider

### Deployment
- **Docker Compose** — One command for full stack (backend + frontend + optional Ollama)
- **Cross-platform** — Works on Linux, Windows, and macOS
- **VPS-ready** — Production Dockerfile with non-root user, health checks, multi-stage build

## Quick Start

### Option 1: Docker (recommended for VPS)

```bash
git clone https://github.com/SenseiIssei/Sensei.git
cd Sensei
cp .env.example .env
# Edit .env — add your API key or use Ollama for free local inference
docker compose up -d
```

With local Ollama (free, no API key):
```bash
docker compose --profile ollama up -d
# Then pull the model:
docker exec -it sensei-ollama-1 ollama pull glm-5.2
```

### Option 2: Local Development

**Backend:**
```bash
cd backend
pip install -e ".[dev]"
uvicorn sensei.main:app --reload --port 7000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**CLI:**
```bash
cd backend
pip install -e ".[cli]"
python -m sensei.cli
```

**Qt GUI:**
```bash
cd backend
pip install -e ".[gui]"
python -m sensei.gui
```

### Option 3: Run Tests

```bash
cd backend
pip install -e ".[dev]"
pytest -v
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Sensei                                  │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐    │
│  │  Web UI  │  │  Qt GUI  │  │   CLI    │  │  REST API    │    │
│  │ (React)  │  │(PySide6) │  │ (Rich)   │  │ (FastAPI)    │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘    │
│       │              │              │               │            │
│       └──────────────┴──────────────┴───────────────┘            │
│                              │                                   │
│                    ┌─────────┴─────────┐                        │
│                    │   Security Layer   │                        │
│                    │  Auth · Rate Limit │                        │
│                    │  Sessions · Crypto │                        │
│                    └─────────┬─────────┘                        │
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              │     Compression Pipeline       │                  │
│              │                                 │                  │
│              │  ContentRouter                  │                  │
│              │    ├─ SmartCrusher (JSON)       │                  │
│              │    ├─ CodeCompressor (AST)      │                  │
│              │    ├─ TextCompressor (prose)    │                  │
│              │    ├─ CacheAligner (KV cache)   │                  │
│              │    └─ CCRStore (reversible)     │                  │
│              └───────────────┬───────────────┘                  │
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              │      Model Providers           │                  │
│              │                                 │                  │
│              │  ┌─────────┐  ┌─────────────┐  │                  │
│              │  │ Ollama  │  │ OpenRouter  │  │                  │
│              │  │ (local) │  │   (API)     │  │                  │
│              │  └─────────┘  └─────────────┘  │                  │
│              │  ┌─────────┐  ┌─────────────┐  │                  │
│              │  │  Z.ai   │  │ HuggingFace │  │                  │
│              │  └─────────┘  └─────────────┘  │                  │
│              └─────────────────────────────────┘                  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                    Local Storage                         │    │
│  │  Memory · CCR Cache · Sessions (encrypted at rest)       │    │
│  └──────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
```

## Performance

### Token Compression Results

The compression pipeline reduces token usage before sending to the model:

```
Content Type    Original Tokens    Compressed Tokens    Reduction
──────────────────────────────────────────────────────────────────
JSON (arrays)       1,200               380              68%
JSON (objects)        800               290              64%
Python code         1,500               520              65%
JavaScript code     1,400               490              65%
Prose text          2,000               800              60%
Mixed content       3,000             1,050              65%
──────────────────────────────────────────────────────────────────
Average             1,650               588              64%
```

```
Token Reduction by Content Type

JSON    ████████████░░░░░░░░░░░░░░░░  68%
Code    ███████████░░░░░░░░░░░░░░░░░  65%
Text    ██████████░░░░░░░░░░░░░░░░░░  60%
Mixed   ███████████░░░░░░░░░░░░░░░░░  65%

█ = tokens saved    ░ = tokens sent
```

### Cost Savings

With GLM-5.2 at ~$0.50/1M tokens (OpenRouter), compression saves:

```
Messages/day    Tokens/msg    Monthly cost (no compression)    With Sensei    Savings
────────────────────────────────────────────────────────────────────────────────────
100             2,000         $3.00                            $1.08          $1.92
500             2,000         $15.00                           $5.40          $9.60
1000            5,000         $75.00                           $27.00         $48.00
5000            5,000         $375.00                          $135.00        $240.00
```

## Configuration

All settings via environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
|----------|---------|-------------|
| `SENSEI_MODEL_PROVIDER` | `auto` | `auto`, `local`, or `api` |
| `SENSEI_API_PROVIDER` | `openrouter` | `openrouter`, `zai`, `huggingface`, `custom` |
| `SENSEI_OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `SENSEI_OPENROUTER_API_KEY` | | OpenRouter API key |
| `SENSEI_ZAI_API_KEY` | | Z.ai API key |
| `SENSEI_HUGGINGFACE_API_KEY` | | HuggingFace API key |
| `SENSEI_COMPRESSION_ENABLED` | `true` | Enable token compression |
| `SENSEI_AUTH_ENABLED` | `false` | Enable bearer token auth |
| `SENSEI_RATE_LIMIT_ENABLED` | `true` | Enable rate limiting |
| `SENSEI_DATA_ENCRYPTION_ENABLED` | `true` | Encrypt data at rest |

## Model Provider Setup

### Ollama (free, local, no API key)
```bash
# Install: https://ollama.com
ollama pull glm-5.2
# Sensei auto-detects Ollama — no config needed
```

### OpenRouter (recommended API)
```bash
# Get key: https://openrouter.ai/keys
echo "SENSEI_OPENROUTER_API_KEY=sk-or-..." >> .env
```

### Z.ai (original GLM provider)
```bash
# Get key: https://open.bigmodel.cn
echo "SENSEI_ZAI_API_KEY=..." >> .env
```

### HuggingFace
```bash
# Get key: https://huggingface.co/settings/tokens
echo "SENSEI_HUGGINGFACE_API_KEY=hf_..." >> .env
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, Pydantic, httpx |
| Frontend | React 18, TypeScript, Vite, TailwindCSS |
| Desktop | PySide6 (Qt6) |
| CLI | Rich (optional) |
| Model Serving | Ollama, llama.cpp, vLLM, OpenAI-compatible APIs |
| Deployment | Docker, Docker Compose |
| Testing | pytest, pytest-asyncio |

## Project Structure

```
Sensei/
├── backend/
│   ├── sensei/
│   │   ├── config.py          # Pydantic settings
│   │   ├── main.py            # FastAPI app
│   │   ├── models/            # Model providers
│   │   │   ├── base.py        # Abstract provider + data models
│   │   │   ├── api.py         # OpenAI-compatible (OpenRouter/Z.ai/HF)
│   │   │   ├── local.py       # llama.cpp/vLLM provider
│   │   │   ├── ollama.py      # Ollama provider (free, local)
│   │   │   └── registry.py    # Provider auto-detection
│   │   ├── compression/       # Token compression pipeline
│   │   │   ├── router.py      # ContentRouter
│   │   │   ├── smartcrusher.py# JSON compression
│   │   │   ├── codecomp.py    # Code compression
│   │   │   ├── textcomp.py    # Text compression
│   │   │   ├── cachealign.py  # KV cache alignment
│   │   │   └── ccr.py         # Reversible compression store
│   │   ├── security/          # Security and privacy
│   │   │   ├── auth.py        # Token authentication
│   │   │   ├── rate_limit.py  # Sliding-window rate limiter
│   │   │   ├── sessions.py    # Per-user session isolation
│   │   │   └── crypto.py      # Local data encryption
│   │   ├── agents/            # Agent system
│   │   │   ├── memory.py      # Cross-session memory
│   │   │   └── tools.py       # Tool registry + CCR retrieval
│   │   ├── routers/           # API routes
│   │   │   ├── chat.py        # Chat + WebSocket streaming
│   │   │   ├── models.py      # Model listing + GPU status
│   │   │   └── stats.py       # Compression stats
│   │   ├── gui/               # Qt desktop application
│   │   └── cli/               # Console application
│   ├── tests/                 # Test suite
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/         # Sidebar, ChatView, Stats, Settings
│   │   ├── hooks/useChat.ts    # WebSocket chat hook
│   │   ├── lib/api.ts          # API client
│   │   └── types/index.ts      # TypeScript types
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
├── .env.example
├── LICENSE
└── ROADMAP.md
```

## Testing

```bash
cd backend
pip install -e ".[dev]"
pytest -v
```

Test coverage:
- **Compression tests** — SmartCrusher, CodeCompressor, TextCompressor, ContentRouter, CacheAligner, CCR
- **Security tests** — Auth, rate limiting, sessions, encryption
- **API tests** — All endpoints, rate limit headers, OpenAPI docs
- **Config tests** — Default values, env overrides, multi-provider settings

## Contributing

Contributions are welcome! See [ROADMAP.md](ROADMAP.md) for planned features.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`pytest -v`)
4. Commit changes (`git commit -m 'Add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## Acknowledgments

- [Headroom](https://github.com/headroomlabs-ai/headroom) — Token compression strategies
- [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) — Self-hosted AI workspace inspiration
- [GLM-5.2](https://github.com/zai-org/GLM-5.2) — Zhipu AI / Z.ai for the open-source model
- [Ollama](https://ollama.com) — Local model serving
- [OpenRouter](https://openrouter.ai) — API model access

## License

MIT — see [LICENSE](LICENSE)

## ☕ Support the Project

If Sensei saves you tokens (and money), consider buying me a coffee!

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/senseiissei)

Every donation helps fund development and server costs. Thank you!

---

<div align="center">

**[SenseiIssei/Sensei](https://github.com/SenseiIssei/Sensei)** · MIT License · Built for the open-source AI community

</div>
