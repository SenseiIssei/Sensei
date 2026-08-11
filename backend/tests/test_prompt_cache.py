"""Never rewrite what the provider is caching.

A `cache_control` marker caches everything up to and including the block it sits
on. Rewriting any of that changes the cache key, so the next request pays full
price for a prefix that would have been billed at a fraction — which can cost
several times whatever the rewrite saved. Compression that loses money is worse
than no compression, and the savings ledger cannot see it happen.

Measured on real Claude Code traffic: 33 markers across 22 requests.
"""

from __future__ import annotations

import pytest

from sensei.config import settings
from sensei.routers.gateway import compress_anthropic_request

# Repetitive on purpose. Flowing prose is left alone by the compressor anyway,
# so a prose fixture cannot tell "protected because cached" from "nothing to do".
BIG = "\n".join(
    f"file: src/module_{i}/handler.py  status=unchanged  lines={100 + i}  owner=team-a"
    for i in range(400)
)
TOOL_OUTPUT = "\n".join(f"2026-08-11 INFO worker={s % 4} item={s} status=ok" for s in range(400))


@pytest.fixture(autouse=True)
def _defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "compression_enabled", True)
    monkeypatch.setattr(settings, "gateway_compress_system", True)
    monkeypatch.setattr(settings, "gateway_preserve_cache", False)


def _system(cached: bool) -> list[dict]:
    block: dict = {"type": "text", "text": BIG}
    if cached:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


class TestACachedPrefixIsLeftAlone:
    def test_a_marked_system_prompt_is_not_rewritten(self) -> None:
        """This is the default configuration, and it used to rewrite it."""
        system, _, _ = compress_anthropic_request(
            _system(cached=True), [{"role": "user", "content": TOOL_OUTPUT}]
        )

        assert system[0]["text"] == BIG
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_an_unmarked_system_prompt_is_still_compressed(self) -> None:
        """No caching means nothing to protect, so the old behaviour stands —
        this must not become a blanket refusal to touch system prompts."""
        system, _, _ = compress_anthropic_request(
            _system(cached=False), [{"role": "user", "content": TOOL_OUTPUT}]
        )

        assert system[0]["text"] != BIG
        assert len(system[0]["text"]) < len(BIG)

    def test_a_marker_anywhere_protects_everything_before_it(self) -> None:
        """The marker caches the prefix up to itself, so one on the last tool
        definition protects the system prompt too."""
        messages = [
            {"role": "user", "content": [{"type": "text", "text": BIG}]},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": BIG, "cache_control": {"type": "ephemeral"}}],
            },
            {"role": "user", "content": TOOL_OUTPUT},
        ]

        system, out, _ = compress_anthropic_request(_system(cached=False), messages)

        assert system[0]["text"] == BIG, "system sits inside the cached prefix"
        assert out[0]["content"][0]["text"] == BIG
        assert out[1]["content"][0]["text"] == BIG

    def test_everything_after_the_marker_is_still_compressed(self) -> None:
        """Otherwise protecting the cache would cost the whole point of this.

        The tokens on an agent transcript are in the turns *after* the cached
        prefix — tool output, file dumps, command results.
        """
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": BIG, "cache_control": {"type": "ephemeral"}}],
            },
            {"role": "assistant", "content": TOOL_OUTPUT},
            {"role": "user", "content": TOOL_OUTPUT},
        ]

        _, out, savings = compress_anthropic_request(_system(cached=True), messages)

        assert out[0]["content"][0]["text"] == BIG, "the cached turn was rewritten"
        assert len(out[1]["content"]) < len(TOOL_OUTPUT)
        assert len(out[2]["content"]) < len(TOOL_OUTPUT)
        assert savings["tokens_saved"] > 0

    def test_more_than_the_last_message_survives_compression(self) -> None:
        """`gateway_preserve_cache` compresses only the final message, because
        without markers it cannot know where the prefix ends. With markers it
        can, so several turns of tool output get compressed rather than one."""
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": BIG, "cache_control": {"type": "ephemeral"}}],
            },
            {"role": "assistant", "content": TOOL_OUTPUT},
            {"role": "user", "content": TOOL_OUTPUT},
        ]

        _, out, _ = compress_anthropic_request(_system(cached=True), messages)

        assert len(out[1]["content"]) < len(TOOL_OUTPUT), "the middle turn was skipped"


class TestTheManualSettingStillWorks:
    def test_preserve_cache_protects_an_unmarked_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Someone routing a client that caches without saying so can still ask
        for the conservative behaviour."""
        monkeypatch.setattr(settings, "gateway_preserve_cache", True)
        messages = [
            {"role": "user", "content": TOOL_OUTPUT},
            {"role": "user", "content": TOOL_OUTPUT},
        ]

        system, out, _ = compress_anthropic_request(_system(cached=False), messages)

        assert system[0]["text"] == BIG
        assert out[0]["content"] == TOOL_OUTPUT
        assert len(out[1]["content"]) < len(TOOL_OUTPUT)
