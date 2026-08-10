# Sensei one-command installer (Windows / PowerShell)
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1 [-Run] [-SkipTools]
#
# -SkipTools leaves your editors and CLIs untouched. Without it, the installer
# wires the AI tools it finds on this machine into the gateway — after showing
# you exactly which files it would change and asking. `sensei setup-tools --undo`
# reverses all of it.
param([switch]$Run, [switch]$SkipTools)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "==> Installing Sensei from $root" -ForegroundColor Cyan

# 1. Python
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { throw "Python 3.11+ is required and was not found on PATH." }
Write-Host "==> Using $((& python --version) 2>&1)"

# 2. Backend venv + deps
$venv = Join-Path $root "backend\.venv"
if (-not (Test-Path $venv)) {
    Write-Host "==> Creating virtual environment"
    & python -m venv $venv
}
$vpy = Join-Path $venv "Scripts\python.exe"
Write-Host "==> Installing backend dependencies"
& $vpy -m pip install --upgrade pip -q
& $vpy -m pip install -e (Join-Path $root "backend") -q

# 3. .env
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host "==> Wrote .env (edit it to add an API key, e.g. SENSEI_OPENROUTER_API_KEY)"
}

# 4. Frontend (optional, if Node is present)
if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host "==> Building web UI"
    Push-Location (Join-Path $root "frontend")
    & npm install --no-audit --no-fund --loglevel=error
    & npm run build
    Pop-Location
} else {
    Write-Host "==> Node not found — skipping web UI build (API + gateway still work)." -ForegroundColor Yellow
}

# 5. Wire up the AI tools already on this machine
if (-not $SkipTools) {
    Write-Host "`n==> AI tools found on this machine"
    & $vpy -m sensei.cli setup-tools --dry-run
    $answer = Read-Host "    Apply this configuration? [Y/n]"
    if ($answer -eq "" -or $answer -match '^[Yy]') {
        & $vpy -m sensei.cli setup-tools
    } else {
        Write-Host "    Skipped. Run '$vpy -m sensei.cli setup-tools' whenever you want."
    }
}

Write-Host "`n==> Sensei installed." -ForegroundColor Green
Write-Host "    Start it:  $vpy -m uvicorn sensei.main:app --app-dir backend --port 7000"
Write-Host "    Gateway :  point tools at http://localhost:7000/v1 (OpenAI) or http://localhost:7000 (Anthropic)"
Write-Host "    Savings :  http://localhost:7000/app/  ->  Tokens Saved"
Write-Host "    Undo    :  $vpy -m sensei.cli setup-tools --undo"

if ($Run) {
    Write-Host "`n==> Starting Sensei on http://localhost:7000" -ForegroundColor Cyan
    & $vpy -m uvicorn sensei.main:app --app-dir (Join-Path $root "backend") --port 7000
}
