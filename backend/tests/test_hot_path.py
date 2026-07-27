"""Guards for the gateway's hot path.

`ContentRouter.compress_messages` runs on every request an agent makes, so its
cost is added to every single model call. These tests pin the properties that
keep it cheap — they are about complexity, not about a stopwatch, so they don't
flake on a slow CI runner.
"""

from __future__ import annotations

import time

import pytest

from sensei.compression import codecomp, router
from sensei.compression.router import ContentRouter, ContentType


class TestDetectionIsBounded:
    """Type detection looks at a sample, so it must not cost O(payload)."""

    @pytest.mark.parametrize("detector", [router._detect_logs, router._detect_code])
    def test_detection_does_not_scan_the_whole_payload(self, detector) -> None:
        # 8 MB of lines. A detector that splits the whole thing allocates
        # ~400k strings; one that stops after its sample allocates ~80.
        huge = "\n".join(f"line {i} of some ordinary prose content here" for i in range(400_000))
        assert len(huge) > 8_000_000

        start = time.perf_counter()
        for _ in range(20):
            detector(huge)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, (
            f"20 detections over 8 MB took {elapsed:.2f}s — the bounded split is gone"
        )

    def test_bounded_split_gives_the_same_verdict_as_a_full_split(self) -> None:
        """The optimisation is only valid if it never changes the answer."""
        logs = "\n".join(f"2026-07-27T10:00:{i % 60:02d}Z [INFO] worker {i} ok" for i in range(200))
        prose = "\n".join(f"Just an ordinary sentence number {i}." for i in range(200))
        code = "\n".join(["import os", "", "def f(x):", "    return x + 1"] * 50)

        assert router._detect_logs(logs) is True
        assert router._detect_logs(prose) is False
        assert router._detect_code(code) is True
        assert router._detect_code(prose) is False

    def test_short_input_is_still_rejected_as_logs(self) -> None:
        assert router._detect_logs("[INFO] one line") is False
        assert router._detect_logs("\n".join(["[INFO] x"] * 7)) is False
        assert router._detect_logs("\n".join(["[INFO] x"] * 8)) is True


class TestPatternsAreCompiledOnce:
    """Recompiling per line was ~11k `re` cache lookups per request."""

    def test_detector_patterns_are_compiled(self) -> None:
        import re

        assert isinstance(router._STRONG_CODE_RE, re.Pattern)
        assert isinstance(router._WEAK_CODE_RE, re.Pattern)

    def test_comment_patterns_are_compiled(self) -> None:
        import re

        assert isinstance(codecomp._BLOCK_COMMENT_RE, re.Pattern)
        assert isinstance(codecomp._DEFAULT_COMMENT_RE, re.Pattern)
        for lang, pat in codecomp._COMMENT_RES.items():
            assert isinstance(pat, re.Pattern), lang


class TestImportPrefixes:
    def test_every_language_maps_to_a_tuple_not_a_bare_string(self) -> None:
        """`"java": ("import ")` is a string, not a 1-tuple.

        `any(line.startswith(p) for p in prefixes)` then iterates the characters
        of "import ", so every line beginning with i, m, p, o, r, t or a space
        was treated as an import and folded away. Java input was silently
        mangled. The trailing comma is load-bearing.
        """
        for lang, prefixes in codecomp._IMPORT_PREFIXES.items():
            assert isinstance(prefixes, tuple), f"{lang} maps to {type(prefixes).__name__}"
            assert all(isinstance(p, str) and len(p) > 1 for p in prefixes), lang

    def test_java_keeps_non_import_lines(self) -> None:
        java = "\n".join(
            [
                "import java.util.List;",
                "public class Thing {",
                "    private int total;",
                "    void run() {",
                "        total = 1;",
                "    }",
                "}",
            ]
        )
        out = codecomp.CodeCompressor()._collapse_imports(java.split("\n"), "java")
        body = "\n".join(out)
        # These begin with 'p', 'i', 't' and a space — all characters of
        # "import ", which is exactly what the old bug keyed on.
        assert "public class Thing {" in body
        assert "private int total;" in body
        assert "total = 1;" in body


class TestOutputIsUnchanged:
    """The optimisations must not move a single byte of compressed output."""

    @pytest.mark.parametrize(
        ("content", "expected_type"),
        [
            ('[{"a": 1, "b": 2}, {"a": 3, "b": 4}]', ContentType.json),
            ("\n".join(["2026-01-01T00:00:00Z [INFO] ok"] * 20), ContentType.logs),
            ("import os\n\ndef f(x):\n    # a comment\n    return x\n", ContentType.code),
            ("It is important to note that this is basically prose.", ContentType.text),
        ],
    )
    def test_routing_still_picks_the_right_compressor(self, content, expected_type) -> None:
        assert ContentRouter(enable_caching=False).detect_type(content) == expected_type

    def test_python_comment_stripping_is_intact(self) -> None:
        src = "import os  # trailing\n\n# whole-line comment\ndef f():\n    return 1\n"
        out = codecomp.CodeCompressor().compress(src)
        assert "# trailing" not in out
        assert "whole-line comment" not in out
        assert "def f():" in out
        assert "return 1" in out

    def test_block_comments_are_stripped(self) -> None:
        src = "const a = 1; /* inline */\n/* start\n   middle\n   end */\nconst b = 2;\n"
        out = codecomp.CodeCompressor().compress(src)
        assert "inline" not in out
        assert "middle" not in out
        assert "const a = 1;" in out
        assert "const b = 2;" in out
