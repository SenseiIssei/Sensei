"""The provider's prompt cache, and what actually preserves it.

The cache is keyed on the bytes the provider receives, which are the bytes
Sensei sends. So the question is never "did Sensei change the text" but "does
Sensei produce the same text for the same message on every turn". Compression is
deterministic, so it does — and compressing everything is cache-safe.

What breaks it is a decision that depends on position. `gateway_preserve_cache`
compresses only the newest message, so a message compressed while it was newest
arrives uncompressed on the next turn. Different bytes, cache miss, every turn —
on precisely the cache-heavy agents the setting used to recommend itself for.

Written after going the wrong way first: the cached prefix was protected on
sight of a `cache_control` marker, which is where Claude Code puts one on the
*last* message. That protected the entire request and compressed nothing — a
real task went from 12,561 tokens saved to 1.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from sensei.compression.router import ContentRouter
from sensei.config import settings
from sensei.routers.gateway import compress_anthropic_request


def _tool_output(n: int) -> str:
    return "\n".join(f"2026-08-11 INFO worker={s % 4} item={s} n={n} status=ok" for s in range(300))


def _digest(messages: list[dict]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


@pytest.fixture(autouse=True)
def _defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "compression_enabled", True)
    monkeypatch.setattr(settings, "gateway_compress_system", True)
    monkeypatch.setattr(settings, "gateway_preserve_cache", False)


def test_compression_is_deterministic() -> None:
    """Everything below rests on this. If the same text could compress two ways,
    no amount of care about which messages get touched would keep a cache."""
    text = _tool_output(0)
    digests = {hashlib.sha256(ContentRouter().compress(text).compressed.encode()).hexdigest()}
    for _ in range(4):
        digests.add(hashlib.sha256(ContentRouter().compress(text).compressed.encode()).hexdigest())

    assert len(digests) == 1


class TestTheCachedPrefixSurvivesAnotherTurn:
    def test_by_default_the_prefix_is_byte_identical_next_turn(self) -> None:
        """Which is what the provider needs, and it comes for free from
        determinism — not from leaving anything uncompressed."""
        turn_n = [
            {"role": "user", "content": _tool_output(0)},
            {"role": "assistant", "content": _tool_output(1)},
        ]
        turn_n1 = [*turn_n, {"role": "user", "content": _tool_output(2)}]

        _, out_n, _ = compress_anthropic_request(None, [dict(m) for m in turn_n])
        _, out_n1, _ = compress_anthropic_request(None, [dict(m) for m in turn_n1])

        assert _digest(out_n) == _digest(out_n1[:2])

    def test_preserve_cache_is_what_breaks_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The setting that used to describe itself as the one to enable for a
        cache-heavy agent. A message compressed while newest comes back
        uncompressed once it is not."""
        monkeypatch.setattr(settings, "gateway_preserve_cache", True)
        turn_n = [
            {"role": "user", "content": _tool_output(0)},
            {"role": "assistant", "content": _tool_output(1)},
        ]
        turn_n1 = [*turn_n, {"role": "user", "content": _tool_output(2)}]

        _, out_n, _ = compress_anthropic_request(None, [dict(m) for m in turn_n])
        _, out_n1, _ = compress_anthropic_request(None, [dict(m) for m in turn_n1])

        assert _digest(out_n) != _digest(out_n1[:2])


class TestCompressionIsNotGivenUpForCaching:
    def test_a_marked_request_is_still_compressed(self) -> None:
        """Claude Code marks its *last* message, so treating a marker as
        "protect everything up to here" protects the whole request. That was
        tried; it reduced a real task from 12,561 tokens saved to 1."""
        messages = [
            {"role": "user", "content": _tool_output(0)},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": _tool_output(1),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
        ]

        _, out, savings = compress_anthropic_request(None, messages)

        assert savings["tokens_saved"] > 0
        assert len(out[0]["content"]) < len(_tool_output(0))

    def test_the_marker_itself_is_passed_through(self) -> None:
        """Sensei rewrites the text inside a block, never the block's own
        fields — dropping the marker would turn every request into a cache
        write instead of a read."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": _tool_output(0),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ]

        _, out, _ = compress_anthropic_request(None, messages)

        assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
