"""Unified diffs (``git diff``, ``git show``, ``diff -u``).

Every added and removed line stays, byte for byte: those are what a review or
a follow-up edit needs. What goes, only on diffs long enough to matter:

- unchanged context beyond one line either side of a change,
- hunks of generated files (lockfiles, minified bundles, snapshots), reduced to
  their ``@@`` header and a count,
- files and hunks beyond a cap.

Every cut is counted into a marker with the CCR id.
"""

from __future__ import annotations

import re

from sensei.compression.markers import Context, plural

_FILE = re.compile(r"^diff --git |^--- (?:a/|/dev/null)|^\+\+\+ (?:b/|/dev/null)")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
_GENERATED = re.compile(
    r"(?:^|/)(?:package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|poetry\.lock|uv\.lock|"
    r"Pipfile\.lock|composer\.lock|go\.sum|Gemfile\.lock)$|\.min\.(?:js|css)$|\.snap$|\.map$"
)

MIN_LINES = 80
CONTEXT = 1
MAX_FILES = 30
MAX_HUNKS_PER_FILE = 12


def detect(text: str) -> bool:
    lines = text.split("\n", 400)[:400]
    files = sum(1 for ln in lines if ln.startswith(("diff --git ", "+++ ")))
    hunks = sum(1 for ln in lines if _HUNK.match(ln))
    return files >= 1 and hunks >= 1


def _file_name(header: list[str]) -> str:
    for ln in header:
        if ln.startswith("+++ b/"):
            return ln[6:]
        if ln.startswith("diff --git "):
            parts = ln.split(" b/", 1)
            if len(parts) == 2:
                return parts[1]
    return ""


class DiffCompressor:
    def compress(self, text: str, ctx: Context | None = None) -> str:
        ctx = ctx or Context()
        lines = text.split("\n")
        if len(lines) < MIN_LINES:
            return text

        # Split into preamble + files; each file into header + hunks.
        files: list[tuple[list[str], list[list[str]]]] = []
        pre: list[str] = []
        for ln in lines:
            if ln.startswith("diff --git ") or (
                ln.startswith("--- ") and (not files or files[-1][1])
            ):
                files.append(([ln], []))
            elif not files:
                pre.append(ln)
            elif _HUNK.match(ln):
                files[-1][1].append([ln])
            elif files[-1][1]:
                files[-1][1][-1].append(ln)
            else:
                files[-1][0].append(ln)

        out = list(pre)
        context_dropped = 0
        for fi, (header, hunks) in enumerate(files):
            if fi >= MAX_FILES:
                rest = files[fi:]
                n_lines = sum(len(h) + sum(len(x) for x in hs) for h, hs in rest)
                names = [_file_name(h) for h, _ in rest]
                out.append(
                    ctx.mark(
                        f"{plural(len(rest), 'more file')} ({plural(n_lines, 'line')}) omitted: "
                        + ", ".join(n for n in names[:20] if n),
                        n_lines,
                    )
                )
                break
            out.extend(header)
            name = _file_name(header)
            if _GENERATED.search(name) and sum(len(h) for h in hunks) > 20:
                n = sum(len(h) for h in hunks)
                added = sum(1 for h in hunks for x in h[1:] if x.startswith("+"))
                removed = sum(1 for h in hunks for x in h[1:] if x.startswith("-"))
                out.append(
                    ctx.mark(
                        f"generated file: {plural(len(hunks), 'hunk')}, +{added} -{removed}, "
                        f"{plural(n, 'line')} omitted",
                        n,
                    )
                )
                continue
            for hi, hunk in enumerate(hunks):
                if hi >= MAX_HUNKS_PER_FILE:
                    rest_h = hunks[hi:]
                    n = sum(len(h) for h in rest_h)
                    out.append(
                        ctx.mark(
                            f"{plural(len(rest_h), 'more hunk')} ({plural(n, 'line')}) omitted", n
                        )
                    )
                    break
                body, dropped = self._trim_context(hunk[1:])
                context_dropped += dropped
                out.append(hunk[0])
                out.extend(body)
        if context_dropped:
            out.append(
                ctx.mark(
                    f"{plural(context_dropped, 'unchanged context line')} omitted", context_dropped
                )
            )
        return "\n".join(out)

    @staticmethod
    def _trim_context(body: list[str]) -> tuple[list[str], int]:
        changed = [i for i, ln in enumerate(body) if ln[:1] in "+-\\" and ln != ""]
        if not changed:
            return body, 0
        keep = set()
        for i in changed:
            for k in range(i - CONTEXT, i + CONTEXT + 1):
                if 0 <= k < len(body):
                    keep.add(k)
        out: list[str] = []
        dropped = 0
        gap = 0
        for i, ln in enumerate(body):
            if i in keep or (ln == "" and i == len(body) - 1):
                if gap:
                    out.append(f" ... ({gap} unchanged)")
                    gap = 0
                out.append(ln)
            else:
                gap += 1
                dropped += 1
        if gap:
            out.append(f" ... ({gap} unchanged)")
        # A gap marker that replaces fewer lines than it costs is not worth it.
        if dropped < 4:
            return body, 0
        return out, dropped
