"""The live zone: compress only what is new, replay everything else.

A coding agent resends the whole conversation on every turn, and the provider
caches on an exact byte prefix. Sensei's compression is deterministic, so in
principle recompressing everything reproduces last turn's bytes — but "in
principle" breaks the first time anything position-dependent happens: a marker
that depends on what came before, a Sensei upgrade that changes a compressor,
a stale-read stub that only exists because of a later edit. And on the newest
Claude models, history that differs from what was sent is not just a cache
miss: a thinking block records the prefix that produced it, and a changed
prefix is a 400 on accounts that are enforced.

So per conversation ("lineage"), this module remembers what was actually
forwarded, message by message. When the next request starts with the same
messages, their forwarded form is replayed verbatim and only the delta is
compressed. When it does not, the longest common prefix is still replayed, and
the miss is attributed:

- ``cold_start`` — no record of this conversation (first turn, or after a
  restart or eviction).
- ``ttl`` — the record exists but the provider's cache has expired since.
- ``prefix_change`` — an earlier message, the system prompt or the tool list
  changed (client-side compaction, an MCP server connecting).
- ``hit`` — append-only extension within the cache lifetime.

``cache_control`` markers are not part of the replayed bytes: clients move
them every turn (Claude Code puts one on the last message), so messages are
hashed and stored without them and the current request's markers are put back
on at assembly. Moving a marker invalidates neither the cache nor thinking.

The store is in memory only, bounded by entry count and by size, and expires
entries after ``gateway_live_zone_ttl_seconds``. Nothing is written to disk.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any

from sensei.config import settings

# Patchable in tests and in the replay harness, which runs on recorded time.
clock = time.time

Path = tuple[Any, ...]


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    """A content fingerprint: keys lineages and replayed messages, nothing more.

    Never applied to a credential — the response cache tags those with a keyed
    HMAC (``extras.credential_tag``). Fast on purpose: it runs on every message
    of every request, and its only job is telling two byte strings apart.
    """
    return hashlib.blake2b(
        canon(value).encode("utf-8", "surrogatepass"), digest_size=16
    ).hexdigest()


# ── cache_control: stripped for hashing and storage, re-applied per request ──


def strip_cache_control(value: Any, path: Path = ()) -> tuple[Any, list[tuple[Path, Any]]]:
    """A copy of ``value`` with every ``cache_control`` removed, plus where they were."""
    marks: list[tuple[Path, Any]] = []
    if isinstance(value, dict):
        if not any(isinstance(v, (dict, list)) for v in value.values()) and (
            "cache_control" not in value
        ):
            return value, marks
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k == "cache_control":
                marks.append((path, v))
                continue
            new, sub = strip_cache_control(v, (*path, k))
            out[k] = new
            marks.extend(sub)
        return (out if marks else value), marks
    if isinstance(value, list):
        items = []
        for i, v in enumerate(value):
            new, sub = strip_cache_control(v, (*path, i))
            items.append(new)
            marks.extend(sub)
        return (items if marks else value), marks
    return value, marks


def apply_cache_control(value: Any, marks: list[tuple[Path, Any]]) -> Any:
    """Put markers back, copying only along the paths that change.

    A path that no longer exists in the forwarded form (compression merged or
    dropped a part) is skipped rather than guessed at.
    """
    for path, mark in marks:
        value = _set_path(value, path, mark)
    return value


def _set_path(value: Any, path: Path, mark: Any) -> Any:
    if not path:
        if isinstance(value, dict):
            return {**value, "cache_control": mark}
        return value
    head, rest = path[0], path[1:]
    if isinstance(value, dict) and isinstance(head, str) and head in value:
        return {**value, head: _set_path(value[head], rest, mark)}
    if isinstance(value, list) and isinstance(head, int) and 0 <= head < len(value):
        out = list(value)
        out[head] = _set_path(value[head], rest, mark)
        return out
    return value


def request_cache_ttl(body: dict[str, Any], marks: list[list[tuple[Path, Any]]]) -> float:
    """How long the provider will keep this prefix, as far as the request says."""
    if body.get("prompt_cache_retention") == "24h":  # OpenAI extended retention
        return 86_400.0
    for message_marks in marks:
        for _, mark in message_marks:
            if isinstance(mark, dict) and mark.get("ttl") == "1h":
                return 3600.0
    for item in (body.get("system"), body.get("tools")):
        _, found = strip_cache_control(item) if item is not None else (None, [])
        if any(isinstance(m, dict) and m.get("ttl") == "1h" for _, m in found):
            return 3600.0
    return float(max(1, settings.gateway_cache_ttl_seconds))


# ── The store ───────────────────────────────────────────────────────────────


@dataclass
class Entry:
    key: str
    hashes: list[str]
    groups: list[list[dict[str, Any]]]
    head: str
    last_seen: float
    cache_ttl: float
    size: int
    cached_tokens: int | None = None
    turns: int = 1
    sticky: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    """What to replay and what to compress for one request."""

    key: str
    cause: str
    reuse: int
    groups: list[list[dict[str, Any]]]
    hashes: list[str]
    stripped: list[Any]
    marks: list[list[tuple[Path, Any]]]
    head: str
    cache_ttl: float
    size: int
    frozen: int = 0
    previous_cached: int | None = None
    sticky: dict[str, Any] = field(default_factory=dict)


def lineage_key(api: str, system: Any, first: Any, flags: str = "") -> str:
    system_s, _ = strip_cache_control(system)
    first_s, _ = strip_cache_control(first)
    return digest([api, flags, system_s, first_s])


def _has_thinking(message: Any) -> bool:
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking") for b in content
    )


class LiveZone:
    def __init__(self) -> None:
        self._entries: OrderedDict[str, Entry] = OrderedDict()
        self._expansions: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()
        self.causes: Counter[str] = Counter()
        self.replayed_messages = 0
        self.compressed_messages = 0

    # ---- planning ----------------------------------------------------------

    def plan(
        self,
        *,
        api: str,
        key: str,
        head: Any,
        messages: list[Any],
        body: dict[str, Any],
    ) -> Plan:
        stripped: list[Any] = []
        marks: list[list[tuple[Path, Any]]] = []
        hashes: list[str] = []
        size = 0
        for message in messages:
            s, m = strip_cache_control(message)
            text = canon(s)
            size += len(text)
            stripped.append(s)
            marks.append(m)
            hashes.append(
                hashlib.blake2b(text.encode("utf-8", "surrogatepass"), digest_size=16).hexdigest()
            )
        head_s, _ = strip_cache_control(head)
        head_hash = digest(head_s)
        ttl = request_cache_ttl(body, marks)
        now = clock()

        with self._lock:
            self._expire(now)
            entry = self._entries.get(key)
            if entry is None:
                cause, reuse, groups, previous = "cold_start", 0, [], None
                sticky: dict[str, Any] = {}
            else:
                self._entries.move_to_end(key)
                reuse = 0
                limit = min(len(entry.hashes), len(hashes))
                while reuse < limit and entry.hashes[reuse] == hashes[reuse]:
                    reuse += 1
                groups = entry.groups[:reuse]
                previous = entry.cached_tokens
                sticky = dict(entry.sticky)
                if now - entry.last_seen > entry.cache_ttl:
                    cause = "ttl"
                elif reuse < len(entry.hashes) or entry.head != head_hash:
                    cause = "prefix_change"
                else:
                    cause = "hit"

        plan = Plan(
            key=key,
            cause=cause,
            reuse=reuse,
            groups=groups,
            hashes=hashes,
            stripped=stripped,
            marks=marks,
            head=head_hash,
            cache_ttl=ttl,
            size=size,
            previous_cached=previous,
            sticky=sticky,
        )
        plan.frozen = self._frozen(plan, messages)
        return plan

    @staticmethod
    def _frozen(plan: Plan, messages: list[Any]) -> int:
        """Messages before this index must not be rewritten after the fact.

        Replayed messages are frozen when the provider is caching them or when
        thinking binds them; everything before the last thinking block is bound
        regardless; and on a cold start, the client's own cache breakpoints say
        how far the provider may already hold this prefix.
        """
        frozen = plan.reuse
        thinking_at = max((i for i, m in enumerate(messages) if _has_thinking(m)), default=-1)
        marked_at = max((i for i, m in enumerate(plan.marks) if m), default=-1)
        uncached = plan.previous_cached == 0 and marked_at < 0
        if uncached and thinking_at < 0:
            # The provider reported caching nothing last turn and nothing asks
            # for it now: rewriting the old turns costs nothing.
            frozen = 0
        frozen = max(frozen, thinking_at + 1, marked_at)
        return min(frozen, len(messages))

    # ---- committing --------------------------------------------------------

    def commit(self, plan: Plan, groups: list[list[dict[str, Any]]]) -> None:
        if len(groups) != len(plan.hashes):
            return
        now = clock()
        with self._lock:
            old = self._entries.pop(plan.key, None)
            if old is not None:
                self._size -= old.size
            entry = Entry(
                key=plan.key,
                hashes=plan.hashes,
                groups=groups,
                head=plan.head,
                last_seen=now,
                cache_ttl=plan.cache_ttl,
                size=plan.size,
                cached_tokens=old.cached_tokens if old is not None else None,
                turns=(old.turns + 1) if old is not None else 1,
                sticky=dict(plan.sticky),
            )
            self._entries[plan.key] = entry
            self._size += entry.size
            self.causes[plan.cause] += 1
            self.replayed_messages += plan.reuse
            self.compressed_messages += len(groups) - plan.reuse
            self._evict()

    def observe_usage(self, key: str, cache_read: int, cache_write: int, known: bool) -> None:
        """What the provider said it cached, for the next turn's frozen boundary."""
        if not known:
            return
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.cached_tokens = max(0, cache_read) + max(0, cache_write)

    # ---- hidden retrieve rounds -------------------------------------------

    def remember_expansion(self, fingerprint: str, messages: list[dict[str, Any]]) -> None:
        with self._lock:
            self._expansions[fingerprint] = messages
            self._expansions.move_to_end(fingerprint)
            while len(self._expansions) > 512:
                self._expansions.popitem(last=False)

    def expansion(self, fingerprint: str) -> list[dict[str, Any]] | None:
        with self._lock:
            return self._expansions.get(fingerprint)

    # ---- housekeeping ------------------------------------------------------

    def _expire(self, now: float) -> None:
        ttl = max(60, settings.gateway_live_zone_ttl_seconds)
        stale = [k for k, e in self._entries.items() if now - e.last_seen > ttl]
        for k in stale:
            self._size -= self._entries.pop(k).size

    def _evict(self) -> None:
        max_entries = max(1, settings.gateway_live_zone_max_sessions)
        max_size = max(1, settings.gateway_live_zone_max_mb) * 1024 * 1024
        while self._entries and (len(self._entries) > max_entries or self._size > max_size):
            _, entry = self._entries.popitem(last=False)
            self._size -= entry.size

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._expansions.clear()
            self._size = 0
            self.causes.clear()
            self.replayed_messages = 0
            self.compressed_messages = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = sum(self.causes.values())
            return {
                "enabled": settings.gateway_live_zone,
                "conversations": len(self._entries),
                "approx_bytes": self._size,
                "requests": total,
                "causes": dict(self.causes),
                "append_only_rate": round(self.causes["hit"] / total, 4) if total else None,
                "replayed_messages": self.replayed_messages,
                "compressed_messages": self.compressed_messages,
            }


live_zone = LiveZone()
