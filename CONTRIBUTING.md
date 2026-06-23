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

1. Fork the repo and create a feature branch
2. Write tests for new features
3. Ensure all tests pass (`pytest -v` for backend, `npx tsc --noEmit` for frontend)
4. Update documentation if needed
5. Open a PR with a clear description

## Areas That Need Help

- Compression algorithm improvements
- New model provider integrations
- UI/UX and accessibility
- Test coverage
- Documentation and translations

## Questions?

Open an issue or join the discussion on GitHub.
