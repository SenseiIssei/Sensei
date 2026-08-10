# What's next

Written 2026-07-27, after Phase 2 and the MCP server landed. Revised 2026-08-10.
This is the handover document: enough context that someone picking this up cold
— including me, in six months — knows what to do and why, without re-deriving it.

The strategic picture is in [MEGAPLAN.md](MEGAPLAN.md). This is the queue.

---

## Landed since this was written (2026-08-10)

- **`sensei setup-tools`** — the config-file counterpart to `wrap`. Detects the
  AI tools on the machine and writes the routing into their own configuration:
  Claude Code, Cursor, Windsurf, Cline, Continue, Gemini CLI, opencode as JSON;
  Codex and Aider as a marker-delimited appended block, because TOML and YAML
  have no writer in the standard library and this project is not taking a
  dependency for one. Backed up, idempotent, `--undo`, `--dry-run`. Wired into
  `install.py` and `install.ps1`, so a fresh install ends with everything
  already routed. See `sensei/integrations.py`.
- **A savings ledger that survives a restart.** `SavingsTracker` was in-memory
  only, which meant the answer to "how much have I saved" was always "since the
  last time you closed the lid". There is now a local SQLite ledger recording
  counters, tool, provider and model per request — no prompt text — behind
  `SENSEI_SAVINGS_PERSIST`.
- **The savings dashboard.** `/app/` → *Tokens Saved*: lifetime and session
  totals, a 30-day chart, and breakdowns by tool, provider and model. The chart
  is hand-drawn SVG; a charting library does not fit in the 450 kB budget.
- **Security workflow back to green.** Three findings, all real, none of them a
  vulnerability in Sensei: nanoid pinned to the patched 3.3.17+ via an override,
  three transitive advisories in the extension's lockfile, and two gitleaks
  false positives — the redaction test corpus and a placeholder in a docstring —
  allowlisted with reasons in `.gitleaks.toml`.

### Distribution and trust (2026-08-10, second pass)

- **`sensei-gateway` on PyPI.** The plain name is taken by an unrelated 2023
  HTTP library and `sensei-ai` is taken too; the roadmap said to check, and this
  is the answer. The import package and the command stay `sensei`.
- **Homebrew, Scoop and winget.** `scripts/render_manifests.py` builds all three
  from the release's own `SHA256SUMS`, so a formula cannot pin last version's
  digest. The release now also emits `.tar.gz` and `.zip` next to the `.dmg` and
  `.exe`, because `brew` cannot install from a disk image. The tap and bucket
  jobs are gated on their tokens existing, like the marketplace ones.
  See [packaging.md](packaging.md).
- **A public benchmark trend** on `gh-pages`, appended nightly. The README's 79%
  is now a line rather than an assertion.
