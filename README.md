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
<a href="https://discord.com/users/senseiissei"><img src="https://img.shields.io/badge/Discord-senseiissei-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>

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

## Verified performance

These numbers are **measured, not claimed** — reproduce them with
[`backend/benchmarks/compression_benchmark.py`](backend/benchmarks/compression_benchmark.py)
(real `tiktoken` counts on a representative corpus of tool outputs, logs, code, and prose):

| Content | Real token reduction |
|---|---|
| JSON tool output (20-record array) | **79%** |
| JSON search results | **69%** |
| Build / test logs | **88%** |
| Stack traces | **61%** |
| Source code | 40% |
| Prose | 44% |
| **Aggregate** | **79%** |

The JSON and log wins are **lossless** (CSV-schema tabular compaction + log
triage). An optional [Rust accelerator](rust/sensei_core) (`sensei_core`) runs the
hottest path ~2× faster, byte-for-byte identical to the Python path.

## Use it as a drop-in gateway (save tokens on the tools you already use)

Sensei speaks both the **OpenAI** and **Anthropic** APIs, so point any tool's
base URL at it and prompts are compressed transparently — the tool keeps its own key:

```bash
# OpenAI tools (Codex, Cursor, Continue, Aider, the OpenAI SDK)
export OPENAI_BASE_URL=http://localhost:7000/v1
# Claude Code / Anthropic SDK
export ANTHROPIC_BASE_URL=http://localhost:7000
```

Or install the **[VS Code extension](extensions/vscode)** — one click routes Claude
Code / Codex through Sensei, shows live `% saved · $ saved` in the status bar, and
adds a Sensei chat panel. Every response carries `X-Sensei-Tokens-Saved` headers,
and the web UI's Stats panel shows total tokens and dollars saved.

See [packaging/README.md](packaging/README.md) for console / `.exe` / Marketplace install.

## Features

<!-- Glassmorphism-inspired feature sections -->
<table>
<tr>
<td width="50%" valign="top" style="border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.02); padding: 20px; border-radius: 12px;">

### Core

- **Token Compression Pipeline** — 60-95% prompt compression before the model sees it
- **14+ Model Providers** — Ollama, OpenAI, Claude, Gemini, OpenRouter, Groq, DeepSeek, Mistral, and more
- **One-Command Installer** — `python install.py` sets up everything interactively
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
- **Production-ready** — Production Dockerfile, non-root user, health checks
- **Multi-stage builds** — Optimized image sizes
- **GPU support** — Optional NVIDIA GPU profile for Ollama

</td>
</tr>
</table>

## Quick Start

### Option 0: One-Command Installer (easiest)

