# Sensei Mega Plan — v0.2 "Latest Tech, Zero Friction"

> Status: **decisions made, Milestone 1 delivered** on branch `chore/foundation-m1`.
> Written 2026-07-27 against `main` @ `b2c18a4`.

## Decisions (locked)

| Question | Answer |
|---|---|
| Licensing | **Stay MIT, clean-room.** No Odysseus code is copied — features are re-implemented from published descriptions. Headroom's Apache-2.0 work may be used with attribution + a NOTICE file. |
| Distribution | **All four:** Docker + install scripts, native installers per OS, PyPI wheels including the Rust accelerator, VS Code Marketplace + Open VSX. |
| Priority | **Foundation first** — Phase 0 + Phase 1 before any new features. |
| Publishing | **GHCR only for now.** PyPI, Marketplace and Open VSX steps are written and gated on secrets/variables, so they no-op silently until those accounts exist. Installers ship **unsigned** with verification instructions in the release notes. |

---

## 1. Verified baseline (measured, not assumed)

Everything below was actually executed on Windows 11 / Python 3.12.10 / Node 24.14.1.

| Check | Result |
|---|---|
| `pytest -q` (backend) | **204 passed**, 23.8s, 5 warnings |
| `tsc --noEmit` (frontend) | clean |
| `vitest run` | **2 tests, 1 file** passed |
| `vite build` | clean — 336 kB JS / 102 kB gzip, single chunk |
| Backend against *newest* PyPI deps | passes (fastapi 0.140, pydantic 2.13, pytest 9.1, pytest-asyncio 1.4) |
| Repo size | 1.3 MB, 178 files (excl. `.git`) |

**Verdict: the codebase is healthy.** This is not a rescue job — it's a modernization + distribution job. That's good news; it means we can move fast.

### Warnings that are real bugs-in-waiting

- `sensei/main.py:55` and `:129` use `@app.on_event("startup"/"shutdown")` — deprecated in FastAPI, **removed** in the 0.14x line's roadmap. Must move to `lifespan`.

---

## 2. Dependency reality check

The backend uses `>=` floors, so pip already pulls current versions — but the floors are ~18 months stale and nothing pins/locks, so CI and users can get different trees. The frontend is genuinely **major versions behind**.

### Frontend — every one of these is a major-version gap

| Package | Pinned | Latest | Jump |
|---|---|---|---|
| `react` / `react-dom` | 18.3.1 | **19.2.8** | major |
| `vite` | 6.0.5 | **8.1.5** | 2 majors |
| `vitest` | 2.1.8 | **4.1.10** | 2 majors |
| `tailwindcss` | 3.4.17 | **4.3.3** | major (CSS-first config — breaking) |
| `typescript` | 5.7.2 | **7.0.2** | 2 majors |
| `react-router-dom` | 6.30.4 | **7.18.1** | major |
| `react-markdown` | 9.0.1 | **10.1.0** | major |
| `lucide-react` | 0.468.0 | **1.27.0** | 1.0 stable |
| `@vitejs/plugin-react` | 4.3.4 | **6.0.4** | 2 majors |
| `@playwright/test` | 1.48.0 | **1.62.0** | minor |

### Backend — floors to raise (no breakage found in testing)

`fastapi 0.115→0.140`, `uvicorn 0.32→0.51`, `pydantic 2.10→2.13`, `websockets 14→16`, `tiktoken 0.8→0.13`, `cryptography 43→49`, `pypdf 5→6.14`, `aiofiles 24→25`, `ruff 0.8→0.16`, `pytest 8.3→9.1`, `pytest-asyncio 0.24→1.4`, `PySide6 6.8→6.11`, `rich 13.9→15`, `torch 2.5→2.13`, `transformers 4.46→5.14`.

### Stale model IDs shipped as defaults (`.env.example`, `install.py`)

`claude-3-5-sonnet-20241022`, `gpt-4o`, `gemini-2.0-flash`, `llama-3.3-70b-versatile`, `command-r-plus`, `deepseek-chat`. These are ~2 years old in July 2026 — a new user's first impression is a dead or ancient model. Needs a **live model catalogue** rather than hardcoded strings (see §5.3).

