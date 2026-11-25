# Sensei Roadmap

What comes next, why, and how anybody can tell that it is done. Written
2026-11-25 after an audit of 0.3.0 and a survey of comparable tools. The older,
longer list is kept [below](#earlier-list).

**Contents:** [Where Sensei stands](#where-sensei-stands) ·
[The plan](#the-plan) · [Decisions](#decisions-only-the-maintainer-can-make) ·
[Not planned](#not-planned) · [Earlier list](#earlier-list) ·
[Principles](#principles)

## Where Sensei stands

On 430 real sessions Sensei removes 3.9 % of tool-output tokens, 0.68 % of the
bill once prompt caching is priced in. That fits what others measured
independently: a [study of 2,848 paired runs](https://arxiv.org/html/2607.12161v5)
puts the ceiling for compressing on the user's side at about 5 % of the cost, and
finds almost no correlation between tokens removed and money saved (r = 0.15).
Independent tests of the biggest names mostly find nothing saved, or more spent
through extra turns. Nobody independent has tested Sensei.

So the biggest gap is not a better grep compressor. It is proof that a whole task
gets cheaper without getting worse, and the levers that move the rest of the bill.

| Tool | What it does better today | What Sensei does better |
|---|---|---|
| [Headroom](https://github.com/headroomlabs-ai/headroom) (Apache-2.0) | [Bedrock, Vertex and Gemini routes, Prometheus, OpenTelemetry](https://docs.headroomlabs.ai/docs/proxy); adapters for LangChain, Vercel AI SDK and others; embedded in LiteLLM and Portkey; in our own table ahead on JSON APIs (27.5 % against 0), CI logs (90.8 against 57.5) and kubectl (10.8 against 0) | no telemetry (its beacon is [on by default](https://docs.headroomlabs.ai/docs/proxy)); Intel macOS; grep, diff and test output in the same table; hook mode, which keeps Claude Code's [Remote Control](https://github.com/headroomlabs-ai/headroom/issues/1779) |
| [rtk](https://github.com/rtk-ai/rtk) (Apache-2.0, engine and proxy BUSL-1.1) | [works in Codex, Cursor, Gemini and more](https://github.com/rtk-ai/rtk#works-in-your-agent) by rewriting the command before it runs, so failing commands are covered too; about 5 MB; brew and winget | plain MIT; originals retrievable; gateway with three API formats; MCP proxy |
| [Caveman](https://github.com/JuliusBrussee/caveman) (Apache-2.0) | model and effort per request (0.46x cost, vendor's interim figure); a trial command that compares a user's own work with and without it | nothing leaves the machine; no account |
| [Parsec](https://github.com/daseinlabs/parsec) (MIT) | learned relevance pruning, -39 % cost in [a benchmark its maker runs](https://github.com/daseinlabs/code-compression-bench) | no scoring service that sees the code; originals retrievable |
| [LiteLLM](https://github.com/BerriAI/litellm), [Portkey](https://github.com/Portkey-AI/gateway), [Bifrost](https://github.com/maximhq/bifrost) | 100+ providers, team keys and budgets, observability, clusters | compression built in and cache-aware; LiteLLM's Headroom guardrail reportedly [compresses nothing for Claude Code](https://github.com/BerriAI/litellm/issues/50270); one local program, reversible setup |
| [mcp-compressor](https://github.com/atlassian-labs/mcp-compressor), [context-mode](https://github.com/mksglu/context-mode) | OAuth to remote MCP servers, generated clients; search over stored output | a gateway and hooks next to the MCP part; MIT (context-mode is Elastic 2.0) |
| [Claude's own context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing) and tool search | built in, no setup | works with every provider; what is cleared can be fetched again |

Byte-exact file reads are the design choice with the best evidence behind it:
[whole files beat the best of three compressors by 6.3 points](https://arxiv.org/abs/2610.21073),
because patches against altered text do not apply. Vendor numbers above are the
vendors'; nothing here was installed or rerun by us.

## The plan

Ordered by value against effort. Sizes: S is up to a day, M a few days, L weeks.
**[decision]** needs the maintainer's word, **[money]** costs something.

### 1. Prove it on whole tasks (M) **[decision] [money]**

Paired runs of 30 to 40 real coding tasks: without Sensei, with a pass-through
gateway, with the hook, with the gateway. Billed cost, turns, retrievals, re-runs
of the same command, solved or not. Two models, pre-registered, published whatever
comes out. Then a compression holdout in the ledger, like the one output shaping
has, so every user gets their own answer.

- **Done:** `docs/evals/` holds the protocol (committed before the runs), the raw
  per-task table and the result with intervals; `python -m benchmarks.task_trial`
  repeats it; the dashboard shows "with" against "without" from the holdout.
- **Verify:** a stranger reruns ten tasks with one command. The README leads with
  this number and drops the synthetic one. Submit to
  [TokenTrial](https://bishtashish708.github.io/tokentrial/).
- **Cost:** API usage for roughly 250 agent runs. Estimate it from five pilot runs
  before deciding.

### 2. Install as a folder, not as a self-extracting file (S to M)

Every `sensei mcp` unpacks 60 MB into the temp directory and leaves it there when
the editor kills it. One machine had 71 such directories (about 4 GB), a dozen of them
in use. Measured on Windows with the same code: first MCP answer after
2.0 s as one file, 0.7 s as a folder; six killed sessions left 360 MB against
none.

- **Done:** Windows installer, `.zip`, `.tar.gz`, `.deb`, `.rpm` and `.dmg` carry
  the folder build; `install.sh` and `sensei update` unpack it; `sensei doctor`
  finds and offers to remove old `_MEI` directories.
- **Verify:** CI installs the built artifacts on three systems, starts and kills
  `sensei mcp` ten times, and fails if anything is left or the first answer takes
  over 1.5 s.

### 3. Failing commands, and the agents that cannot replace output (L)

A failing test is where compression helps most, and in the default Claude Code
setup it does not happen: a nonzero exit fires `PostToolUseFailure`, whose output
a hook [cannot replace](https://github.com/anthropics/claude-code/issues/97278).
Codex, Cursor and Gemini only get MCP. Both are solved by running the command
through `sensei run -- <command>`, put in front by a hook before the tool runs.

- **First (S):** reproduce on the current Claude Code with a scripted model, also
  the [30,000 character limit](https://github.com/anthropics/claude-code/issues/112065).
- **Done:** opt-in per tool, exit code, signals, colours and streaming unchanged,
  full output stored, fails open when Sensei is not there.
- **Verify:** end to end against the real tools as `docs/integrations` does today;
  a test that a failing pytest keeps every assertion diff; no more re-runs of the
  same command than without it (from item 1).

### 4. CI that tells somebody (S) **[decision]**

All 121 scheduled Security runs since 2026-07-28 were red and nobody noticed, and
`main` requires no check at all. A scheduled failure should open one issue and
close it when it is green; `CI OK` should be a required check; Dependabot patch
updates can merge themselves once it is.

- **Done:** one open issue per failing schedule, required check set, auto-merge for
  patch updates of development dependencies only.
- **Verify:** a deliberately failing branch run opens exactly one issue.

### 5. Clear old tool results when it is free (M)

Old observations are most of a long session. Hiding them
[halved the cost at equal solve rate](https://arxiv.org/abs/2508.21433v3) in a
harness without caching. With caching, rewriting history costs a cache write, so
it only pays at moments when the cache is cold anyway: after a TTL miss, at a
compaction, or above a threshold that earns the write back. Sensei already knows
those moments (the live zone attributes every miss) and can leave an id behind.

- **Done:** opt-in, `clear_at_least` threshold computed from the model's prices,
  newest results and unresolved errors kept, everything retrievable.
- **Verify:** gateway replay shows the bill falling on the same sessions, with the
  cache hit rate next to it; item 1 shows solves unchanged.

### 6. A token by default, and no key for strangers on the same machine (M)

Web pages are refused now. Another account on the same computer is not: loopback
is shared, so anyone logged in there can use the key configured in Sensei. Generate
a token on first start, have `connect` write it into each tool as `X-Sensei-Token`,
and require it wherever Sensei would use its own key. Put the vault key into the
system's keychain (DPAPI, Keychain, Secret Service) where there is one.

- **Done:** default on for new installs, old ones keep working with a notice.
- **Verify:** tests per endpoint with and without the token; a second account on a
  Linux CI runner gets 401.

### 7. The same next action (M)

Facts kept is necessary, not sufficient. Replay recorded turns with raw and with
compressed output and compare the next tool call, as
[CoACT](https://arxiv.org/html/2607.02911) does (MIT).

- **Done:** nightly on a fixed, synthetic set with a local model; optional on your
  own sessions, locally.
- **Verify:** a deliberately broken compressor is caught.

### 8. Where our own table says we are behind (M)

JSON API responses, CI and docker logs, kubectl tables. Found in this audit: the
output of PowerShell tables, `dir`, `du` and `pip list` does not shrink at all.
Rerun the head-to-head against the current Headroom (0.45; the table has 0.41).

- **Done:** each within two points of the best tool, or a written reason why not.
- **Verify:** the agent corpus with its facts; property tests that every line that
  disappeared is covered by a marker (Hypothesis, every compressor).

### 9. Reads, measured before built (S, then M)

File reads are 53 % of the tool tokens and save 0 to 1.5 %, on purpose. The one
safe lever is text the model already has: the same lines read again.
[One count](https://github.com/ojuschugh1/sqz#session-level-with-dedup) says whole
files repeat in 1 of 542 reads and line ranges in 8.4 %.

- **First:** count it in `session_replay`. Stop if it is under 2 % of tool tokens.
- **Done:** a reference instead of a repeat, only while the earlier copy is still
  in context and the file is unchanged; also in hook mode.

### 10. Model and effort routing with a holdout (M) **[decision]**

The router exists, is off and unmeasured; effort is not touched. The largest lever
on the bill and the one with the weakest evidence about quality, so: rules only,
off by default, randomised holdout, shown next to turns and retries.

- **Done and verify:** item 1's harness with routing as a fourth arm.

### 11. Reach (M) **[decision] [money]**

PyPI, winget, Homebrew and Scoop are prepared and wait for accounts. Missing:
the MCP Registry, a Claude Code plugin, Linux on ARM, signed Windows and macOS
builds.

- **Done:** the one-line install of each channel works on a clean machine in CI.

### 12. More providers without an adapter (M)

Bedrock, Vertex and Azure paths, Codex with a ChatGPT sign-in, `/metrics` for
Prometheus. Requests Sensei does not understand are relayed since this release;
these need their own signing.

- **Verify:** recorded, scrubbed exchanges as tests; no live keys in CI.

### 13. MCP depth (M)

OAuth to remote servers in the proxy, `sensei_search(ccr_id, query)` over stored
output, resources next to tools.

### 14. Soak and size (S)

A nightly hour of streams, aborts, 429s and 5 MB logs against a fake provider, with
limits on memory and p95 overhead (today 4 ms on a small request, 11 ms on a
40-turn conversation). The web UI is at 450 of 450 kB: split the markdown renderer.

## Decisions only the maintainer can make

1. **Money and publishing for item 1.** The result may be zero. It should be
   published anyway; that is the point.
2. **Focus.** About a fifth of the backend is neither gateway, hooks, MCP nor
   setup: Qt app, agent, crawler, knowledge base, accounts and SSO, webhook. Then
   there is the Sensei-1 training folder. Each needs updates and is attack surface. Proposal: freeze them, move the Qt app and
   `training/` to their own repositories, decide on the rest after item 1.
3. **MCP SDK 2.3** (Dependabot 168). The cap exists because Copilot CLI 1.0.98
   could not start the server with 2.3.0. Probing both versions by hand showed no
   difference in eight openings, so only a run of the real CLI can lift it.
4. **Accounts and certificates** for item 11.
5. **Repository settings** for item 4.
6. **`roadmap.html`** is a hand-written page from June 2026 that nothing links to
   and nothing generates. Delete it, or let it redirect here.

## Not planned

- Rewriting prose or code the user wrote. It was lossy, unmarked, and worth 0.01
  points of the bill.
- Learned compressors as a default. Generic ones cost
  [6 to 12 points of solve rate](https://arxiv.org/html/2601.16746v1) on code.
- Telemetry of any kind.
- A hosted service while the local one is unproven.

# Earlier list

Kept for the ideas and the history; not a promise and not in any order. What the
0.2 and 0.3 releases really brought is in [CHANGELOG.md](CHANGELOG.md), the reasons
behind older choices in [docs/ROADMAP-NEXT.md](docs/ROADMAP-NEXT.md).

## Recently shipped (2026-06)

- [x] CSV-schema JSON compaction and log triage, with a six-sample regression guard (79% on those samples, which says nothing about a bill)
- [x] **OpenAI + Anthropic compression gateway** — drop-in proxy (`/v1/chat/completions`, `/v1/messages`) with client-key passthrough; routes Claude Code / Codex / Cursor / any SDK
- [x] **Agent-aware compression** — compresses `tool_result` payloads (cache-safe); the system prompt stays byte-exact since the release after 0.3
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
- [x] **Streaming responses** — SSE token-by-token streaming with a Stop button (chat panel)
- [ ] **Markdown rendering** — Code blocks with syntax highlighting, tables, LaTeX
- [ ] **Copy / regenerate / edit messages** — Full message control like Claude
- [ ] **Keyboard-first navigation** — Cmd+K command palette, arrow keys, Enter to send
- [ ] **Low-memory mode** — Lazy-load conversations, virtual scrolling, minimal DOM
- [ ] **Offline indicator** — Show connection status, queue messages when offline
- [ ] **System prompt editor** — Per-conversation custom instructions
- [ ] **Token counter** — Live display of tokens used / saved per message

### Enterprise & Company Features
- [ ] **SSO / SAML integration** — Connect to Okta, Azure AD, Google Workspace
- [x] **Role-based access control (RBAC)** — admin/user roles on the user JWT; admin gate on settings/audit/purge (opt-in via SENSEI_RBAC_ENABLED + SENSEI_ADMIN_EMAILS)
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
- [x] **Data auto-purge** — Background loop drops expired sessions/CCR + audit entries older than N days; manual POST /api/maintenance/purge
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
- [x] **Reverse proxy support** — Nginx, Caddy, Traefik templates in deploy/ (SSE-safe)
- [ ] **API proxy mode** — Sensei as a transparent proxy with compression for any LLM API
- [ ] **Load balancer support** — Multiple Sensei instances behind HAProxy
- [ ] **Custom DNS resolution** — Route requests through specific DNS for privacy
- [ ] **Tor / I2P support** — Route API requests through Tor for anonymity
- [ ] **Corporate proxy compatibility** — HTTP_PROXY / HTTPS_PROXY support
- [x] **Request filtering** — Block models (substring) or content (regex) at the gateway → 403 blocked_by_policy
- [x] **Request filtering (DLP redaction)** — Redact secrets (keys, tokens, private keys, JWTs) and optional PII (email/IP) before prompts leave the machine; counts in X-Sensei-Redactions + audit

### OpenClaw-style Multi-Channel
- [ ] **Discord bot integration** — Chat with Sensei from Discord servers
- [ ] **Telegram bot** — Use Sensei via Telegram
- [ ] **Slack integration** — Sensei as a Slack app
- [ ] **WhatsApp bridge** — Connect via WhatsApp Web
- [ ] **Matrix support** — Federated chat integration
- [ ] **Email assistant** — Send emails to Sensei, get responses
- [x] **Webhook API** — Authenticated POST /api/webhook (token header) for Slack/Zapier/bots → compressed chat reply
- [ ] **Multi-agent routing** — Route different channels to different models/configs

### Improvements
- [ ] **Semantic compression** — Use embeddings to identify and remove redundant context
- [ ] **Adaptive compression** — Learn which compression strategies work best per user
- [ ] **CCR prefetch** — Predict which compressed originals the model will need
- [ ] **Graceful degradation** — Better error messages when providers are unavailable

### Testing
- [x] **Frontend tests** — Vitest unit tests (run in CI)
- [ ] **E2E tests** — Playwright for web UI
- [ ] **Load tests** — Locust or k6 for rate limiting validation
- [x] **Coverage reporting** — pytest-cov (~64%), reported in CI
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
- [x] **Agent system** — provider-agnostic ReAct loop (`/api/agent/run`), tool results compressed
  - [x] File operations — read/list/**search** tools, sandboxed to `agent_root` (no traversal)
  - [x] Knowledge-base tool — `rag_search` over the RAG store
  - [x] Custom tool plugins — `ToolRegistry` (register your own `Tool`s)
  - [x] VS Code "Run agent task" command
  - [x] Web tools — `fetch_url` (SSRF-guarded, per-hop revalidated) + `web_search` (Brave)
  - [x] Code execution — `run_python` (opt-in `SENSEI_CODE_EXEC_ENABLED`, isolated subprocess + timeout)
  - [x] Crawl-to-RAG — `POST /api/rag/crawl` BFS same-domain, robots.txt, depth/page caps, SSRF-guarded
  - [ ] Docker-sandboxed code exec (more crawling ideas in docs/ideas-web-crawling.md)
- [x] **RAG (Retrieval-Augmented Generation)** — Upload documents, chat with them
  - [x] Local store + **BM25** retrieval (zero-dependency; no embedding model/key needed)
  - [x] Automatic chunking and indexing (`/api/rag/documents`, `/api/rag/query`, `/api/rag/chat`)
  - [x] Citation tracking (sources returned + cited in the grounded answer)
  - [x] Multi-document queries; VS Code "Add file to knowledge base" + "Ask your docs"
  - [ ] Optional vector/embedding backend (behind the same interface)
- [ ] **Conversation branching** — Fork conversations at any point
- [ ] **Prompt templates** — Save and reuse prompt templates
- [ ] **Shared conversations** — Export and import conversation files
- [x] **Multi-model comparison** — POST /api/chat/compare runs one compressed prompt across up to 6 models concurrently; "Sensei: Compare models" command renders a side-by-side markdown report
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
- [x] **Systemd service files** — deploy/sensei.service (hardened)
- [ ] **Windows installer** — MSI or NSIS installer for Qt GUI
- [ ] **macOS app bundle** — .dmg for Qt GUI
- [x] **Reverse proxy guide** — deploy/README.md (TLS, streaming gotcha, hardening)
- [x] **CI/CD pipeline** — GitHub Actions: backend pytest+coverage, frontend typecheck+vitest, extension compile

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
- Token compression pipeline
- 14+ model providers: Ollama, OpenAI, Claude, Gemini, OpenRouter, Groq, DeepSeek, Mistral, Together AI, Cohere, Fireworks, Perplexity, Z.ai, HuggingFace
- One-command installer (`python install.py`) with interactive provider selection
- Web UI, Qt GUI, CLI, REST API
- Per-user sessions, auth, rate limiting, data encryption
- Docker Compose deployment with optional Ollama GPU profile
- Comprehensive test suite
