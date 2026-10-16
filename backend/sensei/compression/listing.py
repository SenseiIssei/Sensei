"""Directory listings: ``find``, ``ls -la``, ``tree``, Glob results, ``dir``.

A path list repeats its directory on every line. Grouping it by directory
(lossless, verified by rebuilding the list) usually halves it. ``ls -l``
columns that are the same on every row (permissions, links, owner, group) are
hoisted into one header line. Only very long listings are cut, and only in the
middle of a directory, with a marker.
"""

from __future__ import annotations

import re

from sensei.compression.markers import Context, plural

_LS_LONG = re.compile(
    r"^([dlcbps-][rwxsStT-]{9}[.+@]?)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\d+)\s+"
    r"(\w{3}\s+\d{1,2}\s+(?:\d{1,2}:\d{2}|\d{4}))\s(.+)$"
)
_PATH_LINE = re.compile(
    r"^(?:[A-Za-z]:[\\/]|\.{0,2}[\\/]|~[\\/])?[\w.@+\-~ ()\[\],&#$%!']+(?:[\\/][\w.@+\-~ ()\[\],&#$%!']*)+$"
)
_TREE = re.compile(r"^[\s│├└─|`\\+-]*[├└|`+\\][─-]{2}")

MAX_PER_DIR = 40
LOSSY_MIN_LINES = 400


def detect(text: str) -> bool:
    lines = [ln for ln in text.split("\n", 200)[:200] if ln.strip()]
    if len(lines) < 6:
        return False
    tree = sum(1 for ln in lines if _TREE.match(ln))
    if tree >= len(lines) * 0.5:
        return True
    long_ls = sum(1 for ln in lines if _LS_LONG.match(ln) or ln.startswith("total "))
    if long_ls >= len(lines) * 0.7:
        return True
    paths = sum(1 for ln in lines if _PATH_LINE.match(ln.strip()) and " " not in ln.strip())
    return paths >= len(lines) * 0.8


def _split(path: str) -> tuple[str, str]:
    k = max(path.rfind("/"), path.rfind("\\"))
    if k < 0:
        return "", path
    return path[: k + 1], path[k + 1 :]


class ListingCompressor:
    def compress(self, text: str, ctx: Context | None = None, *, edit_target: bool = False) -> str:
        ctx = ctx or Context()
        if any(_LS_LONG.match(ln) for ln in text.split("\n", 20)[:20]):
            return self._ls_long(text)
        lines = text.split("\n")
        if sum(1 for ln in lines if _TREE.match(ln)) >= len(lines) * 0.5:
            return self._cap_plain(lines, ctx) if len(lines) > LOSSY_MIN_LINES else text
        # A plain list of paths read as a tool result may be a file
        # (.gitignore, CODEOWNERS, a manifest): it stays byte-exact. `ls -l`
        # and `tree` output above are never files anyone edits.
        if edit_target:
            return text
        grouped = self._group_paths(lines)
        out = grouped if grouped is not None and self._ungroup(grouped) == lines else lines
        if len(out) > LOSSY_MIN_LINES:
            return self._cap_grouped(out, ctx)
        return "\n".join(out)

    # ─── path lists ──────────────────────────────────────────────────────────

    @staticmethod
    def _group_paths(lines: list[str]) -> list[str] | None:
        """``a/b/c.txt`` lines become ``a/b/`` headings with indented names."""
        out: list[str] = []
        current: str | None = None
        grouped_any = False
        for line in lines:
            if not line or line != line.strip() or not _PATH_LINE.match(line):
                current = None
                out.append(line)
                continue
            head, name = _split(line)
            if not head or not name:
                current = None
                out.append(line)
                continue
            if head != current:
                out.append(head)
                current = head
            else:
                grouped_any = True
            out.append(" " + name)
        return out if grouped_any else None

    @staticmethod
    def _ungroup(out: list[str]) -> list[str]:
        lines: list[str] = []
        current: str | None = None
        for k, line in enumerate(out):
            if current is not None and line.startswith(" ") and not line.startswith("  "):
                lines.append(current + line[1:])
                continue
            nxt = out[k + 1] if k + 1 < len(out) else ""
            if line.endswith(("/", "\\")) and nxt.startswith(" ") and not nxt.startswith("  "):
                current = line
                continue
            current = None
            lines.append(line)
        return lines

    def _cap_grouped(self, out: list[str], ctx: Context) -> str:
        res: list[str] = []
        run = 0
        dropped = 0
        for line in out:
            if line.startswith(" ") and not line.startswith("  "):
                run += 1
                if run > MAX_PER_DIR:
                    dropped += 1
                    continue
            else:
                if dropped:
                    res.append(" " + ctx.mark(f"{plural(dropped, 'more entry')} omitted", dropped))
                run, dropped = 0, 0
            res.append(line)
        if dropped:
            res.append(" " + ctx.mark(f"{plural(dropped, 'more entry')} omitted", dropped))
        return "\n".join(res)

    def _cap_plain(self, lines: list[str], ctx: Context) -> str:
        keep = LOSSY_MIN_LINES // 2
        n = len(lines) - 2 * keep
        return "\n".join(
            [
                *lines[:keep],
                ctx.mark(f"{plural(n, 'line')} of the listing omitted", n),
                *lines[-keep:],
            ]
        )

    # ─── ls -l ───────────────────────────────────────────────────────────────

    @staticmethod
    def _ls_long(text: str) -> str:
        """Hoist the columns that never vary within a directory block."""
        lines = text.split("\n")
        out: list[str] = []
        i = 0
        while i < len(lines):
            j = i
            rows = []
            while j < len(lines):
                m = _LS_LONG.match(lines[j])
                if not m:
                    break
                rows.append(m.groups())
                j += 1
            if len(rows) < 4:
                out.extend(lines[i : max(j, i + 1)])
                i = max(j, i + 1)
                continue
            # Owner and group nearly always repeat; links and perms often do.
            const = {}
            for col, name in ((2, "owner"), (3, "group"), (1, "links")):
                if len({r[col] for r in rows}) == 1:
                    const[name] = rows[0][col]
            if not const:
                out.extend(lines[i:j])
                i = j
                continue
            out.append("(" + " ".join(f"{k}={v}" for k, v in const.items()) + " for all below)")
            for r in rows:
                cols = [r[0]]
                if "links" not in const:
                    cols.append(r[1])
                if "owner" not in const:
                    cols.append(r[2])
                if "group" not in const:
                    cols.append(r[3])
                cols += [r[4], " ".join(r[5].split()), r[6]]
                out.append(" ".join(cols))
            i = j
        return "\n".join(out)
