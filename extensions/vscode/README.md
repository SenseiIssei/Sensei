# Sensei — Token Saver (VS Code)

Compress prompts for **Claude Code, OpenAI Codex, and any OpenAI/Anthropic tool**
in the background — same chats, fewer tokens — plus a **Sensei chat panel** in the
sidebar. Powered by your local [Sensei](https://github.com/SenseiIssei/Sensei)
gateway (self-hosted, free, no telemetry).

## How it works

Sensei runs a local compression gateway that speaks both the OpenAI and Anthropic
APIs. Point a tool's base URL at it and every prompt is compressed before it goes
upstream — the tool keeps using **its own API key** and behaves normally.

| Tool | What the extension sets |
|------|--------------------------|
| Claude Code | `ANTHROPIC_BASE_URL` → Sensei gateway (`/v1/messages`) |
| OpenAI Codex / CLI | `OPENAI_BASE_URL` → Sensei gateway (`/v1`) |
| Cursor / Continue / Aider / any SDK | point their base URL at the gateway |

For CLI agents the extension writes `terminal.integrated.env.*`, so any agent you
launch in an integrated terminal is routed automatically. (GUI tools like Copilot
proper don't expose a base URL; use the chat panel or a BYOK/proxy setup.)

## Setup

1. Run the Sensei backend (default `http://localhost:7000`):
   ```bash
   uvicorn sensei.main:app --port 7000
   ```
2. Install this extension.
3. Command Palette → **Sensei: Route Claude Code through Sensei** (and/or Codex).
4. Open a new integrated terminal and use your tools as normal.

## Features

- **Status bar**: live `% saved · $ saved` counter (click for details).
- **Chat panel**: the Sensei activity-bar view — chat with any configured model;
  prompts are compressed before sending.
- **Commands**: route Claude Code / Codex, stop routing, show savings, open chat.

## Settings

- `sensei.gatewayUrl` (default `http://localhost:7000`)
- `sensei.backendUrl` (default `http://localhost:7000`)
- `sensei.pollSeconds` (default `15`)

## Build from source

```bash
npm install
npm run compile          # tsc -> dist/
npm run package          # vsce package -> .vsix
```
