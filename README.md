<div align="center">

<img src="frontend/public/sensei.svg" width="88" height="88" alt="" />

# Sensei

**The self-hosted AI workspace that compresses your prompts before they leave your machine.**

[![CI](https://github.com/SenseiIssei/Sensei/actions/workflows/ci.yml/badge.svg)](https://github.com/SenseiIssei/Sensei/actions/workflows/ci.yml)
[![Security](https://github.com/SenseiIssei/Sensei/actions/workflows/security.yml/badge.svg)](https://github.com/SenseiIssei/Sensei/actions/workflows/security.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB)](https://python.org)

[Quick start](#quick-start) · [What it does](#what-it-does) · [Configuration](docs/configuration.md) · [Roadmap](ROADMAP.md) · [Contributing](CONTRIBUTING.md)

</div>

---

## Quick start

```bash
pip install -e ./backend && sensei up
```

That opens the web UI and asks you one question: local model or hosted provider.
No config file to edit.

**Or with Docker:**

```bash
git clone https://github.com/SenseiIssei/Sensei.git && cd Sensei
docker compose up -d
```

**Then point your coding agent at it:**

```bash
sensei wrap claude
```

That's the whole setup. Claude Code now runs through Sensei, using your own
Anthropic key, with every prompt compressed on the way out.

Also works with `codex`, `aider`, `cursor-agent`, `cline`, `continue`,
`opencode`, `goose` and `crush`.

---

## What it does

Sensei sits between your AI tools and whatever model you use, and makes the
prompts smaller before they're sent. You keep your own API key; Sensei never
sees your provider account.

### Measured token reduction

Real `tiktoken` counts, not estimates. Reproduce them yourself with
`python backend/benchmarks/compression_benchmark.py`:

| Content | Reduction |
|---|---|
| JSON tool output | **79%** |
| Build & test logs | **88%** |
| JSON search results | **69%** |
| Stack traces | **61%** |
| Prose | 44% |
| Source code | 40% |
| **Aggregate** | **79%** |

The JSON and log wins are **lossless** — tabular compaction and log triage, not
summarisation. Nightly CI fails if this number regresses.

### Where it fits

```
your agent  ──▶  Sensei  ──▶  your model provider
                   │
                   ├─ compresses tool results, logs, code, prose
                   ├─ keeps the system prompt byte-exact (cache-safe)
                   ├─ stores originals locally, retrievable on request
                   └─ redacts secrets before anything leaves the machine
```

Sensei speaks both the OpenAI and Anthropic wire formats, so anything with a
configurable base URL works:

```bash
export OPENAI_BASE_URL=http://localhost:7000/v1     # OpenAI SDK, Codex, Cursor…
export ANTHROPIC_BASE_URL=http://localhost:7000     # Claude Code, Anthropic SDK
```

### The rest of it

Chat UI · CLI · Qt desktop app · VS Code extension · RAG over your own documents ·
a tool-using agent · 14 model providers · per-user sessions · encryption at rest ·
OIDC SSO · RBAC · DLP redaction.

---

## Commands

```
sensei up          start the server and open the web UI
sensei wrap <tool> run a coding agent through the compression gateway
sensei doctor      diagnose a setup that isn't working
sensei models      what this machine can run, and what it already has
sensei stats       tokens and dollars saved
sensei chat        console chat
```

`sensei models` reads your actual RAM and VRAM and tells you which models fit —
the thing that usually blocks people on local inference isn't installing Ollama,
it's knowing what their machine can hold.

---

## Privacy

- **Binds to `127.0.0.1` by default.** Exposing Sensei to your network is a
  deliberate act, not the default state.
- **No telemetry.** Nothing is phoned home, in any build, ever.
- **No remote assets.** The web UI loads no fonts, scripts or trackers from
  third parties, so it works fully offline.
- **API keys are encrypted at rest** in a local vault, not written to `.env` in
  plaintext.
- **Secrets are redacted** from prompts before they reach a provider, if you
  turn `SENSEI_REDACTION_ENABLED` on.

If you put Sensei on a network, read [SECURITY.md](SECURITY.md) first.

---

## Install

| Platform | |
|---|---|
| Any | `pip install -e ./backend` |
| Docker | `docker compose up -d` |
| Windows / macOS / Linux | signed-free installers on the [releases page](https://github.com/SenseiIssei/Sensei/releases) |
| VS Code | the `.vsix` on the releases page |

Release builds are unsigned — verify them with the published `SHA256SUMS` and
Sigstore signatures rather than trusting the OS warning dialog. Each release
explains how.

Optional: a Rust accelerator (`sensei_core`) makes the hottest compression path
about twice as fast. It's byte-for-byte identical to the Python path — CI proves
that on every commit — and everything works without it.

---

## Contributing

Issues and PRs welcome. [CONTRIBUTING.md](CONTRIBUTING.md) has the setup and the
house rules; the short version is that CI runs on Linux, macOS and Windows
across Python 3.11–3.13, and changes to the compression pipeline need a
before/after benchmark.

Areas that would help most right now: compression heuristics for more languages,
an MCP server, mobile UI, and provider integrations.

---

## Credits

Sensei is built on ideas from two open-source projects:

- **[Headroom](https://github.com/headroomlabs-ai/headroom)** (Apache-2.0) — the
  context-compression strategies this pipeline is modelled on.
- **[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)** (AGPL-3.0) —
  the self-hosted workspace shape. Sensei is a clean-room implementation; no
  Odysseus code is used, which is why Sensei can stay MIT.

MIT licensed. Free forever, and the core will never be paywalled — see
[ROADMAP.md](ROADMAP.md#principles).

<div align="center">
<sub>Built by <a href="https://github.com/SenseiIssei">@SenseiIssei</a></sub>
</div>
