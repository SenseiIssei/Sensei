# Contributing to Sensei

Thank you for your interest in contributing to Sensei! This is a community-driven project.

## Development Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- Git

### Backend
```bash
cd backend
pip install -e ".[dev]"
pytest -v  # run tests
ruff check sensei/  # lint
```

### Frontend
```bash
cd frontend
npm install
npm run dev      # dev server
npx tsc --noEmit # type check
npx vite build   # production build
```

## Code Style

- **Python**: ruff for linting, line length 100, target Python 3.11+
- **TypeScript**: Strict mode, no implicit any
- **Commits**: Conventional format — `feat:`, `fix:`, `docs:`, `test:`, `refactor:`

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