---

## 3. Gap analysis vs. the projects Sensei is inspired by

### Headroom — now at **v0.28.0** (2026-06-29, Apache-2.0)

Sensei ported the *v0.x-era* ideas (SmartCrusher, CodeCompressor, CacheAligner, CCR, ContentRouter, cross-agent memory). Since then Headroom shipped a lot Sensei has **none** of:

| Headroom capability | Sensei today | Value |
|---|---|---|
| **MCP server** (`compress` / `retrieve` / `stats` tools) | ❌ *zero MCP anywhere in the repo* | Huge — makes Sensei usable from every MCP client |
| **Agent wrap CLI** (`wrap claude\|codex\|cursor\|aider\|…`) | ❌ manual env-var export | This is the "super easy to use" unlock |
| **Output-token reduction** (verbosity steering + effort routing, ~32% with CI-bounded estimates) | partial: `SENSEI_OUTPUT_SHAPER` flag exists | Output tokens cost 4-5× input |
| **Holdout-group measurement** (honest confidence intervals, never fabricated) | ❌ savings are point estimates | Credibility — this is what makes the README numbers trustworthy |
| **Live-zone compression** (compress only new bytes, frozen prefix byte-identical) | partial: CacheAligner | Provider cache hits |
| **AST-aware CodeCompressor** for Go/Rust/Java/C/C++/Perl | Python/JS-oriented heuristics | Coverage |
| **Learned compressor** (Kompress-v2-base, HF-hosted) | training scaffold only, not shipped | Prose compression |
| **Image compression** (40–90% via trained router) | ❌ | Vision workloads |
| **Failure learning** (`learn` — mines failed sessions into agent memory) | ❌ | Self-improving |
| **Framework adapters** (LangChain / LiteLLM / Vercel AI SDK / Agno) | gateway only | Distribution |
| **Benchmark-preservation suite** (GSM8K / TruthfulQA / SQuAD / BFCL at compression) | compression-ratio benchmark only | Proves compression doesn't hurt quality |
| **Multi-platform wheels** (mac ARM64+Intel, Linux x86_64+aarch64, Windows) | Rust crate builds locally only | Distribution |

### Odysseus — released 2026-05-31, **AGPL-3.0**, 62k★ in a week

Sensei took the "self-hosted workspace" shape (and port 7000). Missing surface area:

| Odysseus capability | Sensei today |
|---|---|
| **Cookbook** — scans your hardware, recommends + downloads + serves the right model | ❌ (only `_detect_gpu()`) |
| **Deep research** with report generation | partial — research agent preset exists |
| **Documents** — writing-first editor with AI edits | ❌ |
| **Notes / Tasks / Calendar** (CalDAV), **Email** (IMAP/SMTP triage) | ❌ |
| **Gallery / image editor, themes, presets** | ❌ |
| **2FA** | ❌ (has JWT + OIDC + RBAC) |
| **PWA-ready responsive UI** | ❌ desktop-only layout |
| **GPU compose variants** (NVIDIA + **AMD ROCm**) | NVIDIA profile only |
| **macOS app bundle / Windows portable / systemd unit** | Windows `.exe` + systemd only |

> ⚠️ **Licensing landmine:** Odysseus is **AGPL-3.0-or-later**. Sensei is **MIT**. Copying Odysseus *code* forces Sensei to AGPL. Re-implementing *ideas* from a feature list is fine. Headroom is Apache-2.0 — compatible with MIT for inbound use, but its code carries attribution + patent-grant obligations. **This is question #1 below.**

---

## 4. Ease-of-use audit — where new users bounce

I read the install path as a first-time user would:

