"""Lossless folds: take out repetition, prove the original can be rebuilt.

These run before any lossy compressor and are the only transforms here that
need no marker and no CCR entry. Each fold has an inverse, and a fold is kept
only if ``unfold(fold(text)) == text`` on that exact input — so a payload that
already happens to contain a line shaped like a fold marker just passes
through that fold untouched instead of being corrupted by it.

- **Runs**: N identical consecutive lines become one line plus
  ``(previous line repeated N-1 more times)``.
- **Adjacent blocks**: a block of 2-64 lines repeated back to back becomes one
  copy plus ``(previous L lines repeated K more times)``.
- **Earlier blocks**: a span of at least 4 lines / 160 characters that already
  appeared further up becomes ``(N lines identical to the N lines starting M
  lines above)``. Repeated stack traces, the same warning block from every
  crate, a test fixture printed twice.

``render_terminal`` is not invertible and is applied separately: it strips ANSI
colour codes and resolves carriage-return progress bars to what the terminal
actually showed. Neither carries information a model can use.
"""

from __future__ import annotations

import re

# CSI sequences (colours, cursor moves), OSC (titles, hyperlinks) and the rarer
# two-byte escapes. Linear: every quantifier is over a disjoint class.
_ANSI = re.compile(r"\x1b\[[0-?]*+[ -/]*+[@-~]|\x1b\][^\x07\x1b]*+(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")

_RUN = re.compile(r"^\(previous line repeated (\d+) more times?\)$")
_BLOCK = re.compile(r"^\(previous (\d+) lines repeated (\d+) more times?\)$")
_BACKREF = re.compile(r"^\((\d+) lines identical to the \1 lines starting (\d+) lines above\)$")

MAX_BLOCK = 64
MIN_BACKREF_LINES = 4
MIN_BACKREF_CHARS = 160


def render_terminal(text: str) -> str:
    """What a terminal would have shown: no escape codes, no overwritten bars."""
    if "\x1b" in text:
        text = _ANSI.sub("", text)
    if "\r" in text:
        text = text.replace("\r\n", "\n")
        if "\r" in text:
            # A bare CR returns to column 0 and the next write overwrites: the
            # last segment of the line is what stayed on screen. A trailing CR
            # leaves the line as it was.
            lines = []
            for raw in text.split("\n"):
                if "\r" in raw:
                    parts = [p for p in raw.split("\r") if p]
                    raw = parts[-1] if parts else ""  # noqa: PLW2901
                lines.append(raw)
            text = "\n".join(lines)
    return text


# ─── runs and adjacent blocks ───────────────────────────────────────────────


def _fold_repeats(lines: list[str]) -> list[str]:
    ids: dict[str, int] = {}
    seq = [ids.setdefault(line, len(ids)) for line in lines]
    n = len(lines)
    out: list[str] = []
    i = 0
    while i < n:
        best_len, best_reps, best_gain = 0, 0, 0
        for size in range(1, min(MAX_BLOCK, (n - i) // 2) + 1):
            if seq[i + size] != seq[i] or seq[i : i + size] != seq[i + size : i + 2 * size]:
                continue
            reps = 1
            while seq[i : i + size] == seq[i + (reps + 1) * size : i + (reps + 2) * size]:
                reps += 1
            chars = sum(len(lines[k]) + 1 for k in range(i, i + size))
            gain = chars * reps - 45
            if gain > best_gain:
                best_len, best_reps, best_gain = size, reps, gain
        if best_len == 0:
            out.append(lines[i])
            i += 1
            continue
        out.extend(lines[i : i + best_len])
        if best_len == 1:
            out.append(f"(previous line repeated {best_reps} more time{'s' * (best_reps != 1)})")
        else:
            out.append(
                f"(previous {best_len} lines repeated {best_reps} more time"
                f"{'s' * (best_reps != 1)})"
            )
        i += best_len * (best_reps + 1)
    return out


def _unfold_repeats(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if line.startswith("(previous "):
            m = _RUN.match(line)
            if m and out:
                out.extend([out[-1]] * int(m.group(1)))
                continue
            m = _BLOCK.match(line)
            if m and len(out) >= int(m.group(1)):
                size = int(m.group(1))
                out.extend(out[-size:] * int(m.group(2)))
                continue
        out.append(line)
    return out


# ─── spans that already appeared earlier ────────────────────────────────────


def _fold_backrefs(lines: list[str]) -> list[str]:
    n = len(lines)
    if n < 2 * MIN_BACKREF_LINES:
        return lines
    ids: dict[str, int] = {}
    seq = [ids.setdefault(line, len(ids)) for line in lines]
    k = MIN_BACKREF_LINES
    first: dict[tuple[int, ...], int] = {}
    out: list[str] = []
    i = 0
    while i < n:
        gram = tuple(seq[i : i + k])
        j = first.get(gram) if len(gram) == k else None
        if j is not None and not all(lines[x].strip() == "" for x in range(i, i + k)):
            length = k
            while i + length < n and j + length < i and seq[j + length] == seq[i + length]:
                length += 1
            if j + length <= i:
                chars = sum(len(lines[x]) + 1 for x in range(i, i + length))
                if chars >= MIN_BACKREF_CHARS:
                    for p in range(i, i + length):
                        g = tuple(seq[p : p + k])
                        if len(g) == k:
                            first.setdefault(g, p)
                    out.append(
                        f"({length} lines identical to the {length} lines starting "
                        f"{i - j} lines above)"
                    )
                    i += length
                    continue
        if len(gram) == k:
            first.setdefault(gram, i)
        out.append(lines[i])
        i += 1
    return out


def _unfold_backrefs(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if line.startswith("(") and " lines identical to the " in line:
            m = _BACKREF.match(line)
            if m:
                length, back = int(m.group(1)), int(m.group(2))
                start = len(out) - back
                if start >= 0 and start + length <= len(out):
                    out.extend(out[start : start + length])
                    continue
        out.append(line)
    return out


# ─── public ──────────────────────────────────────────────────────────────────


def fold(text: str) -> str:
    """Every fold that round-trips on this input, applied in order."""
    if text.count("\n") < 2:
        return text
    original = text.split("\n")
    lines = original
    for do, undo in ((_fold_repeats, _unfold_repeats), (_fold_backrefs, _unfold_backrefs)):
        folded = do(lines)
        if len(folded) < len(lines) and undo(folded) == lines:
            lines = folded
    if lines is original:
        return text
    out = "\n".join(lines)
    # Each step round-trips on its own; the composition is checked as well,
    # because a line in the input that merely looks like a run marker would be
    # expanded by the other step's inverse.
    return out if unfold(out) == text else text


def unfold(text: str) -> str:
    """Inverse of :func:`fold`."""
    lines = text.split("\n")
    return "\n".join(_unfold_repeats(_unfold_backrefs(lines)))
