#!/usr/bin/env python3
"""
Sensei Installer — Auto-setup everything in one command.

Usage:
    python install.py        # Interactive setup
    python install.py --docker  # Docker-based setup

What it does:
    1. Checks prerequisites (Python, Node.js, Docker)
    2. Installs backend dependencies
    3. Installs frontend dependencies
    4. Lets you pick which AI model providers to use
    5. Lets you enter API keys interactively
    6. Generates .env file with your configuration
    7. Optionally downloads Ollama models
    8. Runs tests to verify everything works
    9. Starts the server

Works on: Linux, macOS, Windows
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ─── ANSI Colors ──────────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
if IS_WIN:
    os.system("")  # Enable ANSI on Windows

C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[92m",
    "blue": "\033[94m",
    "cyan": "\033[96m",
    "yellow": "\033[93m",
    "red": "\033[91m",
    "magenta": "\033[95m",
    "bg_blue": "\033[44m",
    "bg_green": "\033[42m",
}


def c(text: str, color: str) -> str:
    return f"{C[color]}{text}{C['reset']}"


# ─── Providers ────────────────────────────────────────────────
PROVIDERS = [
    {
        "id": "ollama",
        "name": "Ollama (Local, Free, No API Key)",
        "env_key": "",
        "env_model": "SENSEI_OLLAMA_MODEL",
        "default_model": "glm-5.2",
        "signup_url": "https://ollama.com",
        "free": True,
        "premium": False,
    },
    {
        "id": "openrouter",
        "name": "OpenRouter (Access ALL models, Free tier)",
        "env_key": "SENSEI_OPENROUTER_API_KEY",
        "env_model": "SENSEI_OPENROUTER_API_MODEL",
        "default_model": "zhipuai/glm-5.2",
        "signup_url": "https://openrouter.ai/keys",
        "free": True,
        "premium": False,
    },
    {
        "id": "groq",
        "name": "Groq (Ultra-fast, Free tier, Llama 3.3)",
        "env_key": "SENSEI_GROQ_API_KEY",
        "env_model": "SENSEI_GROQ_API_MODEL",
        "default_model": "llama-3.3-70b-versatile",
        "signup_url": "https://console.groq.com/keys",
        "free": True,
        "premium": False,
    },
    {
        "id": "openai",
        "name": "OpenAI (GPT-4o, o1, o3)",
        "env_key": "SENSEI_OPENAI_API_KEY",
        "env_model": "SENSEI_OPENAI_API_MODEL",
        "default_model": "gpt-4o",
        "signup_url": "https://platform.openai.com/api-keys",
        "free": False,
        "premium": True,
    },
    {
        "id": "anthropic",
        "name": "Anthropic / Claude (Claude 3.5 Sonnet, Opus)",
        "env_key": "SENSEI_ANTHROPIC_API_KEY",
        "env_model": "SENSEI_ANTHROPIC_API_MODEL",
        "default_model": "claude-3-5-sonnet-20241022",
        "signup_url": "https://console.anthropic.com/settings/keys",
        "free": False,
        "premium": True,
    },
    {
        "id": "google",
        "name": "Google Gemini (Gemini 2.0 Flash, Pro)",
        "env_key": "SENSEI_GOOGLE_API_KEY",
        "env_model": "SENSEI_GOOGLE_API_MODEL",
        "default_model": "gemini-2.0-flash",
        "signup_url": "https://aistudio.google.com/apikey",
        "free": True,
        "premium": True,
    },
    {
        "id": "deepseek",
        "name": "DeepSeek (DeepSeek V3, R1 — cheap & powerful)",
        "env_key": "SENSEI_DEEPSEEK_API_KEY",
        "env_model": "SENSEI_DEEPSEEK_API_MODEL",
        "default_model": "deepseek-chat",
        "signup_url": "https://platform.deepseek.com/api_keys",
        "free": False,
        "premium": True,
    },
    {
        "id": "mistral",
        "name": "Mistral (Mistral Large, Codestral)",
        "env_key": "SENSEI_MISTRAL_API_KEY",
        "env_model": "SENSEI_MISTRAL_API_MODEL",
        "default_model": "mistral-large-latest",
        "signup_url": "https://console.mistral.ai/api-keys",
        "free": False,
        "premium": True,
    },
    {
        "id": "together",
        "name": "Together AI (Llama, Qwen, DeepSeek)",
        "env_key": "SENSEI_TOGETHER_API_KEY",
        "env_model": "SENSEI_TOGETHER_API_MODEL",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "signup_url": "https://api.together.xyz/settings/api-keys",
        "free": False,
        "premium": True,
    },
    {
        "id": "huggingface",
        "name": "HuggingFace (GLM-5.2, thousands of models)",
        "env_key": "SENSEI_HUGGINGFACE_API_KEY",
        "env_model": "SENSEI_HUGGINGFACE_API_MODEL",
        "default_model": "THUDM/glm-5.2-744b",
        "signup_url": "https://huggingface.co/settings/tokens",
        "free": True,
        "premium": False,
    },
    {
        "id": "zai",
        "name": "Z.ai (Original GLM-5.2 provider)",
        "env_key": "SENSEI_ZAI_API_KEY",
        "env_model": "SENSEI_ZAI_API_MODEL",
        "default_model": "glm-5.2",
        "signup_url": "https://open.bigmodel.cn",
        "free": False,
        "premium": False,
    },
    {
        "id": "cohere",
        "name": "Cohere (Command R+)",
        "env_key": "SENSEI_COHERE_API_KEY",
        "env_model": "SENSEI_COHERE_API_MODEL",
        "default_model": "command-r-plus",
        "signup_url": "https://dashboard.cohere.com/api-keys",
        "free": False,
        "premium": True,
    },
    {
        "id": "fireworks",
        "name": "Fireworks AI (Llama, Qwen, fast inference)",
        "env_key": "SENSEI_FIREWORKS_API_KEY",
        "env_model": "SENSEI_FIREWORKS_API_MODEL",
        "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "signup_url": "https://fireworks.ai/apikeys",
        "free": False,
        "premium": True,
    },
    {
        "id": "perplexity",
        "name": "Perplexity (Sonar, Online search-augmented)",
        "env_key": "SENSEI_PERPLEXITY_API_KEY",
        "env_model": "SENSEI_PERPLEXITY_API_MODEL",
        "default_model": "sonar-pro",
        "signup_url": "https://www.perplexity.ai/settings/api",
        "free": False,
        "premium": True,
    },
]


# ─── Helpers ──────────────────────────────────────────────────
def banner() -> None:
    print()
    print(c("  ╔══════════════════════════════════════════════════╗", "cyan"))
    print(c("  ║                                                  ║", "cyan"))
    print(c("  ║         ", "cyan") + c("Sensei", "bold") + c("                       ║", "cyan"))
    print(c("  ║         ", "cyan") + c("compress · dream · retrieve · repeat", "dim") + c("    ║", "cyan"))
    print(c("  ║                                                  ║", "cyan"))
    print(c("  ╚══════════════════════════════════════════════════╝", "cyan"))
    print()
    print(c("  Self-hosted AI workspace with token compression", "dim"))
    print(c("  14+ model providers · Free & Open Source · MIT", "dim"))
    print()


def step(num: int, title: str) -> None:
    print()
    print(c(f"  ┌─ Step {num} ─────────────────────────────────────", "blue"))
    print(c(f"  │ {title}", "bold"))
    print(c(f"  └─────────────────────────────────────────────────", "blue"))


def ok(msg: str) -> None:
    print(f"  {c('✓', 'green')} {msg}")


def warn(msg: str) -> None:
    print(f"  {c('⚠', 'yellow')} {msg}")


def err(msg: str) -> None:
    print(f"  {c('✗', 'red')} {msg}")


def info(msg: str) -> None:
    print(f"  {c('→', 'cyan')} {msg}")


def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> int:
    try:
        result = subprocess.run(cmd, cwd=cwd, check=check, shell=IS_WIN and len(cmd) == 1)
        return result.returncode
    except subprocess.CalledProcessError as e:
        if check:
            err(f"Command failed: {' '.join(cmd)}")
        return e.returncode
    except FileNotFoundError:
        err(f"Command not found: {cmd[0]}")
        return 1


def check_cmd(name: str, install_hint: str) -> bool:
    found = shutil.which(name) is not None
    if found:
        ok(f"{name} found")
    else:
        warn(f"{name} not found")
        info(f"Install: {install_hint}")
    return found


def prompt(msg: str, default: str = "") -> str:
    suffix = f" [{c(default, 'dim')}]" if default else ""
    val = input(f"  {c('?', 'magenta')} {msg}{suffix}: ").strip()
    return val or default


def prompt_yesno(msg: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    val = input(f"  {c('?', 'magenta')} {msg} [{c(hint, 'dim')}]: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


# ─── Main ─────────────────────────────────────────────────────
def main() -> None:
    banner()

    root = Path(__file__).parent.resolve()
    backend_dir = root / "backend"
    frontend_dir = root / "frontend"
    env_file = root / ".env"

    use_docker = "--docker" in sys.argv

    # ── Step 1: Check prerequisites ──
    step(1, "Checking prerequisites")

    has_python = check_cmd("python", "https://python.org/downloads")
    has_node = check_cmd("node", "https://nodejs.org")
    has_npm = check_cmd("npm", "https://nodejs.org")
    has_docker = check_cmd("docker", "https://docker.com")
    has_pip = check_cmd("pip", "pip install pip")
    has_ollama = check_cmd("ollama", "https://ollama.com")

    if use_docker:
        if not has_docker:
            err("Docker is required for --docker mode")
            sys.exit(1)
        ok("Docker mode selected")
    else:
        if not has_python:
            err("Python 3.11+ is required")
            info("Install from: https://python.org/downloads")
            sys.exit(1)
        if not has_node:
            warn("Node.js not found — frontend will not be available")
            warn("Install from: https://nodejs.org")

    # ── Step 2: Install dependencies ──
    step(2, "Installing dependencies")

    if use_docker:
        info("Docker mode — dependencies installed inside containers")
    else:
        if has_pip:
            info("Installing backend dependencies...")
            run([sys.executable, "-m", "pip", "install", "-e", ".[dev]", "--quiet"], cwd=str(backend_dir))
            ok("Backend dependencies installed")

        if has_npm:
            info("Installing frontend dependencies...")
            run(["npm", "install", "--silent"], cwd=str(frontend_dir))
            ok("Frontend dependencies installed")

    # ── Step 3: Choose model providers ──
    step(3, "Choose your AI model providers")

    print()
    print(c("  Available providers:", "bold"))
    print()

    for i, p in enumerate(PROVIDERS, 1):
        tags = []
        if p["free"]:
            tags.append(c("FREE", "green"))
        if p["premium"]:
            tags.append(c("PREMIUM", "magenta"))
        if not p["free"] and not p["premium"]:
            tags.append(c("PAID", "yellow"))
        tag_str = f" {' '.join(tags)}" if tags else ""
        print(f"  {c(str(i).rjust(2), 'dim')}. {c(p['name'], 'bold')}{tag_str}")

    print()
    print(c("  Tip: You can select multiple (comma-separated, e.g. 1,2,4)", "dim"))
    print(c("  Tip: Free providers work without payment — great for getting started!", "dim"))
    print()

    selection = prompt("Select providers (numbers)", "1,2")
    selected_indices = []
    for part in selection.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(PROVIDERS):
                selected_indices.append(idx)

    if not selected_indices:
        warn("No valid selection — defaulting to Ollama + OpenRouter")
        selected_indices = [0, 1]

    selected_providers = [PROVIDERS[i] for i in selected_indices]
    ok(f"Selected {len(selected_providers)} provider(s)")

    # ── Step 4: Enter API keys ──
    step(4, "Configure API keys")

    env_lines = []
    env_lines.append("# Sensei Configuration — Generated by installer")
    env_lines.append("# Edit this file anytime to change settings")
    env_lines.append("")

    # Provider selection
    first_provider = selected_providers[0]
    env_lines.append("# ── Model Provider ──────────────────────────────────────────")
    if first_provider["id"] == "ollama":
        env_lines.append("SENSEI_MODEL_PROVIDER=auto")
    else:
        env_lines.append("SENSEI_MODEL_PROVIDER=api")
    env_lines.append(f"SENSEI_API_PROVIDER={first_provider['id']}")
    env_lines.append("")

    # Ollama config
    env_lines.append("# ── Ollama ────────────────────────────────────────────────")
    env_lines.append("SENSEI_OLLAMA_HOST=http://localhost:11434")
    ollama_model = "glm-5.2"
    for p in selected_providers:
        if p["id"] == "ollama":
            ollama_model = prompt("Ollama model to use", p["default_model"])
    env_lines.append(f"SENSEI_OLLAMA_MODEL={ollama_model}")
    env_lines.append("")

    # Local model config
    env_lines.append("# ── Local Model ────────────────────────────────────────────")
    env_lines.append("SENSEI_LOCAL_MODEL_PATH=")
    env_lines.append("SENSEI_LOCAL_BACKEND=ollama")
    env_lines.append("SENSEI_LOCAL_GPU_LAYERS=0")
    env_lines.append("SENSEI_LOCAL_CONTEXT_SIZE=32768")
    env_lines.append("SENSEI_LOCAL_PORT=8080")
    env_lines.append("")

    # API keys for selected providers
    any_key_set = False
    for p in selected_providers:
        if p["id"] == "ollama":
            continue

        print()
        section = f"Configure {p['name']}"
        print(c(f"  ┌─ {section} ──", "blue"))
        print(c(f"  │ Sign up: {p['signup_url']}", "dim"))

        if p["env_key"]:
            key = input(f"  {c('?', 'magenta')} API key (press Enter to skip): ").strip()
            if key:
                any_key_set = True
                ok(f"Key set for {p['id']}")
            else:
                warn(f"Skipped — you can add it later in .env")

            model = prompt("Model name", p["default_model"])

            env_lines.append(f"# ── {p['name']} ─")
            env_lines.append(f"{p['env_key']}={key}")
            env_lines.append(f"{p['env_model']}={model}")
            env_lines.append("")

        print(c("  └──────────────────", "blue"))

    # Compression
    env_lines.append("# ── Compression ────────────────────────────────────────────")
    env_lines.append("SENSEI_COMPRESSION_ENABLED=true")
    env_lines.append("SENSEI_CCR_TTL_HOURS=24")
    env_lines.append("SENSEI_CCR_CACHE_DIR=.sensei_cache")
    env_lines.append("")

    # Memory
    env_lines.append("# ── Memory ──────────────────────────────────────────────────")
    env_lines.append("SENSEI_MEMORY_ENABLED=true")
    env_lines.append("SENSEI_MEMORY_DIR=.sensei_memory")
    env_lines.append("")

    # Server
    env_lines.append("# ── Server ──────────────────────────────────────────────────")
    env_lines.append("SENSEI_HOST=0.0.0.0")
    port = prompt("Backend port", "7000")
    env_lines.append(f"SENSEI_PORT={port}")
    env_lines.append("SENSEI_CORS_ORIGINS=http://localhost:5173,http://localhost:7000")
    env_lines.append("")

    # Security
    env_lines.append("# ── Security ────────────────────────────────────────────────")
    enable_auth = prompt_yesno("Enable auth token?", False)
    env_lines.append(f"SENSEI_AUTH_ENABLED={'true' if enable_auth else 'false'}")
    if enable_auth:
        import secrets
        auto_token = secrets.token_urlsafe(32)
        auth_token = prompt("Auth token (blank = auto-generate)", "")
        if not auth_token:
            auth_token = auto_token
            info(f"Auto-generated token: {c(auth_token, 'green')}")
        env_lines.append(f"SENSEI_AUTH_TOKEN={auth_token}")
    else:
        env_lines.append("SENSEI_AUTH_TOKEN=")
    env_lines.append("SENSEI_RATE_LIMIT_ENABLED=true")
    env_lines.append("SENSEI_RATE_LIMIT_REQUESTS=60")
    env_lines.append("SENSEI_RATE_LIMIT_WINDOW_SECONDS=60")
    env_lines.append("SENSEI_MAX_MESSAGE_LENGTH=32768")
    env_lines.append("SENSEI_DATA_ENCRYPTION_ENABLED=true")
    env_lines.append("")

    # Sessions
    env_lines.append("# ── Sessions ────────────────────────────────────────────────")
    env_lines.append("SENSEI_SESSION_TIMEOUT_MINUTES=60")
    env_lines.append("SENSEI_SESSION_DIR=.sensei_sessions")
    env_lines.append("")

    # Write .env
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    ok(f"Configuration saved to {c(str(env_file), 'green')}")

    # ── Step 5: Ollama model pull ──
    if has_ollama and any(p["id"] == "ollama" for p in selected_providers):
        step(5, "Pulling Ollama model")
        pull_model = prompt(f"Pull Ollama model", ollama_model)
        if prompt_yesno(f"Pull '{pull_model}' now?", True):
            info(f"Pulling {pull_model}... (this may take a while)")
            run(["ollama", "pull", pull_model])
            ok(f"Model {pull_model} pulled")
        else:
            warn(f"Skipped — run 'ollama pull {pull_model}' later")
    else:
        if not has_ollama and any(p["id"] == "ollama" for p in selected_providers):
            step(5, "Ollama setup")
            warn("Ollama not installed")
            info("Install from: https://ollama.com")
            info(f"After install, run: ollama pull {ollama_model}")

    # ── Step 6: Run tests ──
    if not use_docker and has_python:
        step(6, "Running tests")
        if prompt_yesno("Run test suite now?", True):
            info("Running pytest...")
            code = run([sys.executable, "-m", "pytest", "-v", "--tb=short"], cwd=str(backend_dir), check=False)
            if code == 0:
                ok("All tests passed!")
            else:
                warn("Some tests failed — check output above")
        else:
            warn("Tests skipped")

    # ── Step 7: Start ──
    step(7, "Ready to launch!")

    print()
    print(c("  ╔══════════════════════════════════════════════════╗", "green"))
    print(c("  ║                                                  ║", "green"))
    print(c("  ║         ", "green") + c("Setup Complete!", "bold") + c("                   ║", "green"))
    print(c("  ║                                                  ║", "green"))
    print(c("  ╚══════════════════════════════════════════════════╝", "green"))
    print()

    if use_docker:
        info("Start Sensei:")
        print(c("    docker compose up -d", "cyan"))
        print()
        info("With Ollama:")
        print(c("    docker compose --profile ollama up -d", "cyan"))
        print()
        info("Frontend: http://localhost:5173")
        info(f"Backend:  http://localhost:{port}")
        info("API docs: http://localhost:7000/docs")
    else:
        info("Start backend:")
        print(c("    cd backend && uvicorn sensei.main:app --reload --port " + str(port), "cyan"))
        if has_npm:
            print()
            info("Start frontend (new terminal):")
            print(c("    cd frontend && npm run dev", "cyan"))
        print()
        info("Or start CLI:")
        print(c("    cd backend && python -m sensei.cli", "cyan"))
        print()
        info("Or start Qt GUI:")
        print(c("    cd backend && python -m sensei.gui", "cyan"))
        print()
        info("Frontend: http://localhost:5173")
        info(f"Backend:  http://localhost:{port}")
        info("API docs: http://localhost:7000/docs")

    print()
    info(c("Edit .env anytime to change providers or keys", "dim"))
    info(c("Support the project: https://ko-fi.com/senseiissei", "dim"))
    print()

    if prompt_yesno("Start Sensei now?", True):
        if use_docker:
            run(["docker", "compose", "up", "-d"], cwd=str(root))
        else:
            info("Starting backend... (Ctrl+C to stop)")
            run([sys.executable, "-m", "uvicorn", "sensei.main:app",
                 "--host", "0.0.0.0", "--port", str(port)],
                cwd=str(backend_dir), check=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        warn("Setup cancelled")
        sys.exit(0)
