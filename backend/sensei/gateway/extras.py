"""Opt-in gateway features: model router, exact response cache, tool budgets.

All three are off by default. Each one changes something the user is paying
for — which model answers, whether the provider is asked at all, whether a
request is refused — and that is the user's decision, not a default.

**Model router.** ``gateway_model_router`` is a JSON list of rules, checked in
order; the first that matches sets the model::

    [{"to_model": "claude-haiku-5-5", "from_models": ["claude-opus-5-5"],
      "max_input_tokens": 4000, "require_no_tools": true}]

Conditions: ``from_models`` (the requested model is one of these),
``max_input_tokens`` (estimated prompt after compression), ``require_no_tools``
(the request declares no tools), ``tool_results_only`` (the newest turn carries
nothing but tool results — an agent reading output, not a person asking).
Prompt caches are per model, so a routed turn starts a cold cache on the
other model; route short turns, not long ones. The routed model is in the
ledger's model column and in ``X-Sensei-Routed-From``.

**Response cache.** Exact match on the request as forwarded, for non-streaming
requests at ``temperature: 0``. Retries, CI and evals send the same request
again; those are answered from memory with ``X-Sensei-Cache: hit``. In memory
only, LRU-bounded, with a TTL.

**Tool budgets.** ``gateway_tool_budgets`` caps the prompt tokens a tool may
send per rolling window, e.g. ``"Claude Code=5000000,Cursor=1000000"``. Over
budget, the request is refused with 429 and a message that says which budget,
how much was used, and how to raise it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict, deque
from typing import Any

from sensei.config import settings
from sensei.gateway import wire
from sensei.gateway.session import canon, digest

logger = logging.getLogger(__name__)

clock = time.time


# ── Model router ────────────────────────────────────────────────────────────


def _rules() -> list[dict[str, Any]]:
    raw = settings.gateway_model_router.strip()
    if not raw:
        return []
    try:
        rules = json.loads(raw)
    except ValueError:
        logger.warning("SENSEI_GATEWAY_MODEL_ROUTER is not valid JSON — routing disabled")
        return []
    if isinstance(rules, dict):
        rules = [rules]
    return [r for r in rules if isinstance(r, dict) and isinstance(r.get("to_model"), str)]


def _tool_results_only(api: str, messages: list[Any]) -> bool:
    if not messages:
        return False
    last = messages[-1]
    if api == "anthropic":
        content = last.get("content") if isinstance(last, dict) else None
        return (
            isinstance(content, list)
            and bool(content)
            and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        )
    if api == "openai":
        return isinstance(last, dict) and last.get("role") in ("tool", "function")
    return isinstance(last, dict) and last.get("type") in wire.RESPONSES_TOOL_OUTPUTS


def route_model(api: str, payload: dict[str, Any]) -> str | None:
    """The model this request should go to instead, or None."""
    rules = _rules()
    if not rules:
        return None
    model = str(payload.get("model") or "")
    messages = payload.get("input" if api == "responses" else "messages") or []
    if not isinstance(messages, list):
        messages = []
    tokens = len(canon([payload.get("system"), payload.get("instructions"), messages])) // 4
    has_tools = bool(payload.get("tools"))
    for rule in rules:
        froms = rule.get("from_models")
        if isinstance(froms, list) and froms and model not in froms:
            continue
        limit = rule.get("max_input_tokens")
        if isinstance(limit, int) and tokens > limit:
            continue
        if rule.get("require_no_tools") and has_tools:
            continue
        if rule.get("tool_results_only") and not _tool_results_only(api, messages):
            continue
        target = rule["to_model"]
        return target if target != model else None
    return None


# ── Exact response cache ────────────────────────────────────────────────────


def cacheable(payload: dict[str, Any]) -> bool:
    if not settings.gateway_response_cache or payload.get("stream"):
        return False
    if payload.get("temperature") != 0:
        return False
    n = payload.get("n")
    return n in (None, 1)


class ResponseCache:
    def __init__(self) -> None:
        self._items: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(api: str, path: str, payload: dict[str, Any], auth: str) -> str:
        # The credential is part of the key, hashed: one user's cached answer
        # is never served to another key.
        return digest([api, path, digest(auth), payload])

    def get(self, key: str) -> dict[str, Any] | None:
        now = clock()
        with self._lock:
            item = self._items.get(key)
            if item is None or now - item[0] > settings.gateway_response_cache_ttl_seconds:
                if item is not None:
                    del self._items[key]
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return json.loads(json.dumps(item[1]))

    def put(self, key: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = (clock(), json.loads(json.dumps(data)))
            self._items.move_to_end(key)
            while len(self._items) > max(1, settings.gateway_response_cache_max_entries):
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.hits = self.misses = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": settings.gateway_response_cache,
                "entries": len(self._items),
                "hits": self.hits,
                "misses": self.misses,
            }


response_cache = ResponseCache()


# ── Tool budgets ────────────────────────────────────────────────────────────


def budgets() -> dict[str, int]:
    out: dict[str, int] = {}
    for part in settings.gateway_tool_budgets.split(","):
        name, sep, value = part.rpartition("=")
        if not sep:
            continue
        try:
            out[name.strip().lower()] = int(value.strip().replace("_", ""))
        except ValueError:
            logger.warning("Ignoring tool budget %r — not a number", part.strip())
    return out


class BudgetMeter:
    """Prompt tokens per tool over a rolling window, in memory."""

    def __init__(self) -> None:
        self._events: dict[str, deque[tuple[float, int]]] = {}
        self._lock = threading.Lock()

    def _window(self) -> float:
        return max(0.01, settings.gateway_tool_budget_window_hours) * 3600

    def used(self, tool: str) -> int:
        now = clock()
        with self._lock:
            events = self._events.get(tool.lower())
            if not events:
                return 0
            while events and now - events[0][0] > self._window():
                events.popleft()
            return sum(n for _, n in events)

    def add(self, tool: str, tokens: int) -> None:
        if tokens <= 0:
            return
        with self._lock:
            self._events.setdefault(tool.lower(), deque()).append((clock(), tokens))

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def check(self, tool: str) -> dict[str, Any] | None:
        """None when within budget, else the details for the 429."""
        limits = budgets()
        if not limits:
            return None
        limit = limits.get((tool or "unknown").lower())
        if limit is None:
            limit = limits.get("*")
        if limit is None:
            return None
        used = self.used(tool or "unknown")
        if used < limit:
            return None
        hours = settings.gateway_tool_budget_window_hours
        return {
            "tool": tool or "unknown",
            "used": used,
            "limit": limit,
            "message": (
                f"Sensei budget for '{tool or 'unknown'}' reached: {used:,} of {limit:,} prompt "
                f"tokens in the last {hours:g}h. Raise it in SENSEI_GATEWAY_TOOL_BUDGETS, or wait "
                f"for older requests to leave the window."
            ),
        }


budget_meter = BudgetMeter()
