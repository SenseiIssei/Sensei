from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sensei.compression.codecomp import CodeCompressor
from sensei.compression.router import ContentRouter, ContentType
from sensei.compression.smartcrusher import SmartCrusher
from sensei.compression.textcomp import TextCompressor


class TestSmartCrusher:
    def test_compress_simple_json(self):
        crusher = SmartCrusher()
        original = json.dumps({"name": "test", "value": 42, "empty": None, "blank": ""})
        result = crusher.compress(original)
        data = json.loads(result)
        assert "name" in data
        assert "empty" not in data
        assert "blank" not in data

    def test_compress_array_of_dicts(self):
        crusher = SmartCrusher()
        original = json.dumps([
            {"id": 1, "name": "Alice", "email": None},
            {"id": 2, "name": "Bob", "email": None},
            {"id": 3, "name": "Charlie", "email": None},
        ])
        result = crusher.compress(original)
        # New format: a CSV-schema table. `email` is constant (null) and hoisted;
        # id and name vary across rows.
        lines = result.splitlines()
        assert lines[0].startswith("@csv")
        assert "cols=id,name" in lines[0]
        assert len(lines) == 4  # header + 3 rows
        assert "Alice" in result and "Bob" in result and "Charlie" in result
        # And it must actually be smaller than the original JSON.
        assert len(result) < len(original)

    def test_invalid_json_passthrough(self):
        crusher = SmartCrusher()
        result = crusher.compress("not json at all")
        assert result == "not json at all"


class TestCodeCompressor:
    def test_strip_comments_python(self):
        comp = CodeCompressor()
        code = """# This is a comment
def hello():
    # Inline comment
    print("Hello")  # trailing
"""
        result = comp.compress(code)
        assert "# This is a comment" not in result
        assert "# Inline comment" not in result
        assert "def hello()" in result
        assert 'print("Hello")' in result

    def test_strip_comments_javascript(self):
        comp = CodeCompressor()
        code = """// Comment line
function foo() {
    return 42; // trailing
}
"""
        result = comp.compress(code)
        assert "// Comment line" not in result
        assert "function foo()" in result

    def test_preserve_logic(self):
        comp = CodeCompressor()
        code = """def add(a, b):
    return a + b
"""
        result = comp.compress(code)
        assert "def add(a, b)" in result
        assert "return a + b" in result


class TestTextCompressor:
    def test_remove_boilerplate(self):
        comp = TextCompressor()
        text = "In order to run the app, you need Python. Please note that it requires 3.11+."
        result = comp.compress(text)
        assert "In order to" not in result
        assert "Please note that" not in result

    def test_collapse_whitespace(self):
        comp = TextCompressor()
        text = "Line 1\n\n\n\n\nLine 2"
        result = comp.compress(text)
        assert result.count("\n\n\n") == 0

    def test_replace_verbose_phrases(self):
        comp = TextCompressor()
        result = comp.compress("We did it due to the fact that it was required.")
        assert "due to the fact that" not in result
        assert "because" in result

    def test_remove_filler_words(self):
        comp = TextCompressor()
        result = comp.compress("This is, in fact, basically a really simple example.")
        assert "in fact" not in result
        assert "basically" not in result
        # Filler-heavy prose should get meaningfully shorter.
        assert len(result) < len("This is, in fact, basically a really simple example.")

    def test_clean_prose_preserved(self):
        comp = TextCompressor()
        clean = "The pipeline routes each block to the right compressor."
        # No filler/verbosity to remove — content should survive intact.
        assert comp.compress(clean) == clean

    def test_sentence_capitalization_restored(self):
        comp = TextCompressor()
        result = comp.compress("In order to win, you must try.")
        assert result[0].isupper()

    def test_rust_matches_python(self):
        import unittest.mock as mock

        from sensei.compression import textcomp

        if textcomp._core is None:
            return
        samples = [
            "Basically, in order to actually get started, you must install everything.",
            "the vast majority of the configuration is going to be handled automatically",
            "x" * 600,
            "Multiple sentences. " * 60,
            "dup line long enough to dedupe\ndup line long enough to dedupe\nunique",
        ]
        for s in samples:
            rust_out = textcomp.TextCompressor().compress(s)
            with mock.patch.object(textcomp, "_core", None):
                py_out = textcomp.TextCompressor().compress(s)
            assert rust_out == py_out


class TestLogCompressor:
    def test_keeps_errors_drops_noise(self):
        from sensei.compression.logcomp import LogCompressor

        comp = LogCompressor()
        lines = [f"2026-01-01 12:00:{i:02d} INFO  step {i} ok" for i in range(40)]
        lines.append("2026-01-01 12:01:00 ERROR something exploded")
        text = "\n".join(lines)
        result = comp.compress(text)
        assert "ERROR something exploded" in result
        assert "lines omitted" in result
        assert len(result) < len(text)

    def test_short_log_passthrough(self):
        from sensei.compression.logcomp import LogCompressor

        comp = LogCompressor()
        text = "line1\nline2\nERROR boom"  # < 10 lines
        assert comp.compress(text) == text

    def test_rust_matches_python(self):
        # When the Rust accelerator is built, its output must be byte-identical
        # to the pure-Python path.
        import unittest.mock as mock

        from sensei.compression import logcomp

        if logcomp._core is None:
            return
        text = "\n".join(
            [f"2026-01-01 12:00:{i:02d} INFO step {i} ok" for i in range(30)]
            + ["2026-01-01 12:01:00 ERROR boom", "done"]
        )
        rust_out = logcomp.LogCompressor().compress(text)
        with mock.patch.object(logcomp, "_core", None):
            py_out = logcomp.LogCompressor().compress(text)
        assert rust_out == py_out


class TestContentRouter:
    def test_detect_json(self):
        router = ContentRouter(enable_caching=False)
        assert router.detect_type('{"key": "value"}') == ContentType.json
        assert router.detect_type('[1, 2, 3]') == ContentType.json

    def test_detect_code(self):
        router = ContentRouter(enable_caching=False)
        code = "def hello():\n    print('world')\n"
        assert router.detect_type(code) == ContentType.code

    def test_detect_logs(self):
        router = ContentRouter(enable_caching=False)
        log = "\n".join(f"2026-01-01 12:00:{i:02d} INFO doing thing {i}" for i in range(20))
        assert router.detect_type(log) == ContentType.logs

    def test_detect_text(self):
        router = ContentRouter(enable_caching=False)
        assert router.detect_type("Just a regular sentence.") == ContentType.text

    def test_compress_returns_result(self):
        router = ContentRouter(enable_caching=False)
        result = router.compress('{"name": "test", "value": null}')
        assert result.original != result.compressed
        assert result.content_type == ContentType.json
        assert result.original_tokens > 0

    def test_compress_messages_preserves_system(self):
        router = ContentRouter(enable_caching=False)
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "x" * 200},
        ]
        compressed, results = router.compress_messages(messages)
        assert compressed[0]["role"] == "system"
        assert len(results) >= 1


class TestIntegration:
    def test_health_endpoint(self):
        from sensei.main import app

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_root_endpoint(self):
        from sensei.main import app

        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Sensei"

    def test_models_endpoint(self):
        from sensei.main import app

        client = TestClient(app)
        resp = client.get("/api/models")
        assert resp.status_code == 200
