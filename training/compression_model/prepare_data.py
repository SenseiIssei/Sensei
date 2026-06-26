"""Build a token-labeled dataset for the Sensei-Compressor.

Self-distillation: run Sensei's rule-based ``TextCompressor`` over (mostly
synthetic) verbose text and label each original word KEEP (1) if it survives in
the compressed output, DROP (0) otherwise. The token model then learns — and
generalizes — that behavior.

Run from this folder with the backend on the path::

    PYTHONPATH=../../backend python prepare_data.py --config config.yaml
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

import yaml

# Sensei's rule-based compressor is the teacher. Requires the backend on PYTHONPATH.
from sensei.compression.textcomp import TextCompressor

_WORD_RE = re.compile(r"\w+|[^\w\s]")

# Building blocks for synthetic verbose prose (filler the teacher will strip).
_FILLERS = [
    "basically", "actually", "really", "very", "quite", "in fact",
    "of course", "at the end of the day", "generally speaking",
    "it is important to note that", "needless to say",
]
_VERBOSE = [
    "in order to", "due to the fact that", "the vast majority of",
    "a large number of", "is going to", "make sure that", "all of the",
]
_CONTENT = [
    "the deployment fails when the cache is cold",
    "users expect the dashboard to load quickly",
    "the compressor routes each block to the right handler",
    "the gateway forwards the request to the upstream model",
    "errors are logged and retried with backoff",
    "the model scores each token by importance",
    "the configuration is read from environment variables",
    "the test suite must stay green before merging",
]


def _normalize(word: str) -> str:
    return word.lower()


def _label_words(original: str, compressed: str) -> tuple[list[str], list[int]]:
    """Label each word in `original` KEEP(1)/DROP(0) by survival in `compressed`."""
    orig_words = _WORD_RE.findall(original)
    kept = {}
    for w in _WORD_RE.findall(compressed):
        kept[_normalize(w)] = kept.get(_normalize(w), 0) + 1

    remaining = dict(kept)
    labels: list[int] = []
    for w in orig_words:
        key = _normalize(w)
        if remaining.get(key, 0) > 0:
            remaining[key] -= 1
            labels.append(1)
        else:
            labels.append(0)
    return orig_words, labels


def _synth_sentence(rng: random.Random) -> str:
    parts: list[str] = []
    if rng.random() < 0.8:
        parts.append(rng.choice(_FILLERS).capitalize() + ",")
    parts.append(rng.choice(_VERBOSE))
    parts.append(rng.choice(_CONTENT))
    if rng.random() < 0.5:
        parts.append("and " + rng.choice(_VERBOSE) + " " + rng.choice(_CONTENT))
    return " ".join(parts).strip() + "."


def _iter_inputs(input_dir: str):
    if not input_dir:
        return
    for path in Path(input_dir).rglob("*"):
        if path.suffix.lower() in {".txt", ".md"} and path.is_file():
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if len(line) > 40:
                        yield line
            except OSError:
                continue


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    rng = random.Random(cfg.get("seed", 42))
    comp = TextCompressor()
    out_path = Path(cfg["data_path"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    samples: list[str] = [_synth_sentence(rng) for _ in range(int(cfg["num_synthetic"]))]
    samples.extend(_iter_inputs(cfg.get("input_dir", "")))

    written = kept = total = 0
    with out_path.open("w", encoding="utf-8") as f:
        for text in samples:
            words, labels = _label_words(text, comp.compress(text))
            if not words or all(labels):
                continue  # nothing to learn from
            f.write(json.dumps({"tokens": words, "labels": labels}) + "\n")
            written += 1
            kept += sum(labels)
            total += len(labels)

    drop_rate = 1 - (kept / total) if total else 0
    print(f"Wrote {written} labeled examples to {out_path}")
    print(f"Average drop rate (teacher): {drop_rate:.1%}")


if __name__ == "__main__":
    main()
