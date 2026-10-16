"""grep / ripgrep / Grep-tool output.

An agent's search results repeat the file path on every line, and on a broad
search most of the matches are the same hit in a different file. Two stages:

1. **Lossless**: consecutive lines from the same file are grouped under one
   heading, the way ``rg --heading`` prints them. Match and context lines keep
   their ``12:`` / ``12-`` prefix and their content byte for byte, so an
   ``old_string`` copied out of a match still applies. Verified by rebuilding
   the original from the grouped form; if that does not reproduce the input
   exactly, the input is returned.
2. **Lossy, only for big results**: per-file and total caps. The first and
   last hit of each file stay, lines that mention an error or a term from the
   query are preferred, and every cut leaves a marker with the CCR id. Lines
   longer than a screen (a match inside a minified bundle) keep a window around
   the query terms instead of 40 KB of one line.
"""

from __future__ import annotations

import re
from itertools import pairwise

from sensei.compression import dense
from sensei.compression.markers import Context, plural

# path:12:content / path-12-content. The path may carry a drive letter
# (C:\x or C:/x) and must not contain a colon after that. Non-greedy so the
# first `:digits:` or `-digits-` ends it.
_WITH_PATH = re.compile(r"^((?:[A-Za-z]:[\\/])?[^:\n]*?)([:-])(\d+)\2(.*)$")
_NO_PATH = re.compile(r"^(\d+)([:-])(.*)$")
_PATHISH = re.compile(r"^(?:[A-Za-z]:[\\/])?[\w.~@+\-\\/ ]+$")
_GROUPED_LINE = re.compile(r"^\d+[:-]")
_ERRORISH = re.compile(r"\b(?:error|fail|panic|exception|todo|fixme|bug|warn)", re.I)

# Output smaller than this keeps every match; agents narrow searches on purpose
# and a 2 KB result is cheaper to send than to second-guess.
LOSSY_MIN_CHARS = 6000
MAX_FILES = 25
MAX_UNITS_PER_FILE = 6
MAX_UNITS_TOTAL = 60
LONG_LINE = 500
SINGLE_FILE_LOSSY_CHARS = 12000


def _parse(line: str) -> tuple[str, str, str, str] | None:
    m = _WITH_PATH.match(line)
    if not m:
        return None
    path = m.group(1)
    if not path or not _PATHISH.match(path) or path.strip() != path:
        return None
    if not ("/" in path or "\\" in path or "." in path):
        return None
    return path, m.group(2), m.group(3), m.group(4)


def detect(text: str) -> bool:
    """Most non-blank lines are grep hits (with or without a path)."""
    lines = [ln for ln in text.split("\n", 120)[:120] if ln.strip() and ln != "--"]
    if len(lines) < 3:
        return False
    with_path = sum(1 for ln in lines if _parse(ln))
    if with_path >= len(lines) * 0.6:
        return True
    # Single-file `grep -n`: `12:hit` / `13-context`. A timestamped log
    # (`2026-06-26 14:00:01 ...`) has the same shape, so the numbers must also
    # climb the way line numbers do.
    nums = [int(m.group(1)) for ln in lines if (m := _NO_PATH.match(ln)) and len(m.group(1)) < 8]
    if len(nums) < len(lines) * 0.8:
        return False
    rising = sum(1 for a, b in pairwise(nums) if b > a)
    return rising >= (len(nums) - 1) * 0.8


def query_terms(query: str) -> list[str]:
    return dense.query_terms(query)


def elide_long_line(line: str, ctx: Context, terms: list[str]) -> str:
    return dense.elide_line(line, ctx, terms, LONG_LINE)


