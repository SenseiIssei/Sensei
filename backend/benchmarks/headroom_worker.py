"""Run Headroom on texts sent over stdin. Executed by Headroom's interpreter.

This file is started as ``<headroom-venv>/python -I headroom_worker.py`` by
``benchmarks.harness.HeadroomCompressor``. It imports nothing from Sensei, so
Headroom never becomes a dependency of this repository: it lives in a
throwaway virtualenv (see ``python -m benchmarks.headroom_env``).

Protocol: one JSON object on stdin —
``{"texts": [...], "repeats": 5, "model": "...", "protect_recent": 0}`` —
and one JSON object on stdout —
``{"version": "...", "results": [{"out": "...", "seconds": [...]}, ...]}``.

Each text is delivered the way Headroom's own proof-table harness delivers it:
as the ``tool`` message answering an assistant ``tool_call``, after a short
system and user message. ``protect_recent=0`` is the configuration Headroom
publishes its table with; under the default (4) a short conversation shields
almost every tool result and the measurement would be of the guard, not the
compressor. The timing covers ``compress()`` alone.
"""

from __future__ import annotations

import json
import sys
import time


def main() -> int:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    # Anything Headroom prints must not corrupt the JSON reply.
    reply = sys.stdout.buffer
    sys.stdout = sys.stderr
    from importlib.metadata import version

    from headroom import CompressConfig, compress

    model = req.get("model", "claude-sonnet-4-5-20250929")
    config = CompressConfig(protect_recent=int(req.get("protect_recent", 0)))
    repeats = max(1, int(req.get("repeats", 1)))

    def run(text: str) -> str:
        msgs = [
            {"role": "system", "content": "You are a coding agent."},
            {"role": "user", "content": "Look at the tool output and continue."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_0",
                        "type": "function",
                        "function": {"name": "tool", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_0", "content": text},
        ]
        result = compress(msgs, model=model, config=config)
        out = result.messages[-1].get("content")
        if isinstance(out, list):
            out = "".join(p.get("text", "") for p in out if isinstance(p, dict))
        return out if isinstance(out, str) else text

    # Warm-up: the first call loads detectors and tokenizers; it is not latency
    # a long-running proxy pays per request.
    if req["texts"]:
        run(req["texts"][0])

    results = []
    for text in req["texts"]:
        seconds = []
        out = text
        for _ in range(repeats):
            started = time.perf_counter()
            out = run(text)
            seconds.append(time.perf_counter() - started)
        results.append({"out": out, "seconds": seconds})

    payload = {"version": version("headroom-ai"), "results": results}
    reply.write(json.dumps(payload).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
