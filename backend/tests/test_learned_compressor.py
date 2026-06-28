from __future__ import annotations

import sensei.compression.learned as learned
from sensei.compression.router import ContentRouter, ContentType


def setup_function():
    learned.reset_cache()


def teardown_function():
    learned.reset_cache()


def test_tidy_cleans_drop_artifacts():
    from sensei.compression.learned import _tidy

    assert _tidy(" , the system ,, resilient .") == "The system, resilient."
    assert _tidy("") == ""
    assert _tidy("hello world") == "Hello world"


def test_disabled_by_default_returns_none(monkeypatch):
    from sensei.config import settings

    monkeypatch.setattr(settings, "learned_compressor_enabled", False)
    learned.reset_cache()
    assert learned.get_prose_compressor() is None


def test_enabled_but_missing_checkpoint_falls_back(monkeypatch, tmp_path):
    from sensei.config import settings

    monkeypatch.setattr(settings, "learned_compressor_enabled", True)
    monkeypatch.setattr(settings, "learned_compressor_path", str(tmp_path / "nope"))
    learned.reset_cache()
    assert learned.get_prose_compressor() is None  # missing path → None, no crash


def test_router_uses_rule_based_by_default():
    learned.reset_cache()
    router = ContentRouter(enable_caching=False)
    res = router.compress("Basically, in order to ship we really must test things.", force_type=ContentType.text)
    assert res.metadata["compressor"] == "textcompressor"


def test_router_uses_learned_when_available(monkeypatch):
    class _Fake:
        def compress(self, text: str) -> str:
            return "LEARNED::" + text[:6]

    monkeypatch.setattr(learned, "get_prose_compressor", lambda: _Fake())
    router = ContentRouter(enable_caching=False)
    res = router.compress("Some plain verbose prose that should be compressed here.", force_type=ContentType.text)
    assert res.compressed.startswith("LEARNED::")
    assert res.metadata["compressor"] == "learned-compressor"
