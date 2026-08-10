"""Stack frames and build diagnostics must survive log compression.

Both bugs these cover were found by `benchmarks/quality_eval.py` on the day it
was written, and neither was visible from reading the code or from any existing
test — compression looked fine because the output was smaller and still looked
like a log.

The class of bug is worth naming: a regex that is syntactically valid, matches
nothing, and therefore fails silently. `LogCompressor.FRAME` contained
`File ", "` where `File "` was meant, so no Python traceback frame ever matched
it. The `"java": ("import ")` bug in CodeCompressor is the same shape. Tests
that assert on the *content* of the output catch these; tests that assert it got
smaller do not.
"""

from __future__ import annotations

import pytest

from sensei.compression.logcomp import LogCompressor
from sensei.compression.router import ContentRouter, ContentType

PYTHON_TRACEBACK = """\
Traceback (most recent call last):
  File "/app/worker.py", line 212, in run_batch
    results = [self.process(item) for item in batch]
  File "/app/worker.py", line 212, in <listcomp>
    results = [self.process(item) for item in batch]
  File "/app/worker.py", line 341, in process
    payload = self.serializer.encode(item.body)
  File "/app/serializers/json_fast.py", line 88, in encode
    return _dumps(obj, default=self._default)
TypeError: Object of type Decimal is not JSON serializable
"""

JAVA_TRACEBACK = "\n".join(
    [
        'Exception in thread "main" java.lang.NullPointerException: Cannot invoke "Order.total()"',
        "\tat com.example.checkout.CartService.sum(CartService.java:88)",
        "\tat com.example.checkout.CartService.checkout(CartService.java:41)",
        "\tat com.example.web.CheckoutController.post(CheckoutController.java:117)",
        "\tat java.base/java.lang.Thread.run(Thread.java:840)",
    ]
    + [f"\tat framework.internal.Filter{i}.doFilter(Filter{i}.java:{20 + i})" for i in range(20)]
)


def _build_log() -> str:
    lines = [f"[{i:04d}] compiling module_{i}.cpp ... ok" for i in range(120)]
    lines.insert(73, "src/parser.cpp:412:19: error: no matching function for call to 'advance'")
    lines.append("make: *** [Makefile:88: parser.o] Error 1")
    return "\n".join(lines)


class TestFrameRegex:
    def test_matches_a_python_frame_line(self) -> None:
        """The literal that was broken. Kept as its own test so a future edit
        to the alternation cannot quietly un-fix it."""
        assert LogCompressor.FRAME.match('  File "/app/worker.py", line 212, in run_batch')

    def test_matches_a_java_frame_line(self) -> None:
        assert LogCompressor.FRAME.match("\tat com.example.Foo.bar(Foo.java:88)")

    def test_does_not_match_ordinary_prose(self) -> None:
        assert not LogCompressor.FRAME.match("The build completed successfully.")


class TestTracebacksSurvive:
    def test_python_traceback_keeps_the_innermost_frame(self) -> None:
        """The innermost frame is the answer to "where did this break".

        Before the fix the compressor kept the outermost frame and the
        exception line and elided everything between, which is precisely the
        part an agent needs.
        """
        out = LogCompressor().compress(PYTHON_TRACEBACK)
        assert "json_fast.py" in out
        assert "line 88" in out
        assert "in encode" in out
        assert "TypeError: Object of type Decimal is not JSON serializable" in out

    def test_python_traceback_keeps_every_frame(self) -> None:
        out = LogCompressor().compress(PYTHON_TRACEBACK)
        assert "lines omitted" not in out

    def test_java_traceback_keeps_the_frames_nearest_the_exception(self) -> None:
        """Java puts the exception first and frames after it, so the block has
        to be followed forwards as well as backwards."""
        out = LogCompressor().compress(JAVA_TRACEBACK)
        assert "CartService.java:88" in out
        assert "CheckoutController.java:117" in out

    def test_a_pathological_trace_is_still_bounded(self) -> None:
        """A 900-frame trace is mostly framework noise. Keeping all of it would
        turn the compressor off exactly when it is most needed."""
        deep = "java.lang.IllegalStateException: boom\n" + "\n".join(
            f"\tat framework.Layer{i}.call(Layer{i}.java:{i})" for i in range(900)
        )
        out = LogCompressor().compress(deep)
        assert "lines omitted" in out
        assert len(out) < len(deep) / 2


class TestBuildLogRouting:
    def test_a_build_log_is_detected_as_logs(self) -> None:
        """It was classified as prose: no timestamps, no INFO/ERROR levels.

        The consequence was not just weaker compression. The prose compressor
        dropped `src/parser.cpp:412:19` — the one line that says where to look.
        """
        assert ContentRouter().detect_type(_build_log()) is ContentType.logs

    def test_the_compiler_error_location_survives(self) -> None:
        out = ContentRouter(enable_caching=False).compress(_build_log())
        assert "src/parser.cpp:412:19" in out.compressed
        assert "no matching function" in out.compressed
        assert "Error 1" in out.compressed

    def test_a_build_log_actually_compresses(self) -> None:
        """Routed to the prose compressor it managed 3%. It is 120 near-identical
        lines around two real ones; anything less than most of it is a bug."""
        result = ContentRouter(enable_caching=False).compress(_build_log())
        reduction = 1 - len(result.compressed) / len(result.original)
        assert reduction > 0.75, f"only {reduction:.0%} smaller"

    @pytest.mark.parametrize(
        "line",
        [
            "src/parser.cpp:412:19: error: no matching function",
            "[0042] compiling module_42.cpp ... ok",
            "make: *** [Makefile:88: parser.o] Error 1",
            "npm ERR! code ELIFECYCLE",
            "cargo: error: could not compile `sensei_core`",
        ],
    )
    def test_build_tool_lines_are_recognised(self, line: str) -> None:
        from sensei.compression.router import _LOG_LINE_START

        assert _LOG_LINE_START.match(line), f"not recognised as a log line: {line!r}"


class TestPlainLogsAreUnaffected:
    def test_noise_around_an_error_is_still_dropped(self) -> None:
        """The block-following must not turn into "keep everything"."""
        log = "\n".join(
            [f"2026-01-01T00:00:{i:02d} INFO worker {i} idle" for i in range(60)]
            + ["2026-01-01T00:01:00 ERROR queue depth exceeded"]
        )
        out = LogCompressor().compress(log)
        assert "lines omitted" in out
        assert "ERROR queue depth exceeded" in out
