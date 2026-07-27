# Contributing to Sensei

Thank you for your interest in contributing to Sensei! This is a community-driven project.

## Development Setup

### Prerequisites
- Python 3.11, 3.12 or 3.13 (CI tests all three on Linux, macOS and Windows)
- Node.js 24+
- Rust stable (only if you touch the optional accelerator)
- Git

### Get the pre-commit hooks first

They run the same lint and format checks CI does, so you find out in one second
instead of after a push.

```bash
pip install pre-commit && pre-commit install
```

### Backend
```bash
cd backend
pip install -e ".[dev]"
pytest -q                      # run tests
ruff check .                   # lint (CI blocks on this)
ruff format --check .          # formatting (CI blocks on this too)
```

### Frontend
```bash
cd frontend
npm ci
npm run dev            # dev server
npm run typecheck      # tsc --noEmit
npm run test           # vitest
npm run test:e2e       # playwright (no backend needed — it mocks)
npm run build          # production build
```

### Rust accelerator (optional)
```bash
cd rust/sensei_core
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo build --release

# Build and install the wheel, then re-run the backend suite to prove the
# Rust path is byte-identical to the Python one. CI does exactly this.
pip install "maturin>=1.9,<2"
maturin build --release --out dist && pip install dist/*.whl
(cd ../../backend && pytest -q)
```

### VS Code extension
```bash
cd extensions/vscode
npm ci
npm run compile        # typecheck + esbuild bundle
npm run package        # -> sensei-tokens-<version>.vsix
```

## Code Style

- **Python**: ruff, line length 100, target 3.11+. The lint rule set is pinned
  explicitly in `backend/pyproject.toml` — if a rule fights the architecture
  (lazy optional imports, deliberate broad excepts), it's ignored there with a
  written reason rather than sprinkled `# noqa` everywhere.
- **TypeScript**: strict mode, no implicit any.
- **Rust**: `cargo fmt`, and clippy is `-D warnings`.
- **Commits**: Conventional format — `feat:`, `fix:`, `perf:`, `deps:`, `docs:`,
  `test:`, `refactor:`, `ci:`, `chore:`. This is not cosmetic: release-please
  builds `CHANGELOG.md` and picks the next version number from these prefixes.
  Use `feat!:` or a `BREAKING CHANGE:` footer for anything breaking.

## Changing the compression pipeline

This is the part of Sensei that people install it for, so it has an extra bar:

```bash
python backend/benchmarks/compression_benchmark.py
```

Report the aggregate before and after in your PR. Nightly CI fails if aggregate
savings drop below 75%, and it separately asserts that the Rust and Python
paths produce identical output.

## Pull Request Process

1. Fork the repo and create a feature branch (`git checkout -b feat/my-feature`)
2. Write tests for new features
3. Ensure all tests pass (`pytest -v` for backend, `npx tsc --noEmit` for frontend)
4. Update documentation if needed
5. Open a PR with a clear description
6. **Direct commits to `main` are blocked** — all changes go through PR review
7. At least 1 approving review is required before merge
8. Linear history is enforced (no merge commits, rebase instead)

### Branch Protection Rules

- `main` branch is protected — no direct pushes
- Force pushes are blocked
- Branch deletion is blocked
- PR requires 1 approving review
- Stale reviews are dismissed on new commits

### How to Contribute

```bash
# Fork on GitHub, then:
git clone https://github.com/YOUR_USERNAME/Sensei.git
cd Sensei
git checkout -b feat/your-feature

# Make changes, commit
git add -A
git commit -m "feat: add your feature"

# Push and open PR
git push origin feat/your-feature
# Then open a PR on GitHub targeting main
```

## Areas That Need Help

- **Compression algorithms** — Better heuristics for code, JSON, prose
- **Model provider integrations** — New providers, better error handling
- **UI/UX** — Frontend improvements, accessibility, mobile, Claude-like client
- **Training** — Sensei-1 model fine-tuning, data collection, evaluation
- **Multi-channel** — Discord/Telegram/Slack bot integrations (OpenClaw-style)
- **Security** — AES-256 encryption, audit logging, SSO, RBAC
- **Testing** — More test coverage, E2E tests, performance benchmarks
- **Documentation** — Tutorials, guides, API docs, translations

## Sensei-1 Model Training

Interested in helping train Sensei-1? See `training/README.md` for the full pipeline.

- Contribute training data (opt-in, anonymized)
- Help with LoRA/QLoRA training configs
- Run evaluations on different hardware
- Contribute quantized model variants

## Questions?

Open an issue or join the discussion on GitHub.
Add me on Discord: **senseiissei**