**Linux / macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/SenseiIssei/Sensei/main/install.sh | bash
```

**Windows / Any OS:**
```bash
git clone https://github.com/SenseiIssei/Sensei.git
cd Sensei
python install.py
```

The installer will:
1. Check prerequisites automatically
2. Install all dependencies
3. Show you all 14+ model providers to choose from
4. Let you enter API keys interactively (or skip for later)
5. Generate your `.env` file
6. Optionally pull Ollama models
7. Run tests to verify everything works
8. Start the server

You just pick your models and paste API keys — the installer handles the rest.

### Option 1: Docker (recommended)

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

> 📋 **[View the Interactive Roadmap &rarr;](roadmap.html)**** — a beautiful, animated, glassy page showing all planned features, enterprise plans, and the Sensei-1 model vision.**

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

## Performance ✨

> *Every token saved is a little victory. Sensei turns your words into compressed dreams — faster, cheaper, greener.* 🌿

### Token Compression Results

The compression pipeline reduces token usage **before** the model sees it. Less tokens = less cost = happier you. 💚

<!-- Glassmorphism performance cards -->
<table>
<tr>
<td width="50%" valign="top" style="border: 1px solid rgba(255,255,255,0.06); background: linear-gradient(135deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01)); padding: 24px; border-radius: 16px; backdrop-filter: blur(10px);">

<h3 align="center">📊 Token Reduction by Content Type</h3>

<!-- Animated CSS bar chart -->
<div style="font-family: monospace; font-size: 13px; line-height: 2.2;">

<div style="display: flex; align-items: center; gap: 8px;">
<span style="width: 60px; color: #94a3b8;">JSON</span>
<div style="flex: 1; background: rgba(255,255,255,0.05); border-radius: 6px; overflow: hidden; height: 22px;">
<div style="width: 68%; height: 100%; background: linear-gradient(90deg, #22c55e, #4ade80); border-radius: 6px; animation: growBar 1.5s ease-out;">
</div>
</div>
<span style="color: #4ade80; font-weight: bold; width: 40px; text-align: right;">68%</span>
</div>

<div style="display: flex; align-items: center; gap: 8px;">
<span style="width: 60px; color: #94a3b8;">Python</span>
<div style="flex: 1; background: rgba(255,255,255,0.05); border-radius: 6px; overflow: hidden; height: 22px;">
<div style="width: 65%; height: 100%; background: linear-gradient(90deg, #3b82f6, #60a5fa); border-radius: 6px; animation: growBar 1.5s ease-out 0.1s;">
</div>
</div>
<span style="color: #60a5fa; font-weight: bold; width: 40px; text-align: right;">65%</span>
</div>

<div style="display: flex; align-items: center; gap: 8px;">
<span style="width: 60px; color: #94a3b8;">JS/TS</span>
<div style="flex: 1; background: rgba(255,255,255,0.05); border-radius: 6px; overflow: hidden; height: 22px;">
<div style="width: 65%; height: 100%; background: linear-gradient(90deg, #f59e0b, #fbbf24); border-radius: 6px; animation: growBar 1.5s ease-out 0.2s;">
</div>
</div>
<span style="color: #fbbf24; font-weight: bold; width: 40px; text-align: right;">65%</span>
</div>

<div style="display: flex; align-items: center; gap: 8px;">
<span style="width: 60px; color: #94a3b8;">Prose</span>
<div style="flex: 1; background: rgba(255,255,255,0.05); border-radius: 6px; overflow: hidden; height: 22px;">
<div style="width: 60%; height: 100%; background: linear-gradient(90deg, #a855f7, #c084fc); border-radius: 6px; animation: growBar 1.5s ease-out 0.3s;">
</div>
</div>
<span style="color: #c084fc; font-weight: bold; width: 40px; text-align: right;">60%</span>
</div>

<div style="display: flex; align-items: center; gap: 8px;">
<span style="width: 60px; color: #94a3b8;">Mixed</span>
<div style="flex: 1; background: rgba(255,255,255,0.05); border-radius: 6px; overflow: hidden; height: 22px;">
<div style="width: 65%; height: 100%; background: linear-gradient(90deg, #ec4899, #f472b6); border-radius: 6px; animation: growBar 1.5s ease-out 0.4s;">
</div>
</div>
<span style="color: #f472b6; font-weight: bold; width: 40px; text-align: right;">65%</span>
</div>

</div>

<p align="center" style="color: #94a3b8; font-size: 12px; margin-top: 16px;">
<b style="color: #4ade80;">Average: 64% token reduction</b> — you only pay for ~1/3 of the tokens 🎉
</p>

</td>
<td width="50%" valign="top" style="border: 1px solid rgba(255,255,255,0.06); background: linear-gradient(135deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01)); padding: 24px; border-radius: 16px; backdrop-filter: blur(10px);">

<h3 align="center">💰 Monthly Cost Savings</h3>

<div style="font-family: monospace; font-size: 13px; line-height: 2.2;">

<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
<span style="width: 80px; color: #94a3b8;">100 msg/d</span>
<div style="flex: 1; background: rgba(255,255,255,0.05); border-radius: 6px; overflow: hidden; height: 22px; position: relative;">
<div style="width: 100%; height: 100%; background: rgba(239,68,68,0.3); border-radius: 6px; position: absolute;"></div>
<div style="width: 36%; height: 100%; background: linear-gradient(90deg, #22c55e, #4ade80); border-radius: 6px; position: relative; animation: growBar 1.5s ease-out 0.5s;">
</div>
</div>
<span style="color: #4ade80; font-weight: bold; width: 50px; text-align: right;">$1.92</span>
</div>

<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
<span style="width: 80px; color: #94a3b8;">500 msg/d</span>
<div style="flex: 1; background: rgba(255,255,255,0.05); border-radius: 6px; overflow: hidden; height: 22px; position: relative;">
<div style="width: 100%; height: 100%; background: rgba(239,68,68,0.3); border-radius: 6px; position: absolute;"></div>
<div style="width: 36%; height: 100%; background: linear-gradient(90deg, #22c55e, #4ade80); border-radius: 6px; position: relative; animation: growBar 1.5s ease-out 0.6s;">
</div>
</div>
<span style="color: #4ade80; font-weight: bold; width: 50px; text-align: right;">$9.60</span>
</div>

<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
<span style="width: 80px; color: #94a3b8;">1K msg/d</span>
<div style="flex: 1; background: rgba(255,255,255,0.05); border-radius: 6px; overflow: hidden; height: 22px; position: relative;">
<div style="width: 100%; height: 100%; background: rgba(239,68,68,0.3); border-radius: 6px; position: absolute;"></div>
<div style="width: 36%; height: 100%; background: linear-gradient(90deg, #22c55e, #4ade80); border-radius: 6px; position: relative; animation: growBar 1.5s ease-out 0.7s;">
</div>
</div>
<span style="color: #4ade80; font-weight: bold; width: 50px; text-align: right;">$48.00</span>
</div>

<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
<span style="width: 80px; color: #94a3b8;">5K msg/d</span>
<div style="flex: 1; background: rgba(255,255,255,0.05); border-radius: 6px; overflow: hidden; height: 22px; position: relative;">
<div style="width: 100%; height: 100%; background: rgba(239,68,68,0.3); border-radius: 6px; position: absolute;"></div>
<div style="width: 36%; height: 100%; background: linear-gradient(90deg, #22c55e, #4ade80); border-radius: 6px; position: relative; animation: growBar 1.5s ease-out 0.8s;">
</div>
</div>
<span style="color: #4ade80; font-weight: bold; width: 50px; text-align: right;">$240.00</span>
</div>

</div>

<p align="center" style="color: #94a3b8; font-size: 12px; margin-top: 16px;">
<span style="color: #ef4444;">▮</span> Without Sensei &nbsp; vs &nbsp; <span style="color: #4ade80;">▮</span> With Sensei<br>
<b style="color: #4ade80;">Save up to $240/month</b> — that's a new GPU every few months 🚀
</p>

</td>
</tr>
</table>

<!-- Key stats row -->
<table>
<tr>
<td align="center" style="border: 1px solid rgba(34,197,94,0.15); background: linear-gradient(135deg, rgba(34,197,94,0.08), rgba(34,197,94,0.02)); padding: 20px; border-radius: 12px; backdrop-filter: blur(10px);">
<h2 style="color: #4ade80; margin: 0;">64%</h2>
<p style="color: #94a3b8; margin: 4px 0 0 0; font-size: 13px;">Avg Token Reduction</p>
</td>
<td align="center" style="border: 1px solid rgba(59,130,246,0.15); background: linear-gradient(135deg, rgba(59,130,246,0.08), rgba(59,130,246,0.02)); padding: 20px; border-radius: 12px; backdrop-filter: blur(10px);">
<h2 style="color: #60a5fa; margin: 0;">14+</h2>
<p style="color: #94a3b8; margin: 4px 0 0 0; font-size: 13px;">Model Providers</p>
</td>
<td align="center" style="border: 1px solid rgba(168,85,247,0.15); background: linear-gradient(135deg, rgba(168,85,247,0.08), rgba(168,85,247,0.02)); padding: 20px; border-radius: 12px; backdrop-filter: blur(10px);">
<h2 style="color: #c084fc; margin: 0;">$0</h2>
<p style="color: #94a3b8; margin: 4px 0 0 0; font-size: 13px;">Cost with Ollama</p>
</td>
<td align="center" style="border: 1px solid rgba(236,72,153,0.15); background: linear-gradient(135deg, rgba(236,72,153,0.08), rgba(236,72,153,0.02)); padding: 20px; border-radius: 12px; backdrop-filter: blur(10px);">
<h2 style="color: #f472b6; margin: 0;">0</h2>
<p style="color: #94a3b8; margin: 4px 0 0 0; font-size: 13px;">Telemetry Calls</p>
</td>
</tr>
</table>

<style>
@keyframes growBar {
  from { width: 0%; }
}
@keyframes float {
  0%, 100% { transform: translateY(0px); }
  50% { transform: translateY(-6px); }
}
@keyframes glow {
  0%, 100% { box-shadow: 0 0 5px rgba(34,197,94,0.2); }
  50% { box-shadow: 0 0 20px rgba(34,197,94,0.4); }
}
</style>

## Configuration

All settings via environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
|----------|---------|-------------|
| `SENSEI_MODEL_PROVIDER` | `auto` | `auto`, `local`, or `api` |
| `SENSEI_API_PROVIDER` | `openrouter` | `ollama`, `openrouter`, `groq`, `google`, `huggingface`, `zai`, `openai`, `anthropic`, `deepseek`, `mistral`, `together`, `cohere`, `fireworks`, `perplexity`, `custom` |
| `SENSEI_OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `SENSEI_OPENROUTER_API_KEY` | | OpenRouter API key |
| `SENSEI_ZAI_API_KEY` | | Z.ai API key |
| `SENSEI_HUGGINGFACE_API_KEY` | | HuggingFace API key |
| `SENSEI_COMPRESSION_ENABLED` | `true` | Enable token compression |
| `SENSEI_AUTH_ENABLED` | `false` | Enable bearer token auth |
| `SENSEI_RATE_LIMIT_ENABLED` | `true` | Enable rate limiting |
| `SENSEI_DATA_ENCRYPTION_ENABLED` | `true` | Encrypt data at rest |

