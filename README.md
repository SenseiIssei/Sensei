<div align="center">

<br>

<!-- Premium header with glassmorphism-inspired design -->
<img src="frontend/public/sensei.svg" width="120" height="120" alt="Sensei" />

<br>

<h1 style="font-size: 3em; font-weight: 800; letter-spacing: -0.03em;">Sensei</h1>

<h3 style="font-weight: 300; opacity: 0.7;">The self-hosted AI workspace that thinks in compressed dreams.</h3>

<br>

<!-- Badges -->
<a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge&logo=opensourceinitiative&logoColor=white" alt="MIT License"></a>
<a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"></a>
<a href="https://react.dev"><img src="https://img.shields.io/badge/React-18-61dafb?style=for-the-badge&logo=react&logoColor=black" alt="React 18"></a>
<a href="docker-compose.yml"><img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker"></a>
<a href="#contributing"><img src="https://img.shields.io/badge/PRs-Welcome-f59e0b?style=for-the-badge&logo=github&logoColor=white" alt="PRs Welcome"></a>

<br><br>

<!-- Glassmorphism-style feature pills -->
<table>
<tr>
<td align="center" style="border: none; background: rgba(255,255,255,0.03); backdrop-filter: blur(10px);">

**Free Forever** &bull; **Open Source** &bull; **Self-Hosted** &bull; **Privacy-First** &bull; **Zero Telemetry**

</td>
</tr>
</table>

<br>

<!-- Navigation with surreal twist -->
<sub>descend into the workspace</sub>

[Quick Start](#quick-start) &nbsp;&middot;&nbsp; [Features](#features) &nbsp;&middot;&nbsp; [Architecture](#architecture) &nbsp;&middot;&nbsp; [Performance](#performance) &nbsp;&middot;&nbsp; [Roadmap](ROADMAP.md) &nbsp;&middot;&nbsp; [Support](#--support-the-project)

<br>

</div>

<!-- Surreal divider -->
<div align="center">
<sub style="opacity: 0.3;">&middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot;</sub>
</div>

<br>

## What is Sensei?

> *Imagine an AI workspace that compresses your thoughts before they reach the model — like folding a letter into a paper crane, sending it across the void, and unfolding it perfectly on the other side. That's Sensei.*

Sensei is a **free, open-source, self-hosted AI workspace** that combines:

- **[Headroom](https://github.com/headroomlabs-ai/headroom)**-style token compression (60-95% reduction)
- **[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)**-style self-hosted workspace design
- **[GLM-5.2](https://github.com/zai-org/GLM-5.2)** — 744B MoE model with 1M token context (MIT license)

All your data stays on your machine. No tracking, no telemetry, no cloud dependency. Your thoughts never leave your orbit.

## Features

<!-- Glassmorphism-inspired feature sections -->
<table>
<tr>
<td width="50%" valign="top" style="border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.02); padding: 20px; border-radius: 12px;">

### Core

- **Token Compression Pipeline** — 60-95% prompt compression before the model sees it
- **Multi-Provider Support** — Ollama (local, free), OpenRouter, Z.ai, HuggingFace
- **Reversible Compression (CCR)** — Originals cached locally, retrievable by the model
- **Cross-session Memory** — Conversations persist across restarts like dreams you can revisit
- **KV Cache Alignment** — Stabilizes prompt prefixes for faster inference

</td>
<td width="50%" valign="top" style="border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.02); padding: 20px; border-radius: 12px;">

### Interfaces

- **Web UI** — React + TypeScript + TailwindCSS dark glass interface
- **Qt Desktop App** — PySide6 native desktop application
- **CLI** — Interactive console chat with slash commands
- **REST API** — Full FastAPI with WebSocket streaming, docs at `/docs`

</td>
</tr>
<tr>
<td width="50%" valign="top" style="border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.02); padding: 20px; border-radius: 12px;">

### Security & Privacy

- **Per-user sessions** — Each user gets isolated conversation history
- **Local data encryption** — Data at rest encrypted with machine-specific keys
- **Token-based auth** — Optional bearer token authentication
- **Rate limiting** — Configurable sliding-window rate limiter
- **Zero telemetry** — Nothing leaves your machine except compressed prompts

</td>
<td width="50%" valign="top" style="border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.02); padding: 20px; border-radius: 12px;">

### Deployment

- **Docker Compose** — One command for full stack + optional Ollama
- **Cross-platform** — Linux, Windows, macOS
- **VPS-ready** — Production Dockerfile, non-root user, health checks
- **Multi-stage builds** — Optimized image sizes
- **GPU support** — Optional NVIDIA GPU profile for Ollama

</td>
</tr>
</table>

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

> *If Sensei folds your tokens into paper cranes and saves you money, consider leaving one at the shrine.*

<div align="center">

<table>
<tr>
<td align="center" style="border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.02); padding: 30px; border-radius: 16px;">

<a href="https://ko-fi.com/senseiissei"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Buy me a coffee" width="200"></a>

<br><br>

<sub>Every donation helps fund development and server costs. Thank you.</sub>

</td>
</tr>
</table>

</div>

<br>

<!-- Surreal closing -->
<div align="center">

<sub style="opacity: 0.3;">&middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot;</sub>

<br>

**[SenseiIssei/Sensei](https://github.com/SenseiIssei/Sensei)**

MIT License &bull; Built for the open-source AI community

<br>

<sub style="opacity: 0.4;">compress &middot; dream &middot; retrieve &middot; repeat</sub>

</div>
