"""Guardrail: the compression pipeline must save >60% on a representative corpus.

Uses the router's offline len//4 token estimate (not tiktoken) so the test runs
without downloading a tokenizer. The tiktoken-measured number from
``benchmarks/compression_benchmark.py`` is higher still.
"""
from __future__ import annotations

from benchmarks.compression_benchmark import CORPUS
from sensei.compression.router import ContentRouter


def test_aggregate_savings_exceed_60_percent():
    router = ContentRouter(enable_caching=False)
    total_original = total_compressed = 0
    for content in CORPUS.values():
        result = router.compress(content)
        total_original += result.original_tokens
        total_compressed += result.compressed_tokens

    saved = 1 - total_compressed / total_original
    assert saved >= 0.60, f"aggregate savings {saved:.0%} below the 60% target"


def test_every_sample_is_compressed():
    router = ContentRouter(enable_caching=False)
    for name, content in CORPUS.items():
        result = router.compress(content)
        assert result.compressed_tokens <= result.original_tokens, name
