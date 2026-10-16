"""git status / git log output, and git's per-file line-ending warnings.

Nothing here drops a fact. ``git status`` long form prints the same usage
hints every time (``(use "git add <file>..." ...)``); they go. ``git log``'s
four-line commit header becomes one line, with the author hoisted when every
commit has the same one. A run of ``LF will be replaced by CRLF`` warnings —
one per touched file, often dozens — becomes one warning that lists the files.
"""

from __future__ import annotations

import re

_HINT = re.compile(r'^\s*\((?:use "git [^"]+"[^)]*|use "git [^)]*)\)\s*$')
_COMMIT = re.compile(r"^commit ([0-9a-f]{7,64})((?: \(.*\))?)$")
_AUTHOR = re.compile(r"^Author:\s+(.*)$")
_DATE = re.compile(r"^(?:Date|AuthorDate|CommitDate):\s+(.*)$")
_MERGE = re.compile(r"^Merge:\s+(.*)$")
_CRLF = re.compile(
    r"^warning: in the working copy of '([^']+)', (LF will be replaced by CRLF|CRLF will be "
    r"replaced by LF) the next time Git touches it$"
)

_STATUS_MARKERS = (
    "On branch ",
    "Your branch is ",
    "Changes not staged for commit:",
    "Changes to be committed:",
    "Untracked files:",
    "nothing to commit",
    "HEAD detached at ",
)


def detect_status(text: str) -> bool:
    head = text[:2000]
    return sum(1 for m in _STATUS_MARKERS if m in head) >= 2 or (
        "On branch " in head and _HINT.search(head) is not None
    )


def detect_log(text: str) -> bool:
    lines = text.split("\n", 60)[:60]
    commits = sum(1 for ln in lines if _COMMIT.match(ln))
    authors = sum(1 for ln in lines if ln.startswith("Author: "))
    return commits >= 2 and authors >= 2


def fold_crlf_warnings(text: str) -> str:
    if "the next time Git touches it" not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _CRLF.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        kind = m.group(2)
        files = [m.group(1)]
        j = i + 1
        while j < len(lines):
            m2 = _CRLF.match(lines[j])
            if not m2 or m2.group(2) != kind:
                break
            files.append(m2.group(1))
            j += 1
        if len(files) < 3:
            out.extend(lines[i:j])
        else:
            out.append(
                f"warning: {kind} the next time Git touches it, in the working copy of "
                f"{len(files)} files: " + ", ".join(files)
            )
        i = j
    return "\n".join(out)


class GitCompressor:
    def compress(self, text: str) -> str:
        if detect_log(text):
            text = self._log(text)
        if detect_status(text):
            text = "\n".join(ln for ln in text.split("\n") if not _HINT.match(ln))
        return fold_crlf_warnings(text)

    @staticmethod
    def _log(text: str) -> str:
        lines = text.split("\n")
        authors = {m.group(1) for ln in lines if (m := _AUTHOR.match(ln))}
        one_author = next(iter(authors)) if len(authors) == 1 else None
        out: list[str] = []
        if one_author:
            out.append(f"(all commits below by {one_author})")
        i = 0
        while i < len(lines):
            m = _COMMIT.match(lines[i])
            if not m:
                out.append(lines[i])
                i += 1
                continue
            parts = [m.group(1) + m.group(2)]
            j = i + 1
            while j < len(lines) and lines[j].strip():
                h = lines[j]
                if a := _AUTHOR.match(h):
                    if not one_author:
                        parts.append(a.group(1))
                elif d := _DATE.match(h):
                    parts.append(d.group(1))
                elif mg := _MERGE.match(h):
                    parts.append("merge " + mg.group(1))
                else:
                    break
                j += 1
            out.append(" | ".join(parts))
            # The blank line between header and message carries nothing.
            if j < len(lines) and not lines[j].strip():
                j += 1
            i = j
        return "\n".join(out)