- **Fact-retention evals.** See `benchmarks/quality_eval.py`. Two real defects
  fell out of writing it, both in the highest-value content type:
  `LogCompressor.FRAME` said `File ", "` where `File "` was meant — so no Python
  traceback frame ever matched and the innermost frames were elided — and build
  output was being detected as prose (3% compression instead of 91%, with the
  compiler's `file:line:col` discarded). The Rust accelerator had faithfully
  reproduced the regex bug, which is the parity test working correctly and also
  why nobody caught it.

### Where Headroom is now ahead

Worth checking before planning Phase 3, because it is the same problem being
solved twice. Headroom has since shipped **output-token reduction** (verbosity
steering and effort routing, which is exactly the item below), **cross-agent
memory**, `headroom learn` for mining failed sessions, and Copilot-CLI OAuth
support. The output-shaping design below was written independently and still
holds — in particular the holdout requirement, which is the part worth keeping.

---

## Do these first — they're cheap and they're blocking

### 1. Two checkboxes in repository settings

Neither can be done from a file in this repo.

**Release Please is gated off.** The workflow fails with *"GitHub Actions is not
permitted to create or approve pull requests"* until:

1. **Settings → Actions → General → Workflow permissions** →
   ☑ *Allow GitHub Actions to create and approve pull requests*
2. **Settings → Secrets and variables → Actions → Variables** →
   `RELEASE_PLEASE_ENABLED` = `true`

Until then it reports `skipped` rather than red, which is deliberate: a
permanently failing check teaches everyone to ignore the badge, and then a real
failure goes unnoticed.

Worth knowing before ticking it: that checkbox grants *create* and *approve*
together, with no way to separate them. Only `release-please.yml` requests
`pull-requests: write` here and every action is SHA-pinned, so the exposure is
confined — but if `main` is ever set to require approving reviews, a workflow
holding that permission could satisfy the requirement by itself.

**CI is not actually a merge gate.** `main` requires a PR, but the required
review count is `0` and there are **no required status checks** — a red PR can
be merged today. The `ci.yml` job named **`CI OK`** exists precisely to be the
one check to require: it aggregates every other job, so pointing branch
protection at it gates the whole matrix and needs no reconfiguration when a job
is added.

### 2. Screenshots for the README

The README has a "Screenshots wanted" placeholder because they can't be captured
in a headless environment, and mocking one up and presenting it as the product
would be dishonest. Four would help, listed in
[`docs/screenshots/README.md`](screenshots/README.md). Redact API keys first.

---

## Phase 3 — finish the compression story

The MCP server is done. Four items left, in leverage order.

### Output-token shaping, with a holdout group

Output tokens cost roughly 4-5× input tokens, and Sensei currently does nothing
about them. `SENSEI_OUTPUT_SHAPER` exists as a flag with no real implementation
behind it.

Two mechanisms: verbosity steering (system-prompt guidance that trims
boilerplate from responses) and effort routing (send the easy turns to a
cheaper/faster model).

**Do not ship this with a point estimate.** The honest way to measure an
intervention that changes model behaviour is a holdout: leave a configurable
fraction of requests unshaped, compare, and report a confidence interval. A
claimed "31% output saving" with no interval is a number nobody should trust,
including us. `SENSEI_OUTPUT_HOLDOUT` defaulting to ~0.1 is the shape of it.

Acceptance: the stats endpoint reports output savings *with* an interval, and
says "not enough data yet" until the sample supports one.

### Live-zone compression

Providers cache on an exact prefix match. Today `CacheAligner` keeps the system
prompt byte-exact, but everything after it is recompressed each turn, so a long
agent conversation re-prefills more than it needs to.

Compress only the *new* bytes — the fresh tool result at the end — and leave
every earlier turn byte-identical. Slightly less total compression, materially
lower latency on cache-heavy agents.

`SENSEI_GATEWAY_PRESERVE_CACHE` is a partial version of this already. The work
is making it the default behaviour with a proper frozen-prefix boundary rather
than a whole-message heuristic.

Acceptance: a multi-turn conversation through the gateway produces a byte-identical
prefix across turns, verified in a test rather than by inspection.

### Tree-sitter CodeCompressor

`CodeCompressor` is regex-driven. That was the right call for zero dependencies
and speed, and it works for Python and JS. It does not work well for Go, Rust,
Java, C/C++, C#, Ruby or PHP, and it produced a real bug — `"java": ("import ")`
was a string rather than a one-tuple, so every Java line starting with i, m, p,
o, r, t or a space was folded away as an import.

Tree-sitter grammars would make this structural instead of textual. Keep the
regex path as the fallback when a grammar isn't installed, behind an optional
extra, so a default install stays dependency-light.

Acceptance: a language-per-file corpus where the compressed output still parses.

### Quality-preservation evals in nightly CI

Nightly proves compression *shrinks* things. It does not prove the model still
answers correctly. Those are different claims and only one of them is currently
checked.

Run a subset of GSM8K / SQuAD / a tool-calling benchmark at several compression
levels and track accuracy alongside the ratio. If aggressive compression costs
three points of accuracy, that should be visible in the repository, not
discovered by a user.

Acceptance: nightly publishes ratio *and* accuracy, and fails if accuracy drops
beyond a floor.

---

## Phase 4 — workspace features

Clean-room only. Odysseus is AGPL-3.0; copying its code would force Sensei to
AGPL and close off the whole point of staying MIT. Implement from published
descriptions, never from source.

Ordered by value per unit of effort:

1. **Conversation branching** — fork at any message. The single most-requested
   thing in every chat UI, and the data model already stores messages in a list.
2. **Cmd+K command palette** and keyboard-first navigation.
3. **Markdown rendering with syntax highlighting**, code blocks, tables, LaTeX.
   `react-markdown` is already a dependency; this is mostly a `rehype` plugin
   and a theme.
4. **File and image drag-drop into chat.** `FileReference` already exists in the
   type model and is unused.
5. **Documents** — a writing-first editor with AI edits.
6. **Notes, tasks, scheduled agent runs.**
7. **Email and calendar.** Largest surface, least certain value. Do this last or
   not at all.

---

## Phase 5 — security and trust

- **2FA (TOTP)** and session-token rotation.
- **Per-IP rate limiting** alongside the existing per-user limiter.
- **Docker-sandboxed code execution.** `run_python` is currently a subprocess
  with a timeout. The docs say so plainly, which is the minimum bar, but a
  container is the actual fix.
- **Prompt-injection detection** on ingested web and RAG content. Sensei
  crawls pages and feeds them to an agent with tools; that is the classic
  injection path and there is nothing in the way of it today.
- **A written threat model.** `SECURITY.md` has scope and reporting, not a
  model of who the attacker is and what they can reach.
- **Signed releases.** Artifacts carry SHA256SUMS and Sigstore signatures
  already; the installers themselves are unsigned because there is no Apple
  Developer account ($99/yr) and no Windows code-signing certificate. Until
  those exist, the release notes explain the OS warnings and how to verify
  instead — which is more honest than a signature nobody checks, but it is not
  a substitute.

---

## Phase 6 — distribution and community

- **Docs site** on GitHub Pages. Deferred from Phase 2 because
  `docs/configuration.md` is generated and the README now carries the rest.
  Worth doing when there is more than one page of prose to host.
- **PyPI publishing.** `release.yml` has the Trusted Publishing step wired and
  gated on `vars.PYPI_ENABLED`. Needs the project created on PyPI and GitHub
  added as a trusted publisher — check whether the name `sensei` is taken first.
- **VS Code Marketplace and Open VSX.** Also wired, gated on `VSCE_PAT` /
  `OVSX_PAT`.
- **Public benchmark dashboard** — nightly already produces `benchmark-*.json`
  artifacts; publishing them as a trend line makes the 79% claim continuously
  auditable rather than a number in a README.
- **Framework adapters** — LangChain, LiteLLM, Vercel AI SDK. Each is a thin
  wrapper over the existing gateway and each opens a distribution channel.

---

## Things that are true and worth not forgetting

Written down because each cost real time to find, and none of them are visible
from reading the code:

- **Test the offline path by stopping the server.** The service worker was
  written, compiled, and unit-tested green while being completely broken — it
  cached the shell but none of the hashed assets, so offline you got a blank
  page. Only stopping the process and reloading surfaced it.
- **Test the app the way `sensei up` serves it**, under `/app/`, not just from
  `vite preview` at the root. Root-absolute asset URLs 404 into the API, which
  answers with JSON, and a browser handed JSON for a module script does nothing
  at all — no error, no console output. `scripts/check-subpath-safe.mjs` guards
  this now.
- **A Dockerfile that names a Python version in a path will break on a base
  image bump**, and it will break by building successfully and importing
  nothing. Packages live in a venv at a fixed path for this reason.
- **`npm audit` advisories are not monotonic.** Downgrading react-router to
  escape one high-severity advisory would have walked into fourteen, including
  an unauthenticated RCE. Always read the affected ranges of the version you're
  moving *to*.
- **Regexes that touch untrusted text must be linear.** Three in the compression
  cleanup were quadratic and took 11 seconds on 30 kB of whitespace.
  `tests/test_regex_redos.py` asserts both equivalence and complexity.
- **A rate limiter shared across a test suite is a time bomb.** Adding ten tests
  made two unrelated ones fail. `tests/conftest.py` resets it per test.
- **A check that cries wolf gets deleted.** The third-party-asset check parses
  actual resource references rather than grepping for `https://`, because
  library code is full of documentation links in error messages.
