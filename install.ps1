# Sensei one-command installer (Windows / PowerShell)
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1 [-Run]
param([switch]$Run)

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

Write-Host "`n==> Sensei installed." -ForegroundColor Green
Write-Host "    Start it:  $vpy -m uvicorn sensei.main:app --app-dir backend --port 7000"
Write-Host "    Gateway :  point tools at http://localhost:7000/v1 (OpenAI) or http://localhost:7000 (Anthropic)"

if ($Run) {
    Write-Host "`n==> Starting Sensei on http://localhost:7000" -ForegroundColor Cyan
    & $vpy -m uvicorn sensei.main:app --app-dir (Join-Path $root "backend") --port 7000
}
