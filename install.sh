#!/bin/bash
# Sensei Quick Installer for Linux/macOS
# Run: curl -fsSL https://raw.githubusercontent.com/SenseiIssei/Sensei/main/install.sh | bash
# Or:  git clone https://github.com/SenseiIssei/Sensei.git && cd Sensei && bash install.sh

set -e

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║                  Sensei                          ║"
echo "  ║    compress · dream · retrieve · repeat          ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[92m'
BLUE='\033[94m'
CYAN='\033[96m'
YELLOW='\033[93m'
RED='\033[91m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

ok() { echo -e "  ${GREEN}✓${RESET} $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET} $1"; }
err() { echo -e "  ${RED}✗${RESET} $1"; }
info() { echo -e "  ${CYAN}→${RESET} $1"; }

# Check if running from curl (not cloned yet)
if [ ! -f "install.py" ]; then
    info "Cloning Sensei repository..."
    git clone https://github.com/SenseiIssei/Sensei.git
    cd Sensei
fi

# Check Python
if command -v python3 &>/dev/null; then
    PY=python3
    ok "Python3 found"
elif command -v python &>/dev/null; then
    PY=python
    ok "Python found"
else
    err "Python 3.11+ is required"
    info "Install: https://python.org/downloads"
    info "Or on Ubuntu/Debian: sudo apt install python3 python3-pip"
    info "Or on macOS: brew install python"
    exit 1
fi

# Check Node
if command -v node &>/dev/null; then
    ok "Node.js found"
else
    warn "Node.js not found (frontend won't be available)"
    info "Install: https://nodejs.org or: brew install node"
fi

# Check Docker
if command -v docker &>/dev/null; then
    ok "Docker found"
    echo ""
    echo -e "  ${BOLD}Run with Docker?${RESET}"
    echo -e "    ${CYAN}docker compose up -d${RESET}"
    echo ""
fi

# Check Ollama
if command -v ollama &>/dev/null; then
    ok "Ollama found"
else
    warn "Ollama not found (optional — for free local models)"
    info "Install: https://ollama.com"
fi

echo ""
echo -e "  ${BOLD}Starting interactive installer...${RESET}"
echo ""

# Run the Python installer
exec $PY install.py "$@"
