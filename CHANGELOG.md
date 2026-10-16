# Changelog

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

- DLP redaction no longer rewrites thinking signatures or encrypted reasoning,
  which providers verify byte for byte.
- A quadratic regular expression in the prose compressor, a log-injection path
  and an exception message reaching clients — all found by CodeQL — are fixed.
- CI is green again: the frontend's vitest/coverage mismatch, the extension's
  `braces` advisory (via an `ovsx` override), the nightly benchmark push, and
  the extension's `@types/vscode` drift are fixed. Python 3.14 joins the matrix,
  and every installer is run for real on Windows, macOS and Linux in CI.

## Earlier releases

See the [GitHub releases](https://github.com/SenseiIssei/Sensei/releases) for
0.1.0 – 0.1.19.
