"""The agent-traffic compressors must stay linear-time too.

Same contract as ``test_regex_redos.py``: these checks run over text Sensei
does not control (a 40 KB minified line in a grep hit, a padded table), so a
pattern that backtracks quadratically is a way to stall the gateway.

Each regex that CodeQL flagged was replaced by plain string scanning. Two
things are asserted:

1. The replacement gives the same answer as the regex it replaced, on
   randomized input from an alphabet built to hit its edge cases. The old
   regex is kept here only as the oracle.
2. Pathological input completes quickly.
"""

from __future__ import annotations

import random
import re
import time

import pytest

from sensei.compression.gitcomp import GitCompressor, _field
from sensei.compression.logcomp import LogCompressor
from sensei.compression.router import ContentRouter, _is_test_line, _wordish
from sensei.compression.textcrusher import split_sentences

_SEED = 20261016


def _random(alphabet: list[str], n: int = 4000, max_len: int = 12) -> list[str]:
    rng = random.Random(_SEED)
    return ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, max_len))) for _ in range(n)]


# ─── equivalence with the patterns they replaced ────────────────────────────


def test_sentence_split_matches_the_old_regex() -> None:
    old = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
    alphabet = [".", "!", "?", " ", "  ", "\t", "a", "B", "7", '"', "(", "[", "x.", "é"]
    for s in _random(alphabet, max_len=16):
        assert split_sentences(s) == old.split(s), repr(s)


def test_noise_matches_the_old_regex() -> None:
    old = re.compile(
        r"^(?:test \S.* \.\.\. (?:ok|ignored)$"
        r"|\S+::\S+ PASSED(?:\s+\[\s*\d+%\])?$"
        r"|\S+\.py \.+\s*(?:\[\s*\d+%\])?$)"
    )
    alphabet = ["test ", "a", "::", " ", ".", "...", " ... ok", " ... ignored", "x.py",
                " PASSED", "[", " 10%", "]", "%]", "\t"]  # fmt: skip
    for s in _random(alphabet):
        if old.match(s):
            assert LogCompressor.is_noise(s), repr(s)


def test_noise_still_recognises_the_common_shapes() -> None:
    for line in (
        "test scheduler::case_1 ... ok",
        "tests/test_a.py::test_x PASSED",
        "tests/test_a.py::test_x PASSED [ 40%]",
        "tests/test_a.py ........ [ 40%]",
        "   Compiling serde v1.0.200",
        "#12 DONE 3.1s",
    ):
        assert LogCompressor.is_noise(line), line
    for line in ("test scheduler::case_1 ... FAILED", "tests/test_a.py ..F.. [ 40%]"):
        assert not LogCompressor.is_noise(line), line


def test_test_line_matches_the_old_regex() -> None:
    old = re.compile(
        r"^(?:test \S.* \.\.\. (?:ok|FAILED|ignored)$|\S+\.py [.FEsxX]+\s*\[\s*\d+%\]$"
        r"|=+ .*(?:test session starts|FAILURES|ERRORS|short test summary|passed|failed).* =+$"
        r"|\s*(?:FAIL|PASS)\s+\S|running \d+ tests?$|--- FAIL:)"
    )
    alphabet = ["test ", "a", " ", "...", " ... ok", " ... FAILED", "x.py", ".", "F", "[",
                "10%", "]", "===", " passed ", "FAILURES", "running 3 tests", "PASS "]  # fmt: skip
    for s in _random(alphabet):
        assert _is_test_line(s) == bool(old.match(s)), repr(s)


def test_wordish_matches_the_old_regex() -> None:
    old = re.compile(r"[A-Za-z][a-z'-]+[,.;:!?]?$")
    alphabet = ["A", "a", "z", "'", "-", ",", ".", "!", "1", "_", "É", "Q"]
    for s in _random(alphabet, max_len=6):
        assert _wordish(s) == bool(old.match(s)), repr(s)


def test_git_fields_match_the_old_regexes() -> None:
    patterns = {
        ("Author",): re.compile(r"^Author:\s+(.*)$"),
        ("Date", "AuthorDate", "CommitDate"): re.compile(
            r"^(?:Date|AuthorDate|CommitDate):\s+(.*)$"
        ),
        ("Merge",): re.compile(r"^Merge:\s+(.*)$"),
    }
    alphabet = ["Author", "Date", "AuthorDate", "Merge", ":", " ", "  ", "\t", "x", "A <a@b>"]
    for s in _random(alphabet):
        for names, old in patterns.items():
            m = old.match(s)
            got = _field(s, *names)
            assert (got is not None) == bool(m), (repr(s), names)
            if m:
                assert got == m.group(1).strip()


# ─── pathological input ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        "!::" * 20000,
        "A" + "a" * 50000,
        "Author:" + "  " * 20000 + "x",
        "Merge:" + "  " * 20000,
        "Date:" + " " * 40000 + "!",
        "test " + "x" * 50000,
        "x" * 50000 + ".py" + " ." * 1000,
        "=" + " passed" * 5000 + " x",
        "word." + " " * 40000 + "lower",
        "<p>a" + " \t" * 20000 + "x</p>",
    ],
    ids=lambda p: f"{p[:12]!r}..{len(p)}",
)
def test_pathological_lines_are_fast(payload: str) -> None:
    router = ContentRouter(enable_caching=False)
    text = "\n".join([payload] * 3 + ["Author: A <a@b>", "commit " + "a" * 40] * 3)
    t0 = time.perf_counter()
    router.compress(text, edit_target=True)
    router.compress(text, force_type=None)
    GitCompressor().compress(text)
    split_sentences(payload)
    for line in (payload, payload[:2000]):
        LogCompressor.is_noise(line)
        _is_test_line(line)
        _wordish(line)
    assert time.perf_counter() - t0 < 2.0
