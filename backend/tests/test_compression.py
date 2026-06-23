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
        data = json.loads(result)
        # Should be columnar: {"k": [...], "v": [...]}
        assert "k" in data
        assert "v" in data
        assert len(data["v"]) == 3

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


class TestContentRouter:
    def test_detect_json(self):
        router = ContentRouter(enable_caching=False)
        assert router.detect_type('{"key": "value"}') == ContentType.json
        assert router.detect_type('[1, 2, 3]') == ContentType.json

    def test_detect_code(self):
        router = ContentRouter(enable_caching=False)
        code = "def hello():\n    print('world')\n"
        assert router.detect_type(code) == ContentType.code

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
