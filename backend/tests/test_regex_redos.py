"""The compression cleanup regexes must stay linear-time.

Sensei runs these over text it does not control — crawled pages, tool output,
anything a client sends through the gateway. A quadratic pattern there is a
denial-of-service vector: a few tens of kB of whitespace stalls the process for
ten-plus seconds.

Two things are asserted:

1. The rewritten patterns are byte-identical to the naive ones they replaced,
   over exhaustive randomized input. Equivalence is the whole reason the
   rewrite is safe to make.
2. Pathological input completes fast enough that no reasonable machine could
   be stalled by it.
"""

from __future__ import annotations

import random
import re
import time

import pytest

from sensei.compression.learned import _tidy
from sensei.compression.textcomp import TextCompressor

# (naive pattern, hardened replacement, substitution) — the hardened form is
# what actually ships; the naive one is kept here solely as the oracle.
PATTERN_PAIRS = [
    (r"\s+([,.;:!?])", r"(?<!\s)\s++([,.;:!?])", r"\1"),
    (r"(,\s*){2,}", r"(?:,\s*+){2,}", ", "),
    (r"([,;:]\s*){2,}", r"(?:[,;:]\s*+){2,}", ", "),
    (r"\s*([.!?])[\s.,;:]*", r"(?:(?<!\s)\s++)?([.!?])[\s.,;:]*+", r"\1 "),
    (r"^[\s,;:.]+", r"^[\s,;:.]++", ""),
    (r"\s{2,}", r"\s{2,}+", " "),
    (r"[ \t]+", r"[ \t]++", " "),
    (r" *\n *", r" *+\n *+", "\n"),
]

ALPHABET = " \t\n,.;:!?abc"


@pytest.mark.parametrize(("naive", "hardened", "repl"), PATTERN_PAIRS)
def test_hardened_pattern_is_equivalent(naive: str, hardened: str, repl: str) -> None:
    """The rewrite must not change a single byte of output."""
    rng = random.Random(20260727)
    naive_re, hardened_re = re.compile(naive), re.compile(hardened)

    for _ in range(4000):
        s = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 30)))
        assert naive_re.sub(repl, s) == hardened_re.sub(repl, s), f"diverged on {s!r}"

    # Edge cases randomness is unlikely to produce.
    for s in ("", " ", "\n", ",", "   ,", ",   ", "a,,,,b", "  .  ", "\t\t?\t\t"):
        assert naive_re.sub(repl, s) == hardened_re.sub(repl, s), f"diverged on {s!r}"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(" " * 30_000 + "x", id="whitespace-run"),
        pytest.param("," * 30_000, id="comma-run"),
        pytest.param(" ," * 15_000, id="alternating"),
        pytest.param("\t" * 30_000 + ".", id="tab-run"),
        pytest.param(("a" + " " * 200) * 150, id="many-runs"),
    ],
)
def test_cleanup_is_fast_on_pathological_input(payload: str) -> None:
    """A 30 kB adversarial string must not stall the compressor.

    The naive patterns took 11-12 seconds on these; the ceiling here is
    deliberately loose so a slow CI runner doesn't cause a flake, while still
    being far below anything quadratic.
    """
    compressor = TextCompressor()

    start = time.perf_counter()
    compressor._cleanup(payload)
    _tidy(payload)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"cleanup took {elapsed:.2f}s — a quadratic pattern is back"


def test_cleanup_still_does_its_job() -> None:
    """Guard the behaviour the hardening was not allowed to change."""
    compressor = TextCompressor()

    assert compressor._cleanup("word   ,   next") == "word, next"
    assert compressor._cleanup("a,,,b") == "a, b"
    assert compressor._cleanup("keep  \n  this") == "keep\nthis"

    assert _tidy("hello   ,  world") == "Hello, world"
    assert _tidy("  ,,, leading") == "Leading"
