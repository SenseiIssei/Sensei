# Changelog

## [0.3.0] — 2026-10-16

The release that makes Sensei connect itself to every AI tool it finds, handle
real coding-agent traffic, and measure itself honestly, including against
Headroom.

### Switch it on once

- **`sensei connect` / `sensei disconnect`**, plus the same two buttons in the
  tray and on the Connections page. Sensei wires every tool it detects and
  explains every tool it can't, with the reason. New tools are picked up while
  it runs. Every edit is backed up, hash-checked and reversible.
- **25 tools.** New: VS Code Copilot, Copilot CLI, Antigravity, Qwen Code,
  Crush, Factory, Junie, Kimi, Amp, Kiro, Warp, Augment, LM Studio and Goose.
  Fixed: opencode (shape and path), Kilo (`kilo.jsonc`), Devin (macOS path,
  windsurf-next), Cline (CLI and every editor), the Claude Desktop MSIX
  install, Continue (YAML), and Codex. Codex's `config.toml` is now edited
  table by table, so the Codex app rewriting the file no longer drops Sensei's
  settings.
- **Claude Code uses a hook by default, not a base URL.** A PostToolUse HTTP
  hook compresses Bash, Grep, Glob, WebFetch and MCP output before it enters
  the conversation. Read, Edit and Write are never touched. If Sensei is not
  running, the hook does nothing and Claude Code carries on. Remote Control
  and the desktop app's Code tab keep working. Routing the whole conversation
  through the gateway is still available with `--route`, with a session-start
  hook that clears the base URL if Sensei has gone away. Copilot CLI,
  opencode and Kilo get the same hook approach.
- **Installer fixes.** `SENSEI_SETUP_TOOLS=no` is now honoured; before, the
  running server wired everything 30 seconds later anyway. `install.ps1` no
  longer hangs on a real desktop.
- **Remote MCP** for clients that only accept HTTPS (ChatGPT, claude.ai
  connectors): bearer token, Host and Origin checks, and a tunnel recipe in
  `docs/remote-mcp.md`.

### Compression for what agents actually read

- **New compressors** for grep/rg results, diffs, git output, test and build
  output, directory listings, configs, HTML, minified files and base64 blobs.
- **Lossless folds first.** Each fold is verified by a round trip before
  anything lossy runs.
- **Lossy cuts can be undone.** Every lossy cut leaves a
  `[sensei: …; retrieve ccr=<id>]` marker. The id is the content hash, so the
  same input always gives the same bytes.
- **Nothing can grow.** A result that comes out larger than the input is
  replaced by the original.
- **File reads stay byte-exact**, including code that only looks like prose.
- An independent review found nine ways the first version could hide
  information, such as diff lines folded away and distinct compiler errors
  merged into one. All nine are fixed and each has a regression test.

### A gateway that respects the prompt cache

- **Live zone.** Each turn replays what was sent last turn byte for byte and
  compresses only the new messages. That keeps the provider's cache hitting
  and keeps thinking-block signatures valid. Cache misses are attributed
  (cold start, TTL, prefix change). Preparing a request takes 15 ms of CPU,
  against 84 ms in 0.2.
- **`sensei_retrieve`, answered by the gateway.** When the model asks for an
  original, the gateway fetches it and continues the upstream call, so the
  client never sees the extra round trip.
- **Tool definitions** are compacted safely; Anthropic tool search is opt-in.
- **Repeated tool output** across turns becomes a one-line reference.
- **Opt-in extras:** a model router, an exact response cache, and per-tool
  budgets.

### Honest numbers

- The README's 79% is gone; it came from six hand-written samples. On 430 real
  Claude Code and Codex sessions, Sensei removes **3.9%** of tool-output
  tokens. That is **0.68%** of the bill once prompt caching is priced in
  (Headroom 0.41 on the same data: 3.6% and 0.56%).
- On a seeded corpus of realistic agent tool output, Sensei removes **37.9%**
  (Headroom: 18.1%) and keeps 74 of 74 facts.
- `cd backend && python -m benchmarks.refresh` regenerates every number,
  graphic and README table. Nightly CI fails on regressions or a stale README.

## [0.2.0] — 2026-10-16

The release that makes Sensei safe to put in front of a coding agent all day,
easy to install on every OS, and calm to look at.

### Works with the agents people use now

- **Codex routes through Sensei again.** Codex only speaks OpenAI's Responses
  API since early 2026, and refuses to start with the `wire_api = "chat"` that
  `setup-tools` used to write. Sensei now serves `/v1/responses` (plus
  `/compact` and `/input_tokens`), compresses tool outputs inside it, and writes
  `wire_api = "responses"`.
- **Claude Code's token counting works through the gateway.**
  `/v1/messages/count_tokens` used to 404; it now counts the request as Sensei
  will actually send it, so Claude Code compacts at the right moment.
