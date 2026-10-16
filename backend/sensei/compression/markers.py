"""The one marker every lossy cut leaves behind, and the context that writes it.

A compressor that drops something must say so, in place, and must say how to
get it back. The format is a contract with the gateway, which injects a
retrieve tool when it sees one and resolves the call from the CCR store::

    [sensei: 37 lines omitted; retrieve ccr=3f9a1c0b7d2e4a65]

- ASCII only, and the description never contains ``[``, ``]``, ``;`` or a
  newline, so :data:`MARKER_RE` finds every marker and nothing else.
- The id is the first 16 hex characters of the SHA-256 of the *whole original
  block*, byte-exact, before any processing. Deterministic on purpose: the same
  tool result must compress to the same bytes on every request, or a marker
  would bust the provider's prompt cache on its own.
- Without a store there is nothing to retrieve from, so the marker drops the
  clause rather than promise something that cannot be honoured.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

MARKER_RE = re.compile(r"\[sensei: ([^\[\]\n;]*)(?:; retrieve ccr=([0-9a-f]{16}))?\]")

_UNSAFE = re.compile(r"[\[\];\n\r]")


def ccr_id_for(original: str) -> str:
    """The deterministic id for one original block."""
    return hashlib.sha256(original.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n:,} {word}"
    suffix = "es" if word.endswith(("ch", "sh", "s", "x")) else "s"
    return f"{n:,} {word}{suffix}"


@dataclass
class Context:
    """Per-call state shared by every compressor that runs on one block.

    ``query`` is whatever the caller knows about what the model is looking for
    (the user's last prompt, the tool call's arguments). Compressors use it to
    decide what to keep; it never changes what counts as lossless.
    """

    ccr_id: str | None = None
    query: str = ""
    lossy: bool = False
    omitted: int = 0
    notes: list[str] = field(default_factory=list)

    def mark(self, what: str, count: int = 1) -> str:
        """Record a lossy cut and return the marker that replaces it."""
        self.lossy = True
        self.omitted += count
        what = _UNSAFE.sub(" ", what).strip()
        if self.ccr_id:
            return f"[sensei: {what}; retrieve ccr={self.ccr_id}]"
        return f"[sensei: {what}]"


def has_marker(text: str) -> bool:
    return "[sensei: " in text and MARKER_RE.search(text) is not None
