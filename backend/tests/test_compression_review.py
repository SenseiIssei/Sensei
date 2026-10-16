"""Regression tests from the independent review of the agent-traffic pipeline.

Each test is one of the reviewer's probe scripts, reduced to an assertion.
Information loss outranks savings: every one of these was a case where the
compressed text said less than the original without saying so, or said
something the original did not.
"""

from __future__ import annotations

import json
import random
import re
import tempfile
import time
from pathlib import Path

import pytest

from sensei.compression import folds
from sensei.compression.ccr import CCRStore
from sensei.compression.markers import Context
from sensei.compression.router import ContentRouter, ContentType
from sensei.compression.search import _parse
from sensei.compression.textcrusher import TextCrusher

_BACKREF = re.compile(r"^\((\d+) lines identical to the \d+ lines starting (\d+) lines above\)$")


@pytest.fixture
def router() -> ContentRouter:
    return ContentRouter(ccr_store=CCRStore(tempfile.mkdtemp()), enable_caching=True)


def _added(text: str) -> int:
    return sum(1 for ln in text.split("\n") if ln.startswith("+") and not ln.startswith("+++"))


# ─── HIGH ───────────────────────────────────────────────────────────────────


def test_diff_keeps_every_added_line_even_when_repeated(router: ContentRouter) -> None:
    """p3: identical `+` blocks in several files were folded into a
    back-reference, which the diff compressor then trimmed as context."""
    block = [
        "+    logger.info('starting the expensive operation now, please wait')",
        "+    result = compute_the_expensive_operation(arg_one, arg_two, arg_three)",
        "+    logger.info('finished the expensive operation, result follows here')",
        "+    return result",
    ]
    lines: list[str] = []
    for name, extra in (("a.py", "+x = 1"), ("b.py", "+y = 2"), ("c.py", "-z = 3")):
        lines += [f"diff --git a/{name} b/{name}", f"--- a/{name}", f"+++ b/{name}"]
        lines += ["@@ -1,20 +1,25 @@", *(f" context line {i} of {name}" for i in range(8))]
        lines += block + [f" more context {i} of {name}" for i in range(8)] + [extra]
        lines += [f" tail ctx {i} {name}" for i in range(6)]
    text = "\n".join(lines)
    out = router.compress(text, edit_target=True).compressed
    assert _added(out) == _added(text) == 14
    assert "identical to the" not in out


def test_distinct_failing_tests_are_never_collapsed(router: ContentRouter) -> None:
    """p4 A: eight parametrised FAILED lines came back as two."""
    lines = ["=" * 29 + " test session starts " + "=" * 30, "collected 300 items", ""]
    lines += [f"tests/test_api_{i}.py " + "." * 40 + f" [{i}%]" for i in range(60)]
    fails = [
        f"FAILED tests/test_api.py::test_endpoint[case{i}] - AssertionError: assert {500 + i} == 200"
        for i in range(1, 9)
    ]
    lines += ["", "=" * 27 + " short test summary info " + "=" * 28, *fails]
    lines += ["=" * 24 + " 8 failed, 292 passed in 12.34s " + "=" * 24]
    out = router.compress("\n".join(lines), edit_target=True).compressed
    assert all(f in out for f in fails)


def test_distinct_errors_are_never_collapsed(router: ContentRouter) -> None:
    """p4 B and p14: errors that differ only in a name are different errors."""
    ids = ["user_id", "session", "retry_count", "cfg", "handler", "db_conn", "cache_key"]
    lines = ["make[1]: Entering directory '/src/app'"]
    lines += [f"[{i:04d}] cc -c -O2 src/mod{i}.c" for i in range(30)]
    errors = [
        f"src/parser.c:{100 + 7 * i}:9: error: '{v}' undeclared (first use in this function)"
        for i, v in enumerate(ids)
    ]
    lines += [*errors, "make[1]: *** [Makefile:88: build/parser.o] Error 1"]
    out = router.compress("\n".join(lines)).compressed
    assert all(e in out for e in errors)

    log = [f"2026-10-16 12:00:{i:02d} INFO request handled ok id={i}" for i in range(50)]
    errs = [
        f"src/{m}.rs:{10 + i}:5: error: cannot find value `{m}_handle` in this scope"
        for i, m in enumerate(["auth", "db", "cache", "queue", "mailer", "billing"])
    ]
    log[20:20] = errs
    out = router.compress("\n".join(log), edit_target=True).compressed
    assert all(e in out for e in errs)


