"""Compress texts read as JSON lines on stdin; one JSON line out per text.

Used by ``SenseiCompressor(timeout=…)`` so a single pathological input — the
session replay found a 2 KB tool output that keeps the prose compressor busy for
over twenty minutes — is cut off, counted, and reported instead of stopping the
whole measurement. Each reply is flushed as soon as it exists, so the parent
knows exactly which input it was waiting on when it gave up.
"""

from __future__ import annotations

import json
import logging
import sys
import time


def main() -> int:
    # The warnings quote the payload they fire on; the payload may be a transcript.
    logging.getLogger("sensei").setLevel(logging.ERROR)
    from sensei.compression.router import ContentRouter

    router = ContentRouter(enable_caching=False)
    out = sys.stdout
    for line in sys.stdin:
        text = json.loads(line)
        started = time.perf_counter()
        compressed = router.compress(text, edit_target=True).compressed
        elapsed = time.perf_counter() - started
        out.write(json.dumps({"out": compressed, "seconds": elapsed}) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
