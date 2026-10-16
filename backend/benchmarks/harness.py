"""Shared measurement plumbing: one tokenizer, one denominator, two compressors.

A head-to-head is only honest if both sides are counted the same way. Every
number this package produces goes through ``Tokenizer.count`` on the text the
model would actually receive — Sensei's output, Headroom's output, or the
untouched original — never through either tool's own token estimate.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


class Tokenizer:
    """tiktoken when it is available, len//4 otherwise — and says which."""

    def __init__(self, encoding: str = "cl100k_base") -> None:
        try:
            import tiktoken

            enc = tiktoken.get_encoding(encoding)
            self._count = lambda s: len(enc.encode(s, disallowed_special=()))
            self.name = f"tiktoken/{encoding}"
        except Exception:  # pragma: no cover - offline fallback
            self._count = lambda s: max(1, len(s) // 4) if s else 0
            self.name = "estimate (len//4)"

    def count(self, text: str) -> int:
        return self._count(text) if text else 0


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile; enough for p50/p95 on a few hundred calls."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[rank]


def normalise(text: str) -> str:
    """Whitespace-insensitive, so a reflowed fact still counts as kept."""
    return re.sub(r"\s+", " ", text)


def _views(compressed: str) -> list[str]:
    """The text as a reader sees it, plus grouped output expanded back.

    Lossless grouping prints ``path:line:text`` hits rg ``--heading`` style —
    the path once, then ``32:text`` under it — and path lists as a directory
    heading with names under it. Nothing is lost, but the literal
    ``path:line`` string no longer appears. Expanding with the compressors'
    own exact inverses (which they verify on every call) lets the fact check
    see what a reader sees, without accepting anything that was dropped.
    """
    views = [compressed]
    try:
        from sensei.compression.listing import ListingCompressor
        from sensei.compression.search import SearchCompressor
    except ImportError:  # an older Sensei without grouping
        return views
    views.append(SearchCompressor.ungroup(compressed))
    views.append("\n".join(ListingCompressor._ungroup(compressed.split("\n"))))
    return views


def missing_facts(facts: Sequence[str], compressed: str) -> list[str]:
    hays = [normalise(v) for v in _views(compressed)]
    return [f for f in facts if not any(normalise(f) in h for h in hays)]


# ─── Compressors ─────────────────────────────────────────────────────────────


@dataclass
class Output:
    text: str
    seconds: list[float] = field(default_factory=list)
    # The compressor did not finish within the watchdog's limit; ``text`` is
    # then the original, as if the caller had given up and sent it unchanged.
    timed_out: bool = False


class SenseiCompressor:
    """Sensei exactly as the gateway applies it to a tool result.

    ``edit_target=True`` because that is how ``compress_anthropic_request``
    treats every ``tool_result`` block: source code and line-numbered file
    views stay byte-exact, everything else is compressed.
    """

    name = "sensei"

    def __init__(self) -> None:
        from sensei.compression.router import ContentRouter

        self.router = ContentRouter(enable_caching=False)
        self.version = _sensei_version()

    def compress(self, text: str) -> str:
        return self.router.compress(text, edit_target=True).compressed

    def run(self, texts: Sequence[str], repeats: int = 1) -> list[Output]:
        if texts:
            self.compress(texts[0])  # warm-up, as for Headroom
        outs = []
        for text in texts:
            seconds = []
            out = text
            for _ in range(max(1, repeats)):
                started = time.perf_counter()
                out = self.compress(text)
                seconds.append(time.perf_counter() - started)
            outs.append(Output(out, seconds))
        return outs


class WatchedSenseiCompressor:
    """Sensei in a child process, with a per-input time limit.

    For replaying real data, where one pathological input must not stop the
    measurement. A text that takes longer than ``timeout`` seconds kills the
    child, is recorded as ``timed_out`` with the original text as output, and
    the child restarts on the next text. Timings come from inside the child,
    so they exclude the pipe.
    """

    name = "sensei"

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self.version = _sensei_version()

    def _spawn(self) -> subprocess.Popen:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(HERE.parent)}
        return subprocess.Popen(
            [sys.executable, "-m", "benchmarks.sensei_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=HERE.parent,
            text=True,
            encoding="utf-8",
        )

    def run(self, texts: Sequence[str], repeats: int = 1) -> list[Output]:
        import queue
        import threading

        outs: list[Output] = []
        i = 0
        while i < len(texts):
            proc = self._spawn()
            replies: queue.Queue = queue.Queue()

            def pump(p: subprocess.Popen = proc, q: queue.Queue = replies) -> None:
                assert p.stdout is not None
                for line in p.stdout:
                    q.put(line)
                q.put(None)

            threading.Thread(target=pump, daemon=True).start()
            assert proc.stdin is not None
            try:
                while i < len(texts):
                    proc.stdin.write(json.dumps(texts[i]) + "\n")
                    proc.stdin.flush()
                    try:
                        line = replies.get(timeout=self.timeout)
                    except queue.Empty:
                        outs.append(Output(texts[i], [self.timeout], timed_out=True))
                        i += 1
                        break
                    if line is None:  # the child died; count it like a hang
                        outs.append(Output(texts[i], [0.0], timed_out=True))
                        i += 1
                        break
                    reply = json.loads(line)
                    outs.append(Output(reply["out"], [reply["seconds"]]))
                    i += 1
            finally:
                proc.kill()
                proc.wait()
        return outs


class HeadroomCompressor:
    """Headroom, run by its own interpreter in its own virtualenv.

    It is never imported here: ``headroom_worker.py`` runs under the given
    Python and talks JSON over a pipe. Install it out of tree with
    ``python -m benchmarks.headroom_env``.
    """

    name = "headroom"

    def __init__(self, python: str, model: str = "claude-sonnet-4-5-20250929") -> None:
        self.python = python
        self.model = model
        self.version = "?"

    def run(self, texts: Sequence[str], repeats: int = 1) -> list[Output]:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        # Headroom's ML prose model is off unless installed; keep its logs quiet.
        env.setdefault("HEADROOM_LOG_LEVEL", "WARNING")
        req = {"texts": list(texts), "repeats": repeats, "model": self.model, "protect_recent": 0}
        proc = subprocess.run(  # noqa: S603 - the interpreter is the caller's own venv
            [self.python, "-I", str(HERE / "headroom_worker.py")],
            input=json.dumps(req).encode("utf-8"),
            capture_output=True,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            tail = proc.stderr.decode("utf-8", "replace")[-2000:]
            raise RuntimeError(f"headroom worker failed ({proc.returncode}):\n{tail}")
        data = json.loads(proc.stdout.decode("utf-8"))
        self.version = data.get("version", "?")
        return [Output(r["out"], r["seconds"]) for r in data["results"]]


def default_headroom_python() -> str | None:
    """$HEADROOM_PYTHON, or the venv ``benchmarks.headroom_env`` creates."""
    env = os.environ.get("HEADROOM_PYTHON")
    if env:
        return env
    from benchmarks.headroom_env import venv_python

    py = venv_python()
    return str(py) if py.exists() else None


def _sensei_version() -> str:
    from sensei import __version__ as v

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=HERE,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return f"{v}+{sha}"
    except Exception:
        return v


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def python_tag() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def median_ms(seconds: Sequence[float]) -> float:
    return statistics.median(seconds) * 1000 if seconds else 0.0