def _traceback_log() -> str:
    trace = [
        "Traceback (most recent call last):",
        '  File "/app/server/handlers/payment_handler.py", line 88, in process_payment',
        "    receipt = gateway.charge(customer_id, amount_in_cents, idempotency_key)",
        '  File "/app/server/gateway/stripe_client.py", line 41, in charge',
        "    raise PaymentDeclined(response.decline_code)",
        "PaymentDeclined: card_declined",
    ]
    lines: list[str] = []
    for k in range(3):
        lines += [
            f"2026-10-16 12:{k:02d}:{s:02d} INFO worker heartbeat queue_depth={s * 7 % 13} "
            f"lag_ms={s * 31 % 97}"
            for s in range(30)
        ]
        lines += [f"2026-10-16 12:{k:02d}:59 ERROR payment failed for order {1000 + k}", *trace]
    return "\n".join(lines)


def test_back_references_point_at_visible_verbatim_lines(router: ContentRouter) -> None:
    """p5: "N lines above" pointed at lines the log compressor had deleted, and
    counted lines the reader could not see."""
    text = _traceback_log()
    out = router.compress(text, edit_target=True).compressed.split("\n")
    refs = 0
    for i, line in enumerate(out):
        m = _BACKREF.match(line)
        if not m:
            continue
        refs += 1
        n, back = int(m.group(1)), int(m.group(2))
        span = out[i - back : i - back + n]
        assert len(span) == n and i - back >= 0
        # Everything referenced is shown verbatim: original text, no markers,
        # no other reference.
        for s in span:
            assert s in text.split("\n"), s
    assert refs >= 1


def test_python_exception_line_survives_a_traceback(router: ContentRouter) -> None:
    out = router.compress(_traceback_log(), edit_target=True).compressed
    assert "PaymentDeclined: card_declined" in out


def test_no_source_file_changes_as_an_edit_target() -> None:
    """p1/p6: a module with a long docstring was detected as text and got
    folds and capitalisation. Every source and config file of this package,
    read as a tool result, must come back byte-exact."""
    router = ContentRouter(enable_caching=False)
    root = Path(__file__).resolve().parents[1]
    files = [
        p
        for pattern in (
            "sensei/**/*.py",
            "benchmarks/*.py",
            "pyproject.toml",
            "../.github/**/*.yml",
        )
        for p in root.glob(pattern)
    ]
    assert len(files) > 50
    changed = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if len(text) < 200:
            continue
        if router.compress(text, edit_target=True).compressed != text:
            changed.append(str(path.relative_to(root.parent)))
    assert not changed


@pytest.mark.parametrize(
    "payload",
    [
        ".PHONY: all build\n\nall: build test\n\nbuild:\n\tcargo build --release\n"
        "\tnpm --prefix frontend run build\n\ntest:\n\tcargo test --workspace\n\tgo test ./...\n",
        "# deps\nnode_modules/\nfrontend/node_modules/\nfrontend/dist/\nbackend/.venv\n"
        "backend/.pytest_cache\nbackend/htmlcov\nrust/target\ndocs/_build\n",
        "src/api/routes.py\nsrc/api/models.py\nsrc/api/schemas.py\nsrc/core/config.py\n"
        "src/core/db.py\nsrc/core/security.py\ntests/test_api.py",
        json.dumps([{"id": i, "name": f"user{i}", "email": None} for i in range(8)], indent=2),
        "<!DOCTYPE html><html><head><title>t</title><script>var a=1;</script></head><body>"
        + "<div><p>x</p></div>" * 3000
        + "</body></html>",
    ],
    ids=["makefile", "gitignore", "path-list", "pretty-json-array", "html-over-30kb"],
)
def test_files_read_as_tool_results_stay_byte_exact(router: ContentRouter, payload: str) -> None:
    """p6, p10, HTML: things that may be files on disk are never rewritten."""
    res = router.compress(payload, edit_target=True)
    assert res.compressed == payload
    assert not res.metadata["lossy"]


# ─── MEDIUM ─────────────────────────────────────────────────────────────────