- **Agents' edits keep matching.** Source code and line-numbered file views in
  tool results now pass through byte-exact: Claude Code's Edit and Codex's
  apply_patch match text exactly, and a model that never saw a comment writes
  an `old_string` without it. `SENSEI_CODE_COMPRESSION=aggressive` restores
  rewriting for people who want the extra savings.
- **The code compressor stopped corrupting code.** It removed `#` and `//`
  inside string literals (`return "#16a34a"` became `return "`), left
  multi-line docstrings half-deleted, and folded runs of JavaScript `const`
  declarations away as if they were imports. Comment stripping is now a
  linear, string-aware scanner.
- **Errors arrive as errors.** A 429 on a streaming request used to come back
  as `200 text/event-stream`. Upstream status, body and rate-limit headers are
  now passed through; 429/5xx/529 and connection failures are retried (honouring
  `Retry-After`) before the first byte reaches the client.
- **Optional local fallback.** With `SENSEI_FALLBACK_ENABLED=true`, a request
  the provider cannot serve is answered by Ollama, llama.cpp, LM Studio or vLLM
  instead — never silently: the response carries `X-Sensei-Fallback`, and the
  provider's key is never sent to the local server.
- Current defaults: Claude Sonnet 5.5, GPT-6.1 Sol, Gemini 3.8 Flash, GLM-5.3,
  DeepSeek V4 Flash, gpt-oss on Groq; a refreshed local catalogue (Qwen3.5/3.8,
  Gemma 4, gpt-oss, Ornith). Gemini, Cohere and HuggingFace base URLs that could
  not have worked are fixed.

### Honest numbers

- **Prompt-cache accounting.** The ledger now records what the provider billed
  — including cache reads and writes, from JSON responses and from streams —
  and the dashboard shows the cache hit rate next to the savings. Compression
  that broke caching would show up here.

### New

- **MCP proxy.** List other MCP servers in `~/.sensei/mcp-servers.json` (Claude
  Desktop's format) and an agent sees two tools instead of all of theirs:
  `sensei_find_tools` and `sensei_call_tool`. Results come back compressed;
  long ones arrive as a first page plus an id that `sensei_retrieve` pages
  through. `sensei mcp --transport streamable-http` serves MCP over HTTP.
- **Disassembly compression** for objdump, GDB, radare2, Ghidra and IDA
  listings: opcode bytes, flow gutters and padding runs go; every address,
  mnemonic and operand stays. 42–56% fewer tokens on typical listings — useful
  behind reverse-engineering MCP servers like REA or GhidraMCP.

### Install, start, update — on every OS

- **One-command installers.** `curl -fsSL …/install.sh | sh` (macOS, Linux)
  and `irm …/install.ps1 | iex` (Windows) download the release binary, verify
  it against `SHA256SUMS`, and offer autostart and tool wiring. No Python
  needed. The README's pipx, Homebrew, Scoop and winget lines pointed at
  packages that were never published; they are gone.
- **`sensei autostart on|off|status`**: a Run key on Windows, a LaunchAgent on
  macOS, a systemd user service (or XDG autostart) on Linux. Per-user,
  reversible, no administrator rights.
- **`sensei update [--check]`**: asks GitHub only when you run it (or daily with
  `SENSEI_UPDATE_CHECK=true`), replaces binary installs in place after verifying
  the checksum, runs the Windows installer silently, and tells pip users the
  one command. The tray menu gains "Start at login" and "Check for updates".
- The Windows installer puts `sensei` on the user's PATH and survives being
  run over a running copy.

### A calm redesign

- New look after dpm.lol: quiet surfaces, hairline borders, one periwinkle
  accent, gold only for the number a page is about. **Light and dark**,
  following the system by default. Same tokens and font as Odysync.
- New **Connections** page (which tools are routed, gateway addresses, MCP) and
  a real **Settings** page (theme, the chat's provider, updates, autostart) in
  place of a panel whose sliders changed nothing.
- New logo; tray and Windows icons to match.

### Security

- DLP redaction now recognises OpenAI's current key formats (`sk-proj-…`,
  `sk-svcacct-…`), which slipped through, and covers `count_tokens` and
  `responses/compact` too. It no longer rewrites thinking signatures or
  encrypted reasoning, which providers verify byte for byte.
- A quadratic regular expression in the prose compressor, a log-injection path
  and an exception message reaching clients — all found by CodeQL — are fixed.
- CI is green again: the frontend's vitest/coverage mismatch, the extension's
  `braces` advisory (via an `ovsx` override), the nightly benchmark push, and
  the extension's `@types/vscode` drift are fixed. Python 3.14 joins the matrix,
  and every installer is run for real on Windows, macOS and Linux in CI.

## Earlier releases

See the [GitHub releases](https://github.com/SenseiIssei/Sensei/releases) for
0.1.0 – 0.1.19.
