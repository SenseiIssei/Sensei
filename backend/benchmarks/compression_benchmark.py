"""Representative compression benchmark for Sensei.

Measures REAL token savings (via tiktoken) across the kinds of content an AI
agent actually sees: JSON tool outputs, build/test logs, stack traces, source
code, and prose. Run:

    PYTHONPATH=backend python backend/benchmarks/compression_benchmark.py

The same corpus backs ``tests/test_aggregate_compression.py`` (which uses the
offline len//4 estimate so it can run without downloading a tokenizer).
"""
from __future__ import annotations

import json

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
            {"file": f"src/module_{i}.py", "line": i * 3, "match": "def compress(", "type": "definition"}
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
        'Traceback (most recent call last):',
        '  File "app/server.py", line 88, in handle',
        '    result = process(payload)',
        '  File "app/core.py", line 142, in process',
        '    return self._run(data)',
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


def main() -> None:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        tok = lambda s: len(enc.encode(s))  # noqa: E731
        metric = "tiktoken/cl100k"
    except Exception:  # pragma: no cover - offline fallback
        tok = lambda s: max(1, len(s) // 4)  # noqa: E731
        metric = "estimate (len//4)"

    router = ContentRouter(enable_caching=False)
    print(f"Token metric: {metric}\n")
    print(f"{'sample':<28}{'type':>7}{'orig':>8}{'comp':>8}{'saved':>8}")
    print("-" * 59)
    total_o = total_c = 0
    for name, content in CORPUS.items():
        result = router.compress(content)
        o, c = tok(content), tok(result.compressed)
        total_o += o
        total_c += c
        print(f"{name:<28}{result.content_type.value:>7}{o:>8}{c:>8}{(1 - c / o) * 100:>7.0f}%")
    print("-" * 59)
    print(f"{'AGGREGATE':<28}{'':>7}{total_o:>8}{total_c:>8}{(1 - total_c / total_o) * 100:>7.0f}%")


if __name__ == "__main__":
    main()