def test_paths_with_dashed_numbers_are_parsed_whole(router: ContentRouter) -> None:
    """p7: `_posts/2024-01-15-launch.md:3:` was grouped under `_posts/2024`."""
    assert _parse("_posts/2024-01-15-launch.md:3:title: Launch day")[0] == (
        "_posts/2024-01-15-launch.md"
    )
    known = {"_posts/2024-01-15-launch.md"}
    assert _parse("_posts/2024-01-15-launch.md-4-context", known)[:3] == (
        "_posts/2024-01-15-launch.md",
        "-",
        "4",
    )
    assert _parse("_posts/2024-01-15-launch.md-4-context")[0] == "_posts/2024-01-15-launch.md"
    text = "\n".join(
        [
            "_posts/2024-01-15-launch.md:3:title: Launch day",
            "_posts/2024-01-15-launch.md:9:We launched the gateway today.",
            "_posts/2024-03-02-pricing.md:4:title: Pricing update",
            "src/v1-2-compat/shim.py:40:def gateway():",
            "src/v1-2-compat/shim.py:41:    return gateway_impl()",
        ]
    )
    out = router.compress(text, edit_target=True).compressed
    assert "_posts/2024-01-15-launch.md" in out.split("\n")
    assert "src/v1-2-compat/shim.py" in out.split("\n")


def test_json_nulls_and_empties_are_kept(router: ContentRouter) -> None:
    """p10: null and [] keys vanished, and the result was called lossless."""
    obj = {"name": "pkg", "scripts": {}, "deprecated": None, "files": ["a"], "tags": []}
    out = router.compress(json.dumps(obj), edit_target=True).compressed
    assert json.loads(out) == obj


def test_omitted_match_count_counts_matches_not_hunks(router: ContentRouter) -> None:
    """p12: with -C, "60 more matches" was reported where 180 were dropped."""
    lines: list[str] = []
    total = 0
    for f in range(3):
        for h in range(40):
            base = h * 20 + 1
            lines.append(f"src/pkg/module_{f}.py-{base}-    # setup for handler number {h}")
            for k in range(3):
                lines.append(
                    f"src/pkg/module_{f}.py:{base + 1 + k}:    handler_{h}_{k} = make({h}{k})"
                )
                total += 1
            lines += [f"src/pkg/module_{f}.py-{base + 4}-    # end of block {h}", "--"]
    res = router.compress("\n".join(lines))
    out = folds.unfold(res.compressed)
    shown = sum(1 for ln in out.split("\n") if re.match(r"^\d+:", ln))
    claimed = sum(int(m.group(1)) for m in re.finditer(r"\[sensei: (\d+) more match", out))
    assert claimed == total - shown


# ─── LOW / performance ──────────────────────────────────────────────────────


def _scaling(run, small: int, large: int) -> tuple[float, float]:
    """Seconds for a small and a 4x larger input (best of two each).

    CI runners differ by an order of magnitude in raw speed, so an absolute
    bound either flakes or proves nothing. Growth does not depend on the
    machine: linear work takes ~4x as long for 4x the input, and the
    quadratic versions these tests guard against took ~16x.
    """

    def best(n: int) -> float:
        times = []
        for _ in range(2):
            t0 = time.perf_counter()
            run(n)
            times.append(time.perf_counter() - t0)
        return min(times)

    return best(small), best(large)


def test_textcrusher_is_not_quadratic() -> None:
    """p9: 39 s on 1.4 MB of prose, from comparing every pair of sentences."""
    rng = random.Random(2)
    vocab = [f"w{i}" for i in range(3000)]
    sents = [" ".join(rng.choice(vocab) for _ in range(12)).capitalize() + "." for _ in range(8000)]

    def run(n: int) -> None:
        part = sents[:n]
        prose = "\n".join(" ".join(part[i : i + 5]) for i in range(0, len(part), 5))
        TextCrusher().compress(prose, Context())

    small, large = _scaling(run, 2000, 8000)
    assert large < max(small * 9, 0.5), (small, large)
    assert large < 30.0


def test_fold_repeats_on_many_short_lines_is_linear() -> None:
    """p13: 6 s per million short lines in the block search."""
    n = 400_000
    tm = [bin(i).count("1") % 2 for i in range(n + 2)]
    lines = [["connected ok", "retrying", "waiting"][tm[i + 1] - tm[i] + 1] for i in range(n)]

    def run(k: int) -> None:
        folds.fold("\n".join(lines[:k]))

    small, large = _scaling(run, 100_000, 400_000)
    assert large < max(small * 9, 0.5), (small, large)
    assert large < 60.0


def test_lossy_flag_matches_the_bytes(router: ContentRouter) -> None:
    """A step that cut and was then discarded must not report a cut."""
    res = router.compress("ERROR one\nERROR two\nERROR three", force_type=ContentType.logs)
    assert res.metadata["lossy"] == ("[sensei: " in res.compressed)