1. **`.env.example` is 125 lines and 5.7 kB.** A user must scroll past 14 provider blocks to find the 3 lines that matter. → Ship a 12-line `.env.example`; move the rest to `docs/configuration.md`.
2. **`SENSEI_HOST=0.0.0.0` is the shipped default.** For a "privacy-first, zero-telemetry" tool this binds the API to every interface on first run. Odysseus defaults to localhost-only. → Default `127.0.0.1`, require an explicit opt-in to expose.
3. **`install.py` is a 22 kB interactive wizard** that installs deps, builds the UI, writes `.env`, pulls Ollama models, runs the test suite, and starts the server. It's impressive, but it's a bespoke installer that must be maintained by hand and can't be `winget install`-ed.
4. **No signed installers.** `packaging/README.md` literally says an Inno Setup `.iss` "is a good next addition." macOS gets nothing. Linux gets nothing but systemd.
5. **Onboarding is env-file-first, not UI-first.** There's a runtime `/api/settings` endpoint — but no first-run wizard in the web UI. A user who double-clicks an `.exe` still needs to understand env vars.
6. **The web UI has no mobile layout** (`h-screen w-screen` flex row, fixed sidebar) and no PWA manifest.
7. **README is 34 kB.** Great for depth, hostile as a landing page. → 150-line README + a docs site.

---

## 5. The plan

Seven phases. Phases 0–2 are the foundation and should land before anything else; 3–6 are parallelizable.

### Phase 0 — Repo hygiene & CI/CD backbone *(no feature work)*

The current `.github/workflows/ci.yml` runs 4 jobs, **all on `ubuntu-latest` only**, with `npm install` (not `ci`), no caching, no lint, no lockfile discipline, no security scanning, and **no release automation at all**.

Replace with:

**`ci.yml`** — the merge gate
- Backend matrix: `{ubuntu, windows, macos} × Python {3.11, 3.12, 3.13}` (9 jobs, ~4 min)
- `ruff check` + `ruff format --check` (currently configured but never run in CI)
- `mypy` or `ty` type-check on `backend/sensei`
- Frontend: `npm ci`, `tsc --noEmit`, `vitest --coverage`, `vite build`, bundle-size budget
- Extension: `npm ci` + `tsc`
- Rust: `cargo test` + `cargo clippy -D warnings` + `cargo fmt --check` on all 3 OSes
- E2E: Playwright on all 3 OSes (chromium + webkit + firefox)
- Docker: `docker build` for backend + frontend, smoke `/health`
- Coverage → Codecov with a floor (currently ~64%; ratchet, never lower)

**`security.yml`** — nightly + on-PR
- `pip-audit` / `osv-scanner` (Python), `npm audit --audit-level=high`, `cargo audit`
- CodeQL (Python + TS), `gitleaks` secret scan
- Trivy on built container images
- SBOM (CycloneDX) uploaded as an artifact
- OpenSSF Scorecard badge

**`release.yml`** — tag-triggered, the whole point
- `cibuildwheel` → `sensei_core` wheels: manylinux x86_64/aarch64, macOS arm64+x86_64, Windows x64
- PyInstaller/Nuitka → `sensei-windows-x64.exe`, `sensei-macos-universal.dmg` (notarized), `sensei-linux-x86_64.AppImage` + `.deb` + `.rpm`
- Multi-arch Docker images → GHCR (`linux/amd64` + `linux/arm64`)
- PyPI publish via **Trusted Publishing (OIDC)** — no long-lived tokens
- VS Code Marketplace + Open VSX publish
- GitHub Release with auto-generated notes, checksums, and **Sigstore/cosign signatures**
- Homebrew tap / Scoop manifest / winget manifest bumps

**`nightly.yml`**
- Run the full compression benchmark, publish `benchmarks.json` to GitHub Pages, **fail if aggregate savings regress >2%**
- Quality-preservation evals (GSM8K/SQuAD subset) at each compression level

**Supporting hygiene**
- `dependabot.yml` (pip, npm ×2, cargo, actions, docker) grouped weekly
- `.pre-commit-config.yaml` (ruff, prettier, gitleaks)
- Issue/PR templates, `CODEOWNERS`, `SECURITY.md`, `CODE_OF_CONDUCT.md`
- Conventional commits + `release-please` for automated `CHANGELOG.md` + version bumps
- All workflow actions **SHA-pinned** (supply-chain hardening)
- All `secrets.*` scoped to environments with required reviewers

