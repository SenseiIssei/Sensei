"""The replay harness's stand-in for Anthropic's prompt-cache accounting.

The cost numbers in the gateway results come from this emulator, so it is
tested against the behaviour it claims to model: a prefix written at a
breakpoint is read back by a longer request, a changed byte anywhere earlier
is a miss, and an entry expires after its TTL unless it is read.
"""

from __future__ import annotations

from benchmarks.gateway_replay import IMAGE_TOKENS, CacheEmulator, requests_from_transcript


def _req(*texts: str) -> dict:
    content = [{"type": "text", "text": t} for t in texts]
    content[-1]["cache_control"] = {"type": "ephemeral"}
    return {"messages": [{"role": "user", "content": content}]}


LONG = "word " * 3000


def test_extension_reads_the_written_prefix() -> None:
    em = CacheEmulator(ttl=300, min_tokens=100)
    first = em.charge(_req(LONG), 0)
    assert first["cache_creation_input_tokens"] > 0 and first["cache_read_input_tokens"] == 0
    second = em.charge(_req(LONG, "more text"), 10)
    assert second["cache_read_input_tokens"] == first["cache_creation_input_tokens"]
    assert second["cache_creation_input_tokens"] < 10


def test_an_earlier_change_is_a_miss() -> None:
    em = CacheEmulator(ttl=300, min_tokens=100)
    em.charge(_req(LONG, "b"), 0)
    again = em.charge(_req(LONG.replace("word", "w0rd", 1), "b", "c"), 10)
    assert again["cache_read_input_tokens"] == 0


def test_entries_expire_unless_read() -> None:
    em = CacheEmulator(ttl=300, min_tokens=100)
    em.charge(_req(LONG), 0)
    assert em.charge(_req(LONG, "x"), 200)["cache_read_input_tokens"] > 0  # refreshes
    assert em.charge(_req(LONG, "x", "y"), 450)["cache_read_input_tokens"] > 0
    assert em.charge(_req(LONG, "x", "y", "z"), 2000)["cache_read_input_tokens"] == 0


def test_images_cost_a_flat_rate() -> None:
    em = CacheEmulator(min_tokens=1)
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "image", "source": {"type": "base64", "data": "A" * 400_000}}],
            }
        ]
    }
    usage = em.charge(body, 0)
    assert usage["input_tokens"] == IMAGE_TOKENS


def test_transcript_turns(tmp_path) -> None:
    import json

    lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": "hi"},
            "timestamp": "2026-10-16T10:00:00Z",
        },
        {
            "type": "assistant",
            "requestId": "r1",
            "message": {
                "id": "m1",
                "role": "assistant",
                "content": [{"type": "text", "text": "a"}],
            },
            "timestamp": "2026-10-16T10:00:01Z",
        },
        {
            "type": "assistant",
            "requestId": "r1",
            "message": {
                "id": "m1",
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}],
            },
        },
        {"type": "user", "isSidechain": True, "message": {"role": "user", "content": "ignored"}},
        {
            "type": "assistant",
            "requestId": "r2",
            "message": {
                "id": "m2",
                "role": "assistant",
                "content": [{"type": "text", "text": "b"}],
            },
            "timestamp": "2026-10-16T10:00:05Z",
        },
    ]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    turns = requests_from_transcript(str(path), 10)
    assert len(turns) == 2
    assert [m["role"] for m in turns[1][1]] == ["user", "assistant", "user"]
    assert [b["type"] for b in turns[1][1][1]["content"]] == ["text", "tool_use"]