class SearchCompressor:
    def group(self, text: str) -> str:
        """The lossless stage alone: path headings instead of path prefixes."""
        grouped, changed = _group(text)
        if not changed:
            return text
        return grouped if self.ungroup(grouped) == text else text

    @staticmethod
    def ungroup(grouped: str) -> str:
        lines = grouped.split("\n")
        out: list[str] = []
        current: str | None = None
        for k, line in enumerate(lines):
            if current is not None and _GROUPED_LINE.match(line):
                m = _NO_PATH.match(line)
                if m is None:  # unreachable: _GROUPED_LINE is a prefix of _NO_PATH
                    return grouped
                out.append(f"{current}{m.group(2)}{m.group(1)}{m.group(2)}{m.group(3)}")
                continue
            if line == "--" or not line:
                out.append(line)
                continue
            nxt = lines[k + 1] if k + 1 < len(lines) else ""
            if not _GROUPED_LINE.match(line) and _GROUPED_LINE.match(nxt):
                current = line
                continue
            current = None
            out.append(line)
        return "\n".join(out)

    def compress(self, text: str, ctx: Context | None = None) -> str:
        ctx = ctx or Context()
        terms = query_terms(ctx.query)
        if len(text) >= LOSSY_MIN_CHARS:
            text = self._cap(text, ctx, terms)
        if any(len(ln) > LONG_LINE for ln in text.split("\n")):
            text = "\n".join(elide_long_line(ln, ctx, terms) for ln in text.split("\n"))
        if not ctx.lossy:
            return self.group(text)
        # After a lossy cut there is nothing to verify against, but grouping
        # is still the same mechanical rewrite.
        return _group(text)[0]

    def _cap(self, text: str, ctx: Context, terms: list[str]) -> str:
        """Per-file and total caps over hit *units* (a hit plus its context)."""
        lines = text.split("\n")
        hunked = any(ln == "--" for ln in lines)
        # `grep -n pattern one-file`: no path on any line. Only very large
        # ones are cut; a single-file search is usually a deliberate view.
        single = not any(_parse(ln) for ln in lines[:200]) and len(text) >= SINGLE_FILE_LOSSY_CHARS
        units: list[tuple[str | None, list[str]]] = []
        for line in lines:
            parsed = _parse(line)
            path = parsed[0] if parsed else ("" if single and _NO_PATH.match(line) else None)
            if path is not None and hunked and units and units[-1][0] == path:
                units[-1][1].append(line)
            else:
                units.append((path, [line]))

        by_file: dict[str, list[int]] = {}
        for i, (path, _) in enumerate(units):
            if path is not None:
                by_file.setdefault(path, []).append(i)
        total = sum(len(v) for v in by_file.values())
        if total <= MAX_UNITS_TOTAL and len(by_file) <= MAX_FILES:
            return text

        def score(i: int) -> int:
            body = "\n".join(units[i][1]).lower()
            return 2 * bool(_ERRORISH.search(body)) + sum(1 for t in terms if t in body)

        files = list(by_file)
        order = {f: n for n, f in enumerate(files)}
        if len(files) > MAX_FILES:
            ranked = sorted(files, key=lambda f: (-max(score(i) for i in by_file[f]), order[f]))
            kept_files = set(ranked[:MAX_FILES])
        else:
            kept_files = set(files)
        # The total budget is shared by however many files there are: one file
        # may keep all 60 hits, twenty files keep at least 6 each.
        cap = max(MAX_UNITS_PER_FILE, MAX_UNITS_TOTAL // max(1, len(kept_files)))
        keep: set[int] = set()
        for f in kept_files:
            idx = by_file[f]
            if len(idx) <= cap:
                keep.update(idx)
                continue
            chosen = {idx[0], idx[-1]}
            for i in sorted(idx[1:-1], key=lambda i: (-score(i), i)):
                if len(chosen) >= cap:
                    break
                chosen.add(i)
            keep.update(chosen)

        last_kept = {f: max(j for j in by_file[f] if j in keep) for f in kept_files}
        out: list[str] = []
        for i, (path, body) in enumerate(units):
            if path is None:
                if not (body == ["--"] and out and out[-1] == "--"):
                    out.extend(body)
                continue
            if i not in keep:
                continue
            out.extend(body)
            if last_kept[path] == i:
                n = len(by_file[path]) - sum(1 for j in by_file[path] if j in keep)
                if n:
                    where = f" in {path}" if path else ""
                    out.append(ctx.mark(f"{plural(n, 'more match')}{where} omitted", n))
        skipped = [f for f in files if f not in kept_files]
        if skipped:
            n = sum(len(by_file[f]) for f in skipped)
            what = f"{plural(n, 'match')} in {plural(len(skipped), 'more file')} omitted"
            out.append(ctx.mark(what, n))
        return "\n".join(out)


def _group(text: str) -> tuple[str, bool]:
    out: list[str] = []
    current: str | None = None
    changed = False
    for line in text.split("\n"):
        parsed = _parse(line)
        if parsed is None:
            if line != "--" and line:
                # Anything that is not a hit ends the group, so whatever follows
                # starts with its path in full again.
                current = None
            out.append(line)
            continue
        path, sep, num, content = parsed
        if path != current:
            out.append(path)
            current = path
        else:
            changed = True
        out.append(f"{num}{sep}{content}")
    return "\n".join(out), changed