### Phase 1 — Modernize the stack

- **Backend:** `on_event` → `lifespan`; raise all dep floors; add `uv.lock` (or `requirements.lock`) for reproducible CI; enable `ruff format`; add `py.typed`; drop Python 3.10 support formally, add 3.13.
- **Frontend:** React 19 (`useActionState`, `use()`, ref-as-prop cleanup), Tailwind 4 (CSS-first `@theme` config — this is the biggest single migration), Vite 8, Vitest 4, TS 7, react-router 7. Add code-splitting (336 kB single chunk today) and a bundle-size CI budget.
- **Rust:** bump edition + deps, add `cargo clippy` gate, wire `cibuildwheel` so the accelerator actually ships to users instead of being a build-it-yourself extra.
- **Extension:** modern VS Code engine, ESM bundling via esbuild, Open VSX publishing.

### Phase 2 — Ease of use (the "actually useful for people" phase)

1. **`sensei` CLI as the single front door** (replacing the bespoke `install.py` flow):
   ```
   sensei up                 # start everything, open browser
   sensei wrap claude        # route Claude Code through Sensei — zero config
   sensei wrap codex|cursor|aider|cline|continue|opencode|goose
   sensei doctor             # diagnose: ports, providers, keys, GPU, versions
   sensei models             # hardware-aware catalogue (Cookbook-style)
   sensei stats              # tokens + dollars saved
   ```
2. **First-run web wizard** — pick provider → paste key (or "use Ollama, free") → done. No env file required, ever. Writes through the existing `/api/settings`.
3. **Slim `.env.example` to ~12 lines**, everything else documented in `docs/`.
4. **`SENSEI_HOST` defaults to `127.0.0.1`**; `sensei up --expose` for LAN, with a printed warning.
5. **README rewrite** — 150 lines, one GIF, one command. Full docs move to a docs site (Docusaurus/VitePress on GitHub Pages).
6. **Cookbook-style model picker** — detect RAM/VRAM/CPU, recommend + one-click pull the model that actually fits.
7. **Mobile/PWA** — responsive layout, manifest, service worker, installable.

### Phase 3 — Latest compression tech (the Headroom catch-up)

- **MCP server** (`sensei_compress`, `sensei_retrieve`, `sensei_stats`) — highest leverage single item in this plan.
- **Output shaper, properly** — verbosity steering + effort routing, with a **holdout group** so reported savings carry real confidence intervals.
- **Live-zone compression** — compress only the delta; keep the frozen prefix byte-identical for provider cache hits.
- **AST-aware CodeCompressor** via tree-sitter: Go, Rust, Java, C/C++, C#, Ruby, PHP.
- **Ship the learned compressor** — the `training/` scaffold exists; publish weights to HF and load them lazily.
- **Framework adapters** — LangChain, LiteLLM, Vercel AI SDK, plus a thin `withSensei()` SDK wrapper.
- **Quality-preservation eval suite** in nightly CI — prove compression doesn't degrade answers.

### Phase 4 — Workspace features (the Odysseus catch-up)

Prioritized by value-per-effort, all clean-room implementations:
1. Conversation branching + editing/regeneration (already on the roadmap, high user impact)
2. Cmd+K command palette + keyboard-first navigation
3. Markdown/code/LaTeX rendering with syntax highlighting
4. File & image drag-drop into chat
5. Documents editor with AI edits
6. Notes / tasks / scheduled agent runs
7. Email + calendar (largest surface, lowest certainty — deferred pending your call)

### Phase 5 — Security & trust

- 2FA (TOTP), session-token rotation, per-user **and** per-IP rate limiting
- Docker-sandboxed code execution (currently a bare subprocess behind a flag)
- Prompt-injection detection on ingested web/RAG content
- Threat model doc + a real `SECURITY.md` disclosure process
- Reproducible builds + signed artifacts (cosign) so users can verify what they run

