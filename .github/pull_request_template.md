<!-- Thanks for contributing to Sensei. Keep this short — CI checks the rest. -->

## What changed

<!-- One or two sentences. What does this do that main doesn't? -->

## Why

<!-- The problem, not the patch. Link an issue if there is one: Fixes #123 -->

## How it was verified

<!-- Delete what doesn't apply. "CI is green" alone is fine for small changes. -->

- [ ] `pytest -q` passes locally
- [ ] `ruff check . && ruff format --check .` clean
- [ ] Frontend: `npm run typecheck && npm run test && npm run build`
- [ ] Tried it by hand — describe what you did:

## Compression changes only

<!-- Delete this section if you didn't touch backend/sensei/compression or rust/ -->

- [ ] `python backend/benchmarks/compression_benchmark.py` — aggregate savings before/after:
- [ ] The Rust path still matches the Python path byte-for-byte

## Anything reviewers should push back on

<!-- Tradeoffs you weren't sure about, or things you'd like a second opinion on. -->
