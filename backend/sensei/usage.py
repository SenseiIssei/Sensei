"""What the provider says it billed — normalised across three wire formats.

The savings ledger has always known what Sensei *removed*. It did not know what
the provider then *charged*, and in particular how much of the prompt it served
from its own prompt cache. That matters for an honest number: a cached token
costs a tenth of a fresh one (or less), so compression that broke caching could
"save" 30% of tokens and still raise the bill. Recording the cache counters next
to the compression counters is what lets the dashboard show both.

Three shapes arrive here:

- **Anthropic Messages** — ``usage.input_tokens`` excludes cached tokens;
  ``cache_read_input_tokens`` and ``cache_creation_input_tokens`` are separate.
- **OpenAI Chat Completions** — ``usage.prompt_tokens`` *includes* cached ones;
  ``prompt_tokens_details.cached_tokens`` says how many.
- **OpenAI Responses** — ``usage.input_tokens`` includes cached ones;
  ``input_tokens_details.cached_tokens`` says how many.

:class:`Usage` stores them one way: ``prompt`` is the whole prompt as billed,
``cache_read`` and ``cache_write`` are the parts of it that were served from or
written to the cache.

Streaming responses carry their usage in an event near the end of the stream.
:class:`UsageSniffer` watches the bytes as they pass through and parses only the
SSE lines that mention ``"usage"``, so the hot path pays for a substring search
per chunk and nothing more.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


@dataclass
class Usage:
    prompt: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def known(self) -> bool:
        return bool(self.prompt or self.output)

    def merge(self, other: Usage) -> None:
        """Take every non-zero field of ``other``.

        Anthropic streams report input and cache counts in ``message_start``
        and the output count in ``message_delta``; neither event alone is the
        whole picture.
        """
        for field in ("prompt", "output", "cache_read", "cache_write"):
            value = getattr(other, field)
            if value:
                setattr(self, field, value)


def from_usage_block(usage: Any) -> Usage:
    """Normalise one ``usage`` object, whichever API it came from."""
    if not isinstance(usage, dict):
        return Usage()

    # Anthropic: the three input counters are disjoint and add up to the prompt.
    if "cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage:
        read = _int(usage.get("cache_read_input_tokens"))
        write = _int(usage.get("cache_creation_input_tokens"))
        return Usage(
            prompt=_int(usage.get("input_tokens")) + read + write,
            output=_int(usage.get("output_tokens")),
            cache_read=read,
            cache_write=write,
        )

    # OpenAI Chat Completions.
    if "prompt_tokens" in usage or "completion_tokens" in usage:
        details = usage.get("prompt_tokens_details") or {}
        return Usage(
            prompt=_int(usage.get("prompt_tokens")),
            output=_int(usage.get("completion_tokens")),
            cache_read=_int(details.get("cached_tokens")) if isinstance(details, dict) else 0,
        )

    # OpenAI Responses, and Anthropic without any cache fields.
    details = usage.get("input_tokens_details") or {}
    return Usage(
        prompt=_int(usage.get("input_tokens")),
        output=_int(usage.get("output_tokens")),
        cache_read=_int(details.get("cached_tokens")) if isinstance(details, dict) else 0,
    )


def from_response(data: Any) -> Usage:
    """Usage from a complete (non-streaming) JSON response body."""
    if not isinstance(data, dict):
        return Usage()
    return from_usage_block(data.get("usage"))


def _usage_in_event(event: dict[str, Any]) -> Usage:
    # Anthropic `message_start` nests usage inside `message`; Responses
    # `response.completed` nests it inside `response`; everything else puts it
    # at the top level.
    for container in ("message", "response"):
        inner = event.get(container)
        if isinstance(inner, dict) and isinstance(inner.get("usage"), dict):
            return from_usage_block(inner["usage"])
    return from_usage_block(event.get("usage"))


class UsageSniffer:
    """Accumulate usage from an SSE byte stream without buffering the stream."""

    # How much of one unterminated SSE line to hold. Not small: the Responses
    # API's `response.completed` event echoes the instructions, tools and the
    # whole output, which for Codex runs to hundreds of kilobytes — and the
    # usage block is inside it. Bounded all the same, so one pathological line
    # cannot turn a proxy into a buffer.
    _MAX_PENDING = 8 * 1024 * 1024

    def __init__(self) -> None:
        self.usage = Usage()
        self._pending = b""

    def feed(self, chunk: bytes) -> None:
        data = self._pending + chunk
        lines = data.split(b"\n")
        self._pending = lines.pop()
        if len(self._pending) > self._MAX_PENDING:
            self._pending = b""
        for line in lines:
            self._line(line)

    def close(self) -> Usage:
        if self._pending:
            self._line(self._pending)
            self._pending = b""
        return self.usage

    def _line(self, line: bytes) -> None:
        if b'"usage"' not in line:
            return
        line = line.strip()
        if not line.startswith(b"data:"):
            return
        try:
            event = json.loads(line[5:].strip())
        except ValueError:
            return
        if isinstance(event, dict):
            self.usage.merge(_usage_in_event(event))
