"""DLP redaction — strip secrets (and optionally PII) from prompts before they
leave the machine. One-way (the real value never reaches the provider).

Default-off (``SENSEI_REDACTION_ENABLED``); PII patterns are additionally gated
behind ``SENSEI_REDACTION_PII`` since they're more prone to false positives.
"""
from __future__ import annotations

import re
from typing import Any

from sensei.config import settings

# High-confidence secret patterns (redacted whenever redaction is enabled).
# Order matters: more specific keys first so they win over generic ones.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
]

# Lower-confidence PII (only when redaction_pii is on).
PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


class Redactor:
    def __init__(self, include_pii: bool | None = None):
        self.include_pii = settings.redaction_pii if include_pii is None else include_pii

    def _patterns(self) -> list[tuple[str, re.Pattern[str]]]:
        return SECRET_PATTERNS + (PII_PATTERNS if self.include_pii else [])

    def redact(self, text: str) -> tuple[str, dict[str, int]]:
        """Return (redacted_text, {category: count})."""
        counts: dict[str, int] = {}
        for name, pat in self._patterns():
            text, n = pat.subn(f"[REDACTED:{name}]", text)
            if n:
                counts[name] = counts.get(name, 0) + n
        return text, counts


def redact_payload(obj: Any, redactor: Redactor | None = None) -> tuple[Any, dict[str, int]]:
    """Recursively redact every string leaf in a request payload.

    Returns the redacted payload and per-category counts. Non-secret strings
    (model names, roles, ...) are untouched since they don't match any pattern.
    """
    r = redactor or Redactor()
    counts: dict[str, int] = {}

    def walk(o: Any) -> Any:
        if isinstance(o, str):
            new, c = r.redact(o)
            for k, v in c.items():
                counts[k] = counts.get(k, 0) + v
            return new
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o

    return walk(obj), counts