## Model Providers

Sensei supports **14+ model providers** — pick one or use multiple. Free providers need no payment.

<!-- Glassmorphism-style provider table -->
<table>
<tr>
<th>Provider</th>
<th>Models</th>
<th>Tier</th>
<th>Get API Key</th>
</tr>
<tr><td><b>Ollama</b></td><td>GLM-5.2, Llama 3.3, Qwen, any GGUF</td><td>🟢 Free (local)</td><td><a href="https://ollama.com">ollama.com</a></td></tr>
<tr><td><b>OpenRouter</b></td><td>All models (aggregator)</td><td>🟢 Free tier</td><td><a href="https://openrouter.ai/keys">openrouter.ai/keys</a></td></tr>
<tr><td><b>Groq</b></td><td>Llama 3.3 70B, Mixtral (ultra-fast)</td><td>🟢 Free tier</td><td><a href="https://console.groq.com/keys">console.groq.com</a></td></tr>
<tr><td><b>Google Gemini</b></td><td>Gemini 2.0 Flash, Pro</td><td>🟢 Free tier</td><td><a href="https://aistudio.google.com/apikey">aistudio.google.com</a></td></tr>
<tr><td><b>HuggingFace</b></td><td>GLM-5.2, thousands of models</td><td>🟢 Free</td><td><a href="https://huggingface.co/settings/tokens">huggingface.co</a></td></tr>
<tr><td><b>Z.ai</b></td><td>GLM-5.2 (original)</td><td>🟡 Paid</td><td><a href="https://open.bigmodel.cn">open.bigmodel.cn</a></td></tr>
<tr><td><b>OpenAI</b></td><td>GPT-4o, o1, o3</td><td>🟣 Premium</td><td><a href="https://platform.openai.com/api-keys">platform.openai.com</a></td></tr>
<tr><td><b>Anthropic</b></td><td>Claude 3.5 Sonnet, Opus, Haiku</td><td>🟣 Premium</td><td><a href="https://console.anthropic.com/settings/keys">console.anthropic.com</a></td></tr>
<tr><td><b>DeepSeek</b></td><td>DeepSeek V3, R1 (cheap & powerful)</td><td>🟣 Premium</td><td><a href="https://platform.deepseek.com/api_keys">platform.deepseek.com</a></td></tr>
<tr><td><b>Mistral</b></td><td>Mistral Large, Codestral</td><td>🟣 Premium</td><td><a href="https://console.mistral.ai/api-keys">console.mistral.ai</a></td></tr>
<tr><td><b>Together AI</b></td><td>Llama, Qwen, DeepSeek</td><td>🟣 Premium</td><td><a href="https://api.together.xyz/settings/api-keys">api.together.xyz</a></td></tr>
<tr><td><b>Cohere</b></td><td>Command R+</td><td>🟣 Premium</td><td><a href="https://dashboard.cohere.com/api-keys">dashboard.cohere.com</a></td></tr>
<tr><td><b>Fireworks AI</b></td><td>Llama, Qwen (fast inference)</td><td>🟣 Premium</td><td><a href="https://fireworks.ai/apikeys">fireworks.ai</a></td></tr>
<tr><td><b>Perplexity</b></td><td>Sonar (online search-augmented)</td><td>🟣 Premium</td><td><a href="https://www.perplexity.ai/settings/api">perplexity.ai</a></td></tr>
</table>

