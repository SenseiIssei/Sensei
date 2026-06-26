"""Request policy — block disallowed models or content before forwarding.

Configured via ``SENSEI_BLOCKED_MODELS`` (comma-separated substrings, matched
case-insensitively against the requested model) and ``SENSEI_BLOCKED_PATTERNS``
(comma-separated regexes matched against any string in the request). Empty
lists allow everything.
"""
from __future__ import annotations

import re
from typing import Any, Iterator

from sensei.config import settings


def _items(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def blocked_model(model: str | None) -> str | None:
    """Return the matching block-rule if `model` is disallowed, else None."""
    if not model:
        return None
    low = model.lower()
    for rule in _items(settings.blocked_models):
        if rule.lower() in low:
            return rule
    return None


def _patterns() -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for p in _items(settings.blocked_patterns):
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error:
            continue
    return out


def _iter_strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for x in obj:
            yield from _iter_strings(x)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)


def check_policy(payload: dict[str, Any]) -> str | None:
    """Return a human-readable reason if the payload violates policy, else None."""
    rule = blocked_model(payload.get("model"))
    if rule:
        return f"Model '{payload.get('model')}' is blocked by policy (matched '{rule}')."

    patterns = _patterns()
    if patterns:
        for text in _iter_strings(payload):
            for pat in patterns:
                if pat.search(text):
                    return f"Request blocked by content policy (matched /{pat.pattern}/)."
    return None
