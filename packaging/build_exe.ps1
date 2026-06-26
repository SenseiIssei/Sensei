# Build sensei.exe (Windows). Requires the backend venv (run install.ps1 first).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$vpy = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { throw "Run install.ps1 first (backend venv missing)." }

Write-Host "==> Installing PyInstaller"
& $vpy -m pip install -q pyinstaller

if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host "==> Building web UI to bundle into the exe"
    Push-Location (Join-Path $root "frontend")
    & npm install --no-audit --no-fund --loglevel=error
    & npm run build
    Pop-Location
}

Write-Host "==> Building sensei.exe"
& $vpy -m PyInstaller (Join-Path $root "packaging\sensei.spec") --noconfirm --distpath (Join-Path $root "dist")
Write-Host "==> Done: $(Join-Path $root 'dist\sensei.exe')" -ForegroundColor Green