> **Just want to get started?** Run `python install.py` and pick Ollama (free, local) or OpenRouter (free tier, all models). You can always add more providers later by editing `.env`.

### Quick manual setup

**Ollama (free, local, no API key):**
```bash
ollama pull glm-5.2  # Sensei auto-detects Ollama
```

**Any API provider:**
```bash
# Example: OpenAI
echo "SENSEI_API_PROVIDER=openai" >> .env
echo "SENSEI_OPENAI_API_KEY=sk-..." >> .env

# Example: Claude
echo "SENSEI_API_PROVIDER=anthropic" >> .env
echo "SENSEI_ANTHROPIC_API_KEY=sk-ant-..." >> .env
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
├── install.py                # One-command installer (interactive)
├── install.sh                # Shell installer for Linux/macOS
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
├── training/                # Sensei-1 model fine-tuning pipeline
│   ├── configs/             # LoRA, QLoRA, DPO configs
│   ├── train.py             # Training script
│   ├── prepare_data.py      # Convert conversations to training data
│   ├── export.py            # Merge LoRA + export
│   ├── quantize.py          # GGUF/AWQ/GPTQ quantization
│   └── evaluate.py          # Benchmark vs GLM-5.2, Claude, GPT-4o
├── roadmap.html             # Interactive animated roadmap page
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

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

> **Note:** The `main` branch is protected — all changes go through Pull Request review. Fork the repo, create a branch, and open a PR!

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`pytest -v`)
4. Commit changes (`git commit -m 'feat: add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request — requires 1 approving review