### Phase 6 — Community & sustainability

- Docs site, tutorial series, architecture diagrams
- `good-first-issue` backlog, contributor ladder
- Public benchmark dashboard (GitHub Pages, updated nightly)
- GitHub Sponsors / OpenCollective — funding without paywalling anything (per the existing ROADMAP principles)

---

## 6. Cross-platform matrix (the concrete deliverable)

| Target | Artifact | Built by | Tested by |
|---|---|---|---|
| Windows 10/11 x64 | `.exe` + winget + Scoop | `release.yml` | CI matrix + E2E |
| Windows ARM64 | `.exe` | `release.yml` | build-only |
| macOS 13+ arm64 | notarized `.dmg` + Homebrew cask | `release.yml` | CI matrix + E2E |
| macOS x86_64 | universal binary in same `.dmg` | `release.yml` | CI matrix |
| Linux x86_64 | AppImage, `.deb`, `.rpm`, systemd unit | `release.yml` | CI matrix + E2E |
| Linux aarch64 | AppImage + `.deb` | `release.yml` | build-only |
| Any (container) | GHCR multi-arch image | `release.yml` | smoke test |
| Any (Python) | PyPI wheel + sdist, Trusted Publishing | `release.yml` | CI matrix |
| VS Code | Marketplace + Open VSX | `release.yml` | compile + test |

macOS notarization needs an Apple Developer account ($99/yr) and Windows code-signing needs a certificate — **without them the installers still work but show OS warnings**. That's question #4.

---

## 7. Suggested sequencing

| Milestone | Contents | Rough size |
|---|---|---|
| **M1 — Foundation** | Phase 0 (full CI/CD) + Phase 1 backend/Rust | ~1 week |
| **M2 — Modern UI** | Phase 1 frontend (React 19 / Tailwind 4 / Vite 8) | ~1 week |
| **M3 — Zero friction** | Phase 2 (CLI, wizard, slim config, README, PWA) | ~1.5 weeks |
| **M4 — Latest tech** | Phase 3 (MCP, output shaper, live-zone, tree-sitter) | ~2 weeks |
| **M5 — Workspace** | Phase 4, top 4 items | ~2 weeks |
| **M6 — Trust** | Phase 5 + signing + docs site | ~1 week |

Each milestone ends in a tagged release that installs cleanly on all three OSes. Nothing merges to `main` without CI green on all three.

---

## 8. What I will *not* do without you saying so

