"""Representative compression benchmark for Sensei.

Measures REAL token savings (via tiktoken) across the kinds of content an AI
agent actually sees: JSON tool outputs, build/test logs, stack traces, source
code, and prose. Run:

    PYTHONPATH=backend python backend/benchmarks/compression_benchmark.py

Pass ``--json results.json`` for machine-readable output and ``--min-aggregate
60`` to exit non-zero when savings regress — that pair is what the nightly CI
guard runs.

The same corpus backs ``tests/test_aggregate_compression.py`` (which uses the
offline len//4 estimate so it can run without downloading a tokenizer).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sensei.compression.router import ContentRouter

# ─── Representative corpus ───────────────────────────────────────────────────


def _users_json() -> str:
    return json.dumps(
        [
            {
                "id": i,
                "name": f"User Number {i}",
                "email": f"user{i}@example.com",
                "role": "member",
                "active": True,
                "department": "engineering",
                "created_at": "2026-01-15T09:00:00Z",
                "metadata": None,
            }
            for i in range(20)
        ]
    )


def _search_json() -> str:
    return json.dumps(
        [
            {
                "file": f"src/module_{i}.py",
                "line": i * 3,
                "match": "def compress(",
                "type": "definition",
            }
            for i in range(15)
        ]
    )


def _build_log() -> str:
    lines = []
    for i in range(60):
        lines.append(f"2026-06-26 14:00:{i:02d} INFO  building module package_{i} ... ok")
    lines.append("2026-06-26 14:01:00 WARNING deprecated API used in legacy_adapter.py:42")
    lines.append("2026-06-26 14:01:01 ERROR  failed to link target 'app': undefined symbol `foo`")
    lines.append("2026-06-26 14:01:01 ERROR    referenced from main.o")
    for i in range(30):
        lines.append(f"2026-06-26 14:01:{i:02d} INFO  cleaning intermediate artifact tmp_{i}.o")
    lines.append("BUILD FAILED: 1 error, 1 warning in 61.2s")
    return "\n".join(lines)


def _stack_trace() -> str:
    head = ["2026-06-26 14:05:00 INFO starting request handler"] * 5
    trace = [
        "Traceback (most recent call last):",
        '  File "app/server.py", line 88, in handle',
        "    result = process(payload)",
        '  File "app/core.py", line 142, in process',
        "    return self._run(data)",
        'ValueError: invalid payload: missing field "id"',
    ]
    tail = ["2026-06-26 14:05:01 INFO request finished with status 500"] * 5
    return "\n".join(head + trace + tail)


def _code() -> str:
    return '''import os
import sys
import json
from typing import List, Dict


# Compute the running total of the values provided.
def total(values):
    """Return the sum of all values in the list."""
    # accumulate
    acc = 0
    for v in values:        # iterate
        acc += v            # add each value
    return acc


def main():
    # program entry point
    print(total([1, 2, 3]))   # should print 6


if __name__ == "__main__":
    main()
'''


def _prose() -> str:
    return (
        "Basically, in order to actually get started with the deployment, you will first "
        "need to make sure that you have, at the end of the day, installed all of the various "
        "different dependencies that are, in fact, required. It is very important to note that, "
        "generally speaking, the vast majority of the configuration is going to be handled "
        "automatically for you by the installer, so you do not really need to worry about it."
    )


CORPUS = {
    "json:users (20 records)": _users_json(),
    "json:search (15 hits)": _search_json(),
    "logs:build output": _build_log(),
    "logs:stack trace": _stack_trace(),
    "code:python": _code(),
    "prose:verbose doc": _prose(),
}


def measure() -> dict:
    """Run the corpus and return machine-readable results."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")

        def tok(s: str) -> int:
            return len(enc.encode(s))

        metric = "tiktoken/cl100k"
    except Exception:  # pragma: no cover - offline fallback

        def tok(s: str) -> int:
            return max(1, len(s) // 4)

        metric = "estimate (len//4)"

    router = ContentRouter(enable_caching=False)
    samples = []
    total_o = total_c = 0
    for name, content in CORPUS.items():
        result = router.compress(content)
        o, c = tok(content), tok(result.compressed)
        total_o += o
        total_c += c
        samples.append(
            {
                "name": name,
                "type": result.content_type.value,
                "original_tokens": o,
                "compressed_tokens": c,
                "saved_pct": round((1 - c / o) * 100, 2),
            }
        )
    return {
        "metric": metric,
        "samples": samples,
        "aggregate": {
            "original_tokens": total_o,
            "compressed_tokens": total_c,
            "saved_pct": round((1 - total_c / total_o) * 100, 2),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="also write machine-readable results here (use '-' for stdout)",
    )
    parser.add_argument(
        "--min-aggregate",
        type=float,
        default=None,
        metavar="PCT",
        help="exit non-zero if aggregate savings fall below this percentage",
    )
    args = parser.parse_args()

    data = measure()

    print(f"Token metric: {data['metric']}\n")
    print(f"{'sample':<28}{'type':>7}{'orig':>8}{'comp':>8}{'saved':>8}")
    print("-" * 59)
    for s in data["samples"]:
        print(
            f"{s['name']:<28}{s['type']:>7}{s['original_tokens']:>8}"
            f"{s['compressed_tokens']:>8}{s['saved_pct']:>7.0f}%"
        )
    agg = data["aggregate"]
    print("-" * 59)
    print(
        f"{'AGGREGATE':<28}{'':>7}{agg['original_tokens']:>8}"
        f"{agg['compressed_tokens']:>8}{agg['saved_pct']:>7.0f}%"
    )

    if args.json:
        payload = json.dumps(data, indent=2)
        if args.json == "-":
            print(payload)
        else:
            Path(args.json).write_text(payload, encoding="utf-8")
            print(f"\nWrote {args.json}")

    if args.min_aggregate is not None and agg["saved_pct"] < args.min_aggregate:
        print(
            f"\nFAIL: aggregate savings {agg['saved_pct']:.2f}% "
            f"is below the {args.min_aggregate:.2f}% floor",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
