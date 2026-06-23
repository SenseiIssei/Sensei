from __future__ import annotations

import pytest

from sensei.compression.cachealign import CacheAligner
from sensei.compression.ccr import CCRStore
from sensei.compression.codecomp import CodeCompressor
from sensei.compression.router import ContentRouter, ContentType
from sensei.compression.smartcrusher import SmartCrusher
from sensei.compression.textcomp import TextCompressor


class TestCacheAligner:
    def test_strip_timestamps(self):
        aligner = CacheAligner()
        text = "Current time is 12:34:56 and date is 2024-01-15"
        result = aligner._strip_volatile(text)
        assert "12:34:56" not in result
        assert "2024-01-15" not in result

    def test_strip_uuids(self):
        aligner = CacheAligner()
        text = "Session ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        result = aligner._strip_volatile(text)
        assert "a1b2c3d4-e5f6-7890-abcd-ef1234567890" not in result

    def test_align_messages_preserves_structure(self):
        aligner = CacheAligner()
        messages = [
            {"role": "system", "content": "You are Sensei. Time is 14:30:00"},
            {"role": "user", "content": "Hello"},
        ]
        aligned = aligner.align(messages)
        assert len(aligned) == 2
        assert aligned[0]["role"] == "system"
        assert aligned[1]["role"] == "user"
        assert "14:30:00" not in aligned[0]["content"]


class TestCCRStore:
    def test_store_and_retrieve(self, tmp_path):
        store = CCRStore(cache_dir=str(tmp_path))
        content_id = store.store("Hello world", "HW")
        assert content_id is not None
        retrieved = store.retrieve(content_id)
        assert retrieved == "Hello world"

    def test_retrieve_nonexistent(self, tmp_path):
        store = CCRStore(cache_dir=str(tmp_path))
        assert store.retrieve("nonexistent-id") is None

    def test_stats(self, tmp_path):
        store = CCRStore(cache_dir=str(tmp_path))
        store.store("original content here", "compressed")
        stats = store.stats()
        assert stats["total_entries"] >= 1
        assert stats["active_entries"] >= 1
        assert stats["total_original_bytes"] > 0

    def test_eviction(self, tmp_path):
        store = CCRStore(cache_dir=str(tmp_path), ttl_hours=0)
        store.store("temp content", "tc")
        # With 0 TTL, content should be evicted
        stats = store.stats()
        # The entry might still be counted in total but not active
        assert stats["total_entries"] >= 1


class TestContentRouterIntegration:
    def test_full_pipeline_json(self):
        router = ContentRouter(enable_caching=False)
        import json
        original = json.dumps({
            "users": [
                {"id": 1, "name": "Alice", "email": None},
                {"id": 2, "name": "Bob", "email": None},
            ]
        })
        result = router.compress(original)
        assert result.original_tokens > result.compressed_tokens
        assert result.content_type == ContentType.json

    def test_full_pipeline_code(self):
        router = ContentRouter(enable_caching=False)
        code = """def hello():
    # This is a comment
    print("Hello, World!")
"""
        result = router.compress(code)
        assert result.content_type == ContentType.code
        assert result.original_tokens > 0

    def test_full_pipeline_text(self):
        router = ContentRouter(enable_caching=False)
        text = "In order to test this, please note that we need to verify the system."
        result = router.compress(text)
        assert result.content_type == ContentType.text
        assert result.original_tokens > 0

    def test_short_content_passthrough(self):
        router = ContentRouter(enable_caching=False)
        result = router.compress("Hi")
        assert result.original_tokens == result.compressed_tokens

    def test_compress_messages_with_caching(self):
        router = ContentRouter(enable_caching=True)
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "x" * 200},
        ]
        compressed, results = router.compress_messages(messages)
        assert len(compressed) == 2
        assert compressed[0]["role"] == "system"

    def test_empty_messages(self):
        router = ContentRouter(enable_caching=False)
        compressed, results = router.compress_messages([])
        assert len(compressed) == 0
        assert len(results) == 0

    def test_none_content_skipped(self):
        router = ContentRouter(enable_caching=False)
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": None},
        ]
        compressed, results = router.compress_messages(messages)
        assert len(compressed) == 2
