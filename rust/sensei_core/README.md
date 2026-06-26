# sensei_core — Rust accelerator

Optional low-level Rust hot paths for Sensei's compression, exposed to Python via
[PyO3](https://pyo3.rs) / [maturin](https://www.maturin.rs). Sensei **soft-imports**
this module: when it's built, the hot path runs in Rust; otherwise pure Python is
used. Output is **byte-for-byte identical** (verified against the Python impl), so
behavior never changes — only speed.

## Status

- [x] `csv_schema(json_str) -> str | None` — JSON dict-array → CSV-schema table
      (the biggest compression hot path). ~2× faster than Python on a 200-row
      table; gap widens with size. Byte-parity verified in CI samples.
- [ ] `compress_code` / `compress_logs` / `compress_text` — port the remaining
      compressors (regex-heavy → ideal for Rust).
- [ ] streaming tokenizer + KV-cache prefix hashing.
- [ ] zero-copy CCR store.

## Build

```bash
pip install maturin
cd rust/sensei_core
maturin develop --release        # builds + installs into the active venv
```

(On Windows, set `VIRTUAL_ENV` to the venv if it isn't auto-detected.) Sensei
works without this step — it's a pure accelerator.

## Why Rust here

The compressors are tight loops over many JSON rows / log lines / code tokens —
exactly where Python's per-object overhead hurts and Rust shines. Keeping the
crate optional and byte-compatible means we get the speed without locking anyone
out of a pure-Python install.