## Acknowledgments

- [Headroom](https://github.com/headroomlabs-ai/headroom) — Token compression strategies
- [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) — Self-hosted AI workspace inspiration
- [GLM-5.2](https://github.com/zai-org/GLM-5.2) — Zhipu AI / Z.ai for the open-source model
- [Ollama](https://ollama.com) — Local model serving
- [OpenRouter](https://openrouter.ai) — API model access
- [OpenClaw](https://github.com/openclaw/openclaw) — Multi-channel AI assistant inspiration

## License

MIT — see [LICENSE](LICENSE)

## Community

<div align="center">

<a href="https://discord.com/users/senseiissei"><img src="https://img.shields.io/badge/Add_me_on_Discord-senseiissei-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
&emsp;
<a href="https://ko-fi.com/senseiissei"><img src="https://img.shields.io/badge/Support_on_Ko--fi-senseiissei-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white" alt="Ko-fi"></a>

</div>

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

## Made with 💚 and a lot of ☕

<table>
<tr>
<td style="border: 1px solid rgba(34,197,94,0.1); background: linear-gradient(135deg, rgba(34,197,94,0.05), rgba(34,197,94,0.01)); padding: 28px; border-radius: 16px; backdrop-filter: blur(10px);">

<h3 align="center">🌿 Spread Positivity 🌿</h3>

<p align="center" style="color: #94a3b8; max-width: 500px; margin: 0 auto;">
Sensei was built on a simple belief: <b style="color: #4ade80;">AI should be accessible to everyone</b>.<br>
Free, open source, private. No paywalls, no tracking, no gatekeeping.<br><br>
Every conversation you have with Sensei saves tokens, saves money, and saves energy.<br>
That's better for you, better for the planet, and better for the future of AI. 🌍<br><br>
<b style="color: #c084fc;">Be kind to yourself. Be kind to others. Build cool things.</b> ✨<br>
You've got this. 🚀
</p>

</td>
</tr>
</table>

<br>

**[SenseiIssei/Sensei](https://github.com/SenseiIssei/Sensei)**

MIT License &bull; Built for the open-source AI community

<br>

<sub style="opacity: 0.4;">compress &middot; dream &middot; retrieve &middot; repeat</sub>

</div>
