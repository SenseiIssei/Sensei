"""Lines nobody reads in full: minified bundles, base64 blobs, data URIs.

A grep hit inside a minified bundle is one 40 KB line, and a screenshot pasted
into a JSON response is 200 KB of base64. The model needs to know the thing is
there and what surrounds the part it searched for, not every byte of it.

- A base64 run of 256+ characters keeps its first 24 characters and is
  replaced by a marker with its length.
- A dense line (300+ characters, under 6% spaces) keeps its head, its tail and
  a window around every query term it contains.

Both are cuts and carry the CCR id.
"""

from __future__ import annotations

import re

from sensei.compression.markers import Context

_B64 = re.compile(r"(?:data:[\w/+.-]+;base64,)?[A-Za-z0-9+/_-]{256,}={0,2}")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

DENSE_MIN = 300
DENSE_SPACE_RATIO = 0.06
HEAD = 160
TAIL = 80
WINDOW = 140

_STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "are",
        "was",
        "were",
        "not",
        "you",
        "your",
        "have",
        "has",
        "had",
        "grep",
        "head",
        "tail",
        "sed",
        "cat",
        "find",
        "echo",
        "include",
        "exclude",
        "type",
    ]
)


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for w in _WORD.findall(query or ""):
        lw = w.lower()
        if lw not in _STOP and lw not in terms:
            terms.append(lw)
    return terms[:24]


def _looks_base64(s: str) -> bool:
    # Real base64 mixes cases and digits; a long identifier or a hex hash does not.
    body = s.split(",", 1)[-1] if s.startswith("data:") else s
    has_upper = any(c.isupper() for c in body[:400])
    has_lower = any(c.islower() for c in body[:400])
    has_digit = any(c.isdigit() for c in body[:400])
    return has_upper and has_lower and has_digit


def elide_blobs(text: str, ctx: Context) -> str:
    if len(text) < 256:
        return text

    def repl(m: re.Match[str]) -> str:
        s = m.group(0)
        if not _looks_base64(s):
            return s
        keep = s.index(",") + 25 if s.startswith("data:") else 24
        return s[:keep] + ctx.mark(f"base64 blob of {len(s):,} chars elided")

    return _B64.sub(repl, text)


def is_dense(line: str) -> bool:
    return len(line) >= DENSE_MIN and line.count(" ") < len(line) * DENSE_SPACE_RATIO


def elide_line(line: str, ctx: Context, terms: list[str], limit: int = DENSE_MIN) -> str:
    """Keep the head, the tail and a window around each query hit."""
    if len(line) <= limit:
        return line
    low = line.lower()
    spans: list[tuple[int, int]] = [(0, HEAD)]
    for t in terms:
        start = 0
        for _ in range(3):
            k = low.find(t, start)
            if k < 0:
                break
            spans.append((max(0, k - WINDOW // 2), min(len(line), k + len(t) + WINDOW // 2)))
            start = k + len(t)
    spans.append((max(0, len(line) - TAIL), len(line)))
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 40:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    if sum(b - a for a, b in merged) >= len(line) - 120:
        return line
    out: list[str] = []
    prev = 0
    for a, b in merged:
        if a > prev:
            out.append(ctx.mark(f"{a - prev:,} chars elided"))
        out.append(line[a:b])
        prev = b
    return "".join(out)


def elide_dense(text: str, ctx: Context, *, all_long: int = 0) -> str:
    """Blobs first, then every dense line (or every line over ``all_long``)."""
    text = elide_blobs(text, ctx)
    if len(text) < DENSE_MIN:
        return text
    terms = query_terms(ctx.query)
    lines = text.split("\n")
    changed = False
    for i, line in enumerate(lines):
        if len(line) >= DENSE_MIN and (is_dense(line) or (all_long and len(line) > all_long)):
            new = elide_line(line, ctx, terms)
            if new is not line:
                lines[i] = new
                changed = True
    return "\n".join(lines) if changed else text
