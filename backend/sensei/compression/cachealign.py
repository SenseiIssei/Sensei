from __future__ import annotations

import hashlib
import logging
import re
from collections import OrderedDict
from typing import ClassVar

logger = logging.getLogger(__name__)

# LRU cache size for prefix stabilization
_MAX_PREFIX_CACHE = 128


class CacheAligner:
    """Stabilize prompt prefixes so provider KV caches hit reliably.

    Inspired by Headroom's CacheAligner — ensures that the system prompt
    and early conversation messages maintain a stable byte-for-byte prefix
    across requests, so that provider-side prompt caching (Anthropic, OpenAI,
    Z.ai) actually fires.

    Strategies:
    - Sort system messages to a canonical order
    - Strip volatile metadata (timestamps, request IDs) from system messages
    - Ensure consistent whitespace at message boundaries
    - Cache aligned prefixes for reuse
    """

    # Patterns to strip from system messages (volatile content). Order matters:
    # full ISO datetimes are consumed before bare date / time fragments.
    VOLATILE_PATTERNS: ClassVar[list[str]] = [
        r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[.\d]*Z?\b",  # ISO datetimes
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",  # UUIDs
        r"\b\d{4}-\d{2}-\d{2}\b",  # dates YYYY-MM-DD
        r"\b\d{1,2}:\d{2}:\d{2}\b",  # times HH:MM:SS
        r"\brequest[_-]?id[:\s]+[\w-]+\b",  # Request IDs
        r"\bsession[_-]?id[:\s]+[\w-]+\b",  # Session IDs
        r"\btrace[_-]?id[:\s]+[\w-]+\b",  # Trace IDs
    ]

    def __init__(self) -> None:
        self._prefix_cache: OrderedDict[str, list[dict[str, str]]] = OrderedDict()

    def _strip_volatile(self, text: str) -> str:
        """Remove volatile fragments (timestamps, dates, UUIDs, request IDs)
        so the prompt prefix stays byte-stable across requests."""
        for pattern in self.VOLATILE_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        return text

    def align(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Align messages for optimal KV cache hit rates.

        Args:
            messages: Chat messages in role/content format.

        Returns:
            Aligned messages with stable prefixes.
        """
        if not messages:
            return messages

        # Compute a hash of the message structure for cache lookup
        cache_key = self._compute_key(messages)

        if cache_key in self._prefix_cache:
            # Move to end (LRU). A copy, so a caller that edits the list it got
            # back cannot change what the next caller gets.
            self._prefix_cache.move_to_end(cache_key)
            return [dict(m) for m in self._prefix_cache[cache_key]]

        aligned = self._align_messages(messages)

        # Cache the result
        self._prefix_cache[cache_key] = aligned
        if len(self._prefix_cache) > _MAX_PREFIX_CACHE:
            self._prefix_cache.popitem(last=False)

        return [dict(m) for m in aligned]

    def _align_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Apply alignment transformations."""
        result: list[dict[str, str]] = []

        # Separate system messages from the rest
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        # Sort system messages by content hash for canonical ordering
        system_msgs.sort(
            key=lambda m: hashlib.md5(
                (m.get("content") or "").encode(), usedforsecurity=False
            ).hexdigest()
        )

        # Strip volatile patterns from system messages
        for msg in system_msgs:
            content = self._strip_volatile(msg.get("content") or "").strip()
            if content:
                result.append(
                    {
                        "role": "system",
                        "content": content,
                        **{k: v for k, v in msg.items() if k not in ("role", "content")},
                    }
                )

        # Add other messages in order
        for msg in other_msgs:
            # Ensure consistent whitespace
            content = (msg.get("content") or "").strip()
            result.append(
                {
                    "role": msg.get("role", "user"),
                    "content": content,
                    **{k: v for k, v in msg.items() if k not in ("role", "content")},
                }
            )

        return result

    def _compute_key(self, messages: list[dict[str, str]]) -> str:
        """A cache key that identifies the messages, not just their shape.

        This was ``role:len(content)`` per message, so two different
        conversations whose messages happened to have the same lengths shared
        a key — and the second one was answered with the first one's aligned
        messages. The key now covers every field of every message.
        """
        h = hashlib.sha256()
        for msg in messages:
            for k in sorted(msg):
                v = msg[k]
                h.update(k.encode("utf-8", "surrogatepass"))
                h.update(b"\x1f")
                h.update((v if isinstance(v, str) else repr(v)).encode("utf-8", "surrogatepass"))
                h.update(b"\x1e")
            h.update(b"\x1d")
        return h.hexdigest()