- Push anything to `github.com/SenseiIssei/Sensei` (I'll work on local branches and show you diffs first)
- Copy any AGPL code from Odysseus
- Change the license
- Add telemetry of any kind (the ROADMAP principles forbid it — I'll honour that)
- Publish to PyPI / Marketplace / any registry

---

## 9. Milestone 1 — what actually shipped

All on branch `chore/foundation-m1`. Verified locally on Windows 11 / Python
3.12.10 / Node 24.14.1 / Rust 1.96.1 — every check below was run, not assumed.

### Phase 1 — stack modernization

| Change | Result |
|---|---|
| `@app.on_event` → `lifespan` | deprecation warnings gone; 204 tests pass |
| Backend dep floors raised to current | fastapi 0.140, pydantic 2.13, pytest 9.1, pytest-asyncio 1.4, cryptography 49, … |
| Python 3.13 declared and classified | matrix covers 3.11 / 3.12 / 3.13 |
| `py.typed` + `sensei` console entry point | `pip install` now gives you a `sensei` command |
| Ruff: **146 errors → 0**, 58 files reformatted | ruleset pinned explicitly so a new ruff release can't break CI |
| React 18 → **19.2**, Vite 6 → **8.1**, Vitest 2 → **4.1**, Tailwind 3 → **4.3**, TS 5.7 → **7.0**, router 6 → 7, react-markdown 9 → 10, lucide 0.468 → 1.27 | typecheck, unit tests, build and all 3 Playwright E2E specs pass |
| Tailwind config → CSS-first `@theme` | `tailwind.config.cjs` deleted; palette verified in the compiled CSS |
| Bundle split 1 chunk → 5 | app code 336 kB → **44.9 kB** (9.2 kB gzip); react/markdown/icons cache separately |
| pyo3 0.22 → **0.29**, Rust edition 2024, abi3-py311 | builds clean; **one wheel now covers every Python 3.11+** |
| Extension: esbuild bundling, TS 7, Open VSX | 24.7 kB source → **14.9 kB** minified single file |

### Two real bugs found and fixed along the way

1. **`SENSEI_HOST` defaulted to `0.0.0.0`** — a "privacy-first, zero-telemetry"
   tool was binding its API, your API keys and your conversations to every
   network interface on first run. Now `127.0.0.1`, with Docker passing
   `0.0.0.0` explicitly (where the container boundary is the isolation) and
   compose publishing on loopback. Exposing it is now a deliberate act.
2. **Tailwind 4 silently broke the glass effect in Firefox.** Lightning CSS
   treats a hand-written `-webkit-backdrop-filter` as authoritative and drops
   the unprefixed property. Removed the manual prefixes, added an explicit
   `browserslist`, and verified both properties are emitted.

Six silent `except: pass` blocks now log at debug level, three `raise` sites
inside `except` preserve their traceback, and five `zip()` calls state whether
truncation is intended.

### Phase 0 — CI/CD backbone

Five workflows, **every action pinned to a commit SHA** with the tag in a
comment. All validated with `actionlint` (0 findings).

- **`ci.yml`** — the merge gate. Ruff lint+format; backend across
  **{Linux, macOS, Windows} × Python {3.11, 3.12, 3.13}** = 9 jobs; frontend on
  3 OSes with a **450 kB bundle budget**; extension compile + package; Rust
  fmt/clippy/build on 3 OSes; **a byte-parity job** that builds the accelerator
  wheel and re-runs the whole suite against it; Playwright on 3 OSes; Docker
  build + `/health` smoke test. A single `CI OK` check to point branch
  protection at.
- **`security.yml`** — pip-audit, npm audit ×2, cargo audit, CodeQL
  (python / js-ts / actions, security-extended), gitleaks, Trivy on the built
  image with SARIF upload, CycloneDX SBOM, OpenSSF Scorecard. Runs nightly too,
  so a new CVE in an unchanged dependency still surfaces.
- **`release.yml`** — cibuildwheel for manylinux x86_64 + aarch64, macOS
  arm64 + x86_64, Windows AMD64; PyInstaller installers (`.exe`, `.dmg` ×2,
  AppImage, `.deb`, `.rpm`) with the web UI bundled in; multi-arch GHCR images
  with provenance + SBOM; `.vsix`; SHA256SUMS; **Sigstore keyless signatures**;
  auto-written release notes that tell users exactly how to verify a build and
  get past the unsigned-binary warnings. PyPI and Marketplace publishing gated
  on `vars.PYPI_ENABLED` / the `VSCE_PAT` / `OVSX_PAT` secrets.
- **`nightly.yml`** — runs the compression benchmark twice (pure Python and
  with the Rust accelerator), **fails if aggregate savings drop below 75%**,
  and diffs the two payloads to prove byte-parity. Plus a full test run against
  eagerly-upgraded dependencies on all 3 OSes.
- **`release-please.yml`** — conventional commits → `CHANGELOG.md`, version
  bumps across all four manifests, and the tag that triggers `release.yml`.

Supporting: `dependabot.yml` (pip, npm ×2, cargo, actions, docker — grouped),
`.pre-commit-config.yaml`, `SECURITY.md` with a real scope/out-of-scope section,
`CODE_OF_CONDUCT.md`, `CODEOWNERS`, issue forms, PR template, and a
`CONTRIBUTING.md` rewrite covering the new commands.

### Benchmark check

`python backend/benchmarks/compression_benchmark.py` reproduces **79% aggregate**
(tiktoken/cl100k) — the README's headline number is real. The benchmark now
takes `--json` and `--min-aggregate`, which is what the nightly guard uses.

### Not done, and why

- **PyPI / Marketplace / Open VSX publishing is inert.** You chose GHCR only;
  the steps exist but skip until the accounts and secrets exist.
- **Installers are unsigned.** No Apple Developer account or Windows cert. The
  release notes explain the warnings and give checksum + Sigstore verification.
- **Frontend test coverage is still 2 tests in 1 file** for ~80 kB of
  components. The E2E specs carry the real weight. This is the biggest
  remaining gap in the foundation.
- Nothing has been pushed to GitHub, and nothing is committed — the branch
  `chore/foundation-m1` holds the working tree, awaiting your review.

## 10. Milestone 2 — Phase 2 delivered

| Item | Status |
|---|---|
| `sensei` CLI (`up` / `wrap` / `doctor` / `models` / `stats` / `chat`) | done |
| First-run web wizard, no text editor required | done |
| Live provider model lists instead of a hardcoded catalogue | done |
| `.env.example` 125 → 23 lines; full reference generated from the model | done |
| README 34 kB → readable | done |
| Hardware-aware local model sizing (the "Cookbook" idea) | done |
| Mobile layout + PWA manifest | done |
| Service worker, offline app shell, connection banner | done |
| Docs site on GitHub Pages | **not done** — deferred to Phase 6 |

### Things found along the way

- **`SENSEI_HOST` was `0.0.0.0`** — fixed in M1.
- **Tailwind 4 broke the glass effect in Firefox** — Lightning CSS drops the
  unprefixed `backdrop-filter` when a hand-written `-webkit-` variant exists.
- **The web UI loaded fonts from Google** — a privacy leak and an offline
  break in a tool whose premise is neither. CI now fails on any third-party
  origin in the built assets.
- **`"java": ("import ")`** in the code compressor was a string, not a tuple,
  so every Java line starting with i/m/p/o/r/t/space was folded away as an
  import. Java source had been silently mangled.
- **Three polynomial regexes** in the compression cleanup, on paths that
  process untrusted text. 11 s → under 2 ms.
- **The test suite shared one rate-limit budget**, so adding tests made
  unrelated tests fail. Fixed with an autouse fixture.
- **The service worker cached nothing on a real deploy** — assets are fetched
  before the worker takes control, so they must be precached at install, and
  `updateViaCache: "none"` is required or the browser keeps running an old
  worker with a stale asset list. Both only surfaced by testing offline with
  the server actually stopped.

### Measured

| | before | after |
|---|---|---|
| Gateway compression, median | 8.14 ms | **4.68 ms** |
| Gateway compression, p95 | 12.53 ms | **6.31 ms** |
| Frontend app chunk | 336 kB | **44.9 kB** (9.2 kB gzip) |
| Backend tests | 204 | **273** |
| Frontend tests | 2 | **28** |
| Ruff findings | 146 | **0** |

## 11. Next up

**Phase 3 — the Headroom catch-up.** In order of leverage:

1. ~~**MCP server** (`sensei_compress`, `sensei_retrieve`, `sensei_stats`).~~
   **Done.** `sensei mcp` over stdio, behind the optional `sensei[mcp]` extra.
   Verified against a real MCP client: 582 → 287 tokens on a 40-record JSON
   array, original recovered byte-identical. `sensei_retrieve` is what makes it
   safe rather than lossy-by-default, and the server's instructions tell the
   client so — a capability the model doesn't know about might as well not
   exist.
2. **Output-token shaping with a holdout group**, so any claimed saving carries
   a real confidence interval instead of a point estimate.
3. **Live-zone compression** — compress only the delta, keep the frozen prefix
   byte-identical so provider prompt caches still hit.
4. **Tree-sitter CodeCompressor** for Go, Rust, Java, C/C++, C#, Ruby, PHP.
5. **Quality-preservation evals** in nightly CI, proving compression doesn't
   degrade answers rather than only that it shrinks tokens.
