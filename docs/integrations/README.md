# Connecting your AI tools

Turn it on once and Sensei connects to every AI tool it finds, including tools
you install later:

```bash
sensei connect                  # connect every detected tool, now and as new ones appear
sensei setup-tools --status     # what is connected, how, and why not
sensei disconnect               # put every file back and stop connecting
```

You can do the same from the tray menu (**Connect everything** /
**Disconnect everything**) or from the dashboard's **Connections** page. Both
show the same per-tool status.

## What "connected" means

A tool can be connected in up to three ways. Sensei uses the strongest one the
tool allows without breaking any of its features.

| Way | What happens | Used for |
|---|---|---|
| **hook** | After each tool call, the tool sends the output (shell, grep, web fetch, MCP) to Sensei. Sensei returns a compressed version before the model sees it. File reads and edits are never touched. | Claude Code, Copilot CLI, opencode, Kilo |
| **route** | The tool's model requests go through the gateway at `http://127.0.0.1:7000`, and the whole prompt is compressed. | Aider, Continue; opt-in for Claude Code, Codex and VS Code Copilot |
| **mcp** | Sensei's MCP tools are registered: `sensei_compress`, `sensei_retrieve`, `sensei_stats`, plus the proxy for your other MCP servers. | Every tool with an MCP config file |

Every hook **fails open**. If Sensei is not running, is slow or hits an error,
the tool keeps its original output and carries on. Every compressed output ends
with a `sensei_retrieve(ccr_id="…")` hint, so the model can fetch the exact
original whenever it needs it.

## Per tool

| Tool | Default | Opt-in | Files | Notes |
|---|---|---|---|---|
| [Claude Code](claude-code.md) | hook + MCP | `--route` | `~/.claude/settings.json` (hooks), `~/.claude.json` (MCP) | Sign-in, Remote Control and the desktop app's Code tab keep working |
| Claude Desktop | MCP | – | `claude_desktop_config.json` (and the Store/MSIX copy) | Chat traffic cannot be routed without leaving the claude.ai login |
| [Codex](codex.md) (CLI, IDE, app) | MCP | `--route` | `~/.codex/config.toml` | Tables are edited by name, so the edit survives the Codex app rewriting the file |
| Cursor | MCP | – | `~/.cursor/mcp.json` | Model calls are made from Cursor's servers |
| VS Code + Copilot | MCP | by hand: Language Models → Custom Endpoint, URL `http://127.0.0.1:7000/v1/messages` | `Code/User/mcp.json` | VS Code only reads model keys from its secret storage, so Sensei cannot write a working model group |
| GitHub Copilot CLI | hook + MCP | `sensei wrap copilot` | `~/.copilot/mcp-config.json`, `~/.copilot/hooks/sensei.json` | The hook pipes the payload to Sensei with `curl -T -`. Copilot already replaces outputs over ~25 KB with a short preview before hooks run, so the hook pays off on mid-sized outputs |
| Gemini CLI | MCP | – | `~/.gemini/settings.json` | Its AfterTool hook can block or append to a result, not replace it. A compressed output delivered as "Tool result blocked" makes the model retry, so there is no hook |
| Antigravity CLI | MCP | – | `~/.gemini/config/mcp_config.json` | Its hooks cannot rewrite tool results |
| Devin Desktop / Windsurf | MCP | – | `%APPDATA%\devin\mcp_config.json`, `~/.config/devin/` (macOS/Linux), legacy `~/.codeium/windsurf*` | |
| Cline | MCP | – | `~/.cline/data/settings/`, plus the extension in every VS Code-family editor | |
| Roo Code / Zoo Code | MCP | – | extension `globalStorage` | Roo Code shut down in May 2026 |
| Kilo Code | hook + MCP | – | `~/.config/kilo/kilo.jsonc`, `~/.config/kilo/plugin/sensei.js` | A `kilo.jsonc` with comments is a manual step |
| opencode | hook + MCP | – | `~/.config/opencode/opencode.json`, `~/.config/opencode/plugins/sensei.js` | On Windows this is `%USERPROFILE%\.config`, not `%APPDATA%` |
| Continue | MCP (+ legacy route) | – | `~/.continue/mcpServers/sensei.yaml` | `config.yaml` models are a manual step |
| Zed | MCP | – | Zed `settings.json` (`context_servers`) | Comments in the file make this a manual step |
| Qwen Code, Crush, Factory Droid, Junie, Kimi, Amp, Kiro, Warp, Augment, LM Studio | MCP | `sensei wrap <tool>` where routing exists | each tool's MCP file | Best-effort: documented formats, not yet verified end to end |
| Aider | route | – | `~/.aider.conf.yml` | Aider has no MCP |
| Goose | MCP | `sensei wrap goose` | `config.yaml` `extensions:` | An existing `extensions:` key is a manual step |

Tools Sensei cannot connect from this machine are listed in `--status` with the
reason:

- **JetBrains AI Assistant** stores its settings in the IDE UI only. It can
  import Claude Desktop's MCP servers, and Sensei does wire those.
- **ChatGPT**, **claude.ai connectors** and **Devin cloud** only reach MCP
  servers from the vendor's cloud. See [remote-mcp.md](../remote-mcp.md).

## Verified end to end

These were run for real on Windows 11 with a scripted model server in a
temporary home directory. Each run checked what the model actually received,
and was repeated with Sensei stopped:

| Tool | Version | Compression hook | MCP tools reach the model | Sensei stopped |
|---|---|---|---|---|
| Claude Code | 2.1.299 | yes (`updatedToolOutput` accepted by the tool's schema check) | yes | original output, tool keeps working |
| GitHub Copilot CLI | 1.0.98 | yes (`modifiedResult`) | yes | original output |
| opencode | 1.19.3 | yes (plugin in `plugins/`) | yes | original output |
| Kilo CLI | 7.8.12 | yes (plugin in `plugin/`, default export) | yes | – |
| Gemini CLI | 0.64.0 | no — see above | yes | – |

What those runs fixed:

- **The hook command.** `--data-binary @-` is a PowerShell parse error, which
  is the shell Copilot CLI uses on Windows. The hook now uses `-T -`.
- **The MCP command.** MCP entries now name Sensei's own executable by
  absolute path. A bare `sensei` ran whichever program answered to that name
  first on PATH.
- **The MCP SDK.** It is pinned below 2.3. mcp 2.3.0 refuses the handshake
  Copilot CLI falls back to.
- **`CLAUDE_CONFIG_DIR`.** It is honoured for both `settings.json` and
  `.claude.json`.

Rows marked best-effort in `sensei setup-tools --status` follow each tool's
documented format but have not been run like this.

## Safety

- Every file is backed up to `~/.sensei/backups/<timestamp>/` before Sensei
  writes it. The manifest `~/.sensei/integrations.json` records what was
  written and where.
- Undo restores the backup only if the file still hashes to what Sensei wrote.
  If the file changed since then (you edited it, or the tool rewrote it), undo
  removes only Sensei's own keys and leaves everything else in place.
- Sensei never rewrites a JSON file that has comments. It reports a manual step
  with the exact snippet to paste instead.
- **"Don't connect my tools" is remembered.** The installers write it before
  the server starts, so the background scan never overrides it.
  `sensei connect` (or the tray's checkbox) turns automatic connection back on.
- **A tool you disconnect by hand stays disconnected.** `sensei setup-tools
  --only <tool>` reconnects it.
- The uninstaller runs `setup-tools --undo --forget`, which reverts every edit
  and forgets every choice, so a later reinstall starts fresh.

## Try it without touching anything

```bash
sensei setup-tools --dry-run
```
