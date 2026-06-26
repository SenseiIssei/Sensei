#!/bin/bash
# Build a standalone Sensei binary (Linux / macOS). Mirrors build_exe.ps1.
# Requires the backend venv (run ./install.sh or python install.py first).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VPY="$ROOT/backend/.venv/bin/python"
[ -x "$VPY" ] || { echo "Backend venv missing — run ./install.sh first."; exit 1; }

echo "==> Installing PyInstaller"
"$VPY" -m pip install -q pyinstaller

if command -v node >/dev/null 2>&1; then
  echo "==> Building web UI to bundle"
  (cd "$ROOT/frontend" && npm install --no-audit --no-fund --loglevel=error && npm run build)
fi

echo "==> Building sensei binary"
"$VPY" -m PyInstaller "$ROOT/packaging/sensei.spec" --noconfirm --distpath "$ROOT/dist"
echo "==> Done: $ROOT/dist/sensei"
