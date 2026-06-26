# Installing & packaging Sensei

Three ways to install, easiest first.

## 1. One-line console install

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -Run
```

**macOS / Linux:**
```bash
./install.sh        # or: python install.py
```

This creates a venv, installs the backend, builds the web UI (if Node is
present), writes `.env`, and (with `-Run`) starts Sensei on
`http://localhost:7000`.

## 2. Single `.exe` (no Python needed by the end user)

Build a standalone `sensei.exe` that serves the backend + web UI and opens a
browser:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
# -> dist\sensei.exe
```

Under the hood this uses [`packaging/sensei.spec`](sensei.spec) with
[`packaging/launcher.py`](launcher.py) as the entry point. Ship `dist\sensei.exe`
— double-click to run. (For a signed installer, wrap it with Inno Setup or NSIS;
a `.iss` template is a good next addition.)

## 3. VS Code extension

```bash
cd extensions/vscode
npm install && npm run package      # -> sensei-tokens-0.1.0.vsix
code --install-extension sensei-tokens-0.1.0.vsix
```

Publish to the Marketplace with [`vsce`](https://github.com/microsoft/vscode-vsce):

```bash
npm i -g @vscode/vsce
vsce login senseiissei      # needs a publisher + PAT
vsce publish
```

## What the end user gets

- `http://localhost:7000/app` — the Sensei web UI (when the frontend is bundled)
- `http://localhost:7000/v1` — OpenAI-compatible compression gateway
- `http://localhost:7000` — Anthropic-compatible gateway (`/v1/messages`)
- the VS Code extension's status bar + chat panel + one-click tool routing
