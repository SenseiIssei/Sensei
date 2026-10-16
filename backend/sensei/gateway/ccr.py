"""Compression markers, and getting the original back through the gateway.

The marker format is a contract shared with the compression pipeline
(``sensei/compression``)::

    [sensei: <what was cut>; retrieve ccr=<id>]

``<id>`` is the first 16 hex characters of ``sha256(original)``. Deterministic
on purpose: a random id would make the forwarded text differ on every request,
and a prompt cache keyed on bytes would never hit.

Compressors that cut something emit the marker themselves. Where a block came
back smaller with no marker in it — today's prose and log compressors — the
gateway appends one marker for the whole block, so every lossy block in a
forwarded request is retrievable either way.

Originals live in a bounded in-memory map keyed by that id, with the shared
on-disk :class:`~sensei.compression.ccr.CCRStore` (the one ``sensei mcp`` reads)
as the fallback lookup.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from sensei.config import settings

TOOL_NAME = "sensei_retrieve"

MARKER_RE = re.compile(r"\[sensei: ([^\[\]\n;]*); retrieve ccr=([0-9a-f]{16})\]")
# Cheap pre-check before running the regex over a big string.
_NEEDLE = "; retrieve ccr="

TOOL_DESCRIPTION = (
    "Return the exact original text behind a Sensei compression marker. "
    "Some tool results and messages in this conversation were shortened; each "
    "shortened part carries a marker like [sensei: 40 lines omitted; retrieve "
    "ccr=0123456789abcdef]. Call this with that ccr id whenever the shortened "
    "form is missing something you need. Never guess at what was cut."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ccr": {
            "type": "string",
            "description": "The 16-character id after 'ccr=' in a [sensei: ...] marker.",
        },
        "offset": {
            "type": "integer",
            "description": "Character offset to continue from, for very long originals.",
        },
    },
    "required": ["ccr"],
}


def ccr_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def marker(cid: str, what: str) -> str:
    what = re.sub(r"[\[\];\n]", " ", what).strip() or "compressed"
    return f"[sensei: {what}; retrieve ccr={cid}]"


def has_marker(text: str) -> bool:
    return _NEEDLE in text and MARKER_RE.search(text) is not None


def contains_marker(value: Any) -> bool:
    """Whether any string anywhere inside ``value`` carries a marker."""
    if isinstance(value, str):
        return has_marker(value)
    if isinstance(value, dict):
        return any(contains_marker(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_marker(v) for v in value)
    return False


class GatewayCCR:
    """Originals by deterministic id: an LRU bounded by total characters."""

    def __init__(self, max_chars: int = 64 * 1024 * 1024) -> None:
        self._items: OrderedDict[str, str] = OrderedDict()
        self._chars = 0
        self._max = max_chars
        self._lock = threading.Lock()
        self.fallback: Callable[[str], str | None] | None = None

    def put(self, original: str) -> str:
        cid = ccr_id(original)
        with self._lock:
            if cid in self._items:
                self._items.move_to_end(cid)
                return cid
            self._items[cid] = original
            self._chars += len(original)
            while self._chars > self._max and len(self._items) > 1:
                _, old = self._items.popitem(last=False)
                self._chars -= len(old)
        return cid

    def get(self, cid: str) -> str | None:
        with self._lock:
            text = self._items.get(cid)
            if text is not None:
                self._items.move_to_end(cid)
                return text
        if self.fallback is not None:
            try:
                return self.fallback(cid)
            except Exception:  # a broken disk store must not break a turn
                return None
        return None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._chars = 0


store = GatewayCCR()


def annotate(original: str, compressed: str, before: int, after: int) -> str:
    """Make a lossy block retrievable: keep the original, add a marker if the
    compressor did not already put one in.

    Returns the text to forward. Blocks that saved too little to be worth a
    marker come back unchanged — a marker costs ~15 tokens of its own.
    """
    if compressed == original:
        return compressed
    store.put(original)
    if has_marker(compressed) or before - after < settings.gateway_ccr_min_saved_tokens:
        return compressed
    cid = ccr_id(original)
    return f"{compressed}\n{marker(cid, f'compressed view of ~{before:,} tokens')}"


# ── The tool, per wire format ───────────────────────────────────────────────


def tool_definition(api: str) -> dict[str, Any]:
    if api == "anthropic":
        return {"name": TOOL_NAME, "description": TOOL_DESCRIPTION, "input_schema": _SCHEMA}
    if api == "openai":
        return {
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "parameters": _SCHEMA,
            },
        }
    return {
        "type": "function",
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "parameters": _SCHEMA,
    }


def tool_names(api: str, tools: list[Any]) -> set[str]:
    names = set()
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if api == "openai":
            fn = tool.get("function")
            name = fn.get("name") if isinstance(fn, dict) else None
        else:
            name = tool.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def _args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw or "{}")
        except ValueError:
            return {"ccr": raw.strip()}
        return value if isinstance(value, dict) else {}
    return {}


def resolve(raw_args: Any) -> str:
    """Answer one ``sensei_retrieve`` call."""
    args = _args(raw_args)
    cid = str(args.get("ccr") or args.get("ccr_id") or args.get("id") or "").strip().lower()
    match = re.search(r"[0-9a-f]{16}", cid)
    if not match:
        return "[sensei: no ccr id given. Pass the 16-character id from a [sensei: ...] marker]"
    cid = match.group(0)
    text = store.get(cid)
    if text is None:
        return f"[sensei: ccr={cid} expired or unknown]"
    try:
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1000, settings.gateway_retrieve_max_chars)
    page = text[offset : offset + limit]
    end = offset + len(page)
    if end < len(text):
        page += (
            f"\n[sensei: showing chars {offset:,}-{end:,} of {len(text):,}. "
            f"Call {TOOL_NAME} again with offset={end} for the rest]"
        )
    return page
