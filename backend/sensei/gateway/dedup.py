"""Cross-turn deduplication, and stubs for reads that an edit made stale.

Agents repeat themselves. They re-read a file they read ten turns ago, re-run
``git status``, re-run the same failing test. Per-block compression cannot see
that — each block is compressed on its own — so the repeat is paid for in full.

**Dedup** replaces, in a *new* tool result, any run of at least
``gateway_dedup_min_lines`` lines (and ``gateway_dedup_min_chars`` characters)
that already appeared verbatim in an earlier tool result the model can see,
with a one-line reference to it. A result identical to an earlier one becomes
a single line. The index is built from the forwarded text, not the original,
so a reference always points at bytes that are actually in the context.

Only new messages are ever deduplicated, and only against messages before
them, so the outcome for a message depends on nothing that comes later. That
makes it reproducible: computed incrementally turn by turn or all at once after
a restart, the bytes are the same.

**Stale reads** are the one retroactive edit: a Read of a file that was later
edited no longer shows the file, and can become a stub with a retrieve marker.
Rewriting an old message breaks the provider's cache and, on Claude, the
binding of every thinking block after it. So the caller only offers messages
past the live zone's frozen boundary — in practice: conversations whose
provider reported caching nothing and that carry no thinking blocks.
"""

from __future__ import annotations

import hashlib
import re

from sensei.gateway import ccr

READ_TOOLS = frozenset({"read", "read_file", "readfile", "view", "view_file", "open_file"})
WRITE_TOOLS = frozenset(
    {
        "edit",
        "multiedit",
        "write",
        "edit_file",
        "write_file",
        "create_file",
        "str_replace_editor",
        "str_replace_based_edit_tool",
        "notebookedit",
        "apply_diff",
    }
)
_PATH_KEYS = ("file_path", "path", "notebook_path", "filename", "target_file")


def _sh(lines: list[str]) -> bytes:
    return hashlib.blake2b(
        "\n".join(lines).encode("utf-8", "surrogatepass"), digest_size=8
    ).digest()


def _anchor(line: str) -> str:
    line = re.sub(r"[\[\];\"]", "'", line.strip())
    return line[:48] + ("…" if len(line) > 48 else "")


class DedupIndex:
    """Lines of the tool results seen so far in one conversation."""

    def __init__(self, min_lines: int, min_chars: int) -> None:
        self.k = max(2, min_lines)
        self.min_chars = max(1, min_chars)
        self._exact: dict[bytes, str] = {}
        self._shingles: dict[bytes, tuple[int, int]] = {}
        self._texts: list[list[str]] = []
        self._labels: list[str] = []

    def add(self, text: str, label: str) -> None:
        if len(text) < self.min_chars:
            return
        lines = text.split("\n")
        tid = len(self._texts)
        self._texts.append(lines)
        self._labels.append(label)
        self._exact[_sh(lines)] = label
        for i in range(len(lines) - self.k + 1):
            # Most recent occurrence wins: it is the one most likely to still
            # be in the context after a client compacts its history.
            self._shingles[_sh(lines[i : i + self.k])] = (tid, i)

    def apply(self, text: str) -> str:
        """``text`` with repeats of earlier results replaced by references."""
        if len(text) < self.min_chars or not self._texts:
            return text
        lines = text.split("\n")
        label = self._exact.get(_sh(lines))
        if label is not None:
            return f"[sensei: identical to the earlier {label} ({len(lines)} lines, unchanged)]"
        if len(lines) < self.k:
            return text
        out: list[str] = []
        i = 0
        changed = False
        n = len(lines)
        while i < n:
            if i + self.k <= n:
                hit = self._shingles.get(_sh(lines[i : i + self.k]))
                if hit is not None:
                    tid, j = hit
                    prior = self._texts[tid]
                    run = 0
                    while i + run < n and j + run < len(prior) and lines[i + run] == prior[j + run]:
                        run += 1
                    span = lines[i : i + run]
                    if run >= self.k and sum(len(s) + 1 for s in span) >= self.min_chars:
                        out.append(
                            f"[sensei: {run} lines identical to lines {j + 1}-{j + run} of the "
                            f'earlier {self._labels[tid]}, from "{_anchor(span[0])}" to '
                            f'"{_anchor(span[-1])}"]'
                        )
                        i += run
                        changed = True
                        continue
            out.append(lines[i])
            i += 1
        return "\n".join(out) if changed else text


def file_of(args: dict) -> str | None:
    for key in _PATH_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def stale_stub(path: str, original: str) -> str:
    cid = ccr.store.put(original)
    return ccr.marker(cid, f"stale Read of {path} - the file was edited later, read it again")
