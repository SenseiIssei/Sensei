"""Benchmark: rule-based TextCompressor vs the learned Sensei-Compressor.

Runs both over a held-out prose set (NOT the synthetic training sentences) and
reports token reduction + fidelity, so we can decide whether to route prose
through the learned model in production.

    PYTHONPATH=../../backend python bench_learned.py --config config.yaml
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from sensei.compression.textcomp import TextCompressor

_WORD_RE = re.compile(r"\w+|[^\w\s]")

# Held-out verbose prose (not the synthetic training distribution).
HELD_OUT = [
    "At the end of the day, it is important to note that the deployment pipeline, "
    "generally speaking, tends to fail intermittently when the cache happens to be cold.",
    "In order to improve the user experience, we are going to need to make sure that "
    "the dashboard loads in a timely manner for the vast majority of our users.",
    "Needless to say, the gateway is responsible for forwarding each and every one of "
    "the incoming requests to the appropriate upstream model provider.",
    "Due to the fact that errors are logged and then retried with backoff, the system "
    "is, for all intents and purposes, quite resilient to transient network failures.",
    "It should be pointed out that the configuration values are, in actual fact, read "
    "from the environment variables at the time when the server first starts up.",
    "The model basically scores each individual token by its relative importance, and "
    "then proceeds to drop the ones that are deemed to be the least useful overall.",
]


def _tokens(text: str) -> int:
    # tiktoken if available, else a chars/4 estimate (consistent across both sides).
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, len(text) // 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    from infer import LearnedTextCompressor

    rule = TextCompressor()
    learned = LearnedTextCompressor(
        model_dir=cfg["output_dir"],
        keep_threshold=float(cfg.get("keep_threshold", 0.5)),
        max_length=int(cfg.get("max_length", 256)),
    )

    o_tok = r_tok = l_tok = 0
    print("=" * 78)
    for text in HELD_OUT:
        r = rule.compress(text)
        l = learned.compress(text)
        ot, rt, lt = _tokens(text), _tokens(r), _tokens(l)
        o_tok += ot
        r_tok += rt
        l_tok += lt
        print(f"ORIG  ({ot:3d}t): {text}")
        print(f"RULE  ({rt:3d}t): {r}")
        print(f"LEARN ({lt:3d}t): {l}")
        print("-" * 78)

    print(f"\nTotal tokens — original {o_tok}, rule-based {r_tok}, learned {l_tok}")
    print(f"Rule-based reduction: {1 - r_tok / o_tok:.1%}")
    print(f"Learned   reduction: {1 - l_tok / o_tok:.1%}")


if __name__ == "__main__":
    main()
