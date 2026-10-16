from __future__ import annotations

import re
from typing import ClassVar

from sensei.compression.markers import Context, plural

# The Rust accelerator (rust/sensei_core) still exports `compress_logs`, but it
# implements the earlier keep-errors-drop-the-rest pass without markers, test
# awareness or diagnostic dedup. This module no longer calls it: an
# accelerator that returns different bytes is not an accelerator.


class LogCompressor:
    """Compress log / build / test output by keeping what matters.

    Inspired by Headroom's LogCompressor. Logs are the highest-redundancy
    content an agent sees: pages of INFO/DEBUG around a few errors, a line per
    passing test, a line per compiled crate. Strategy:

    - Keep ERROR / FATAL / WARN / exception / traceback lines and their block
      (stack frames, the source line a frame points at, rustc's ``-->`` and
      code snippet).
    - Keep summary lines ("12 passed, 3 failed", "test result:", "BUILD FAILED").
    - Keep the first and last lines (entry point and final status).
    - Recognise progress noise from test runners and build tools (passing
      tests, ``Compiling x v1.2``, ``Downloading``, pytest's dot rows, caret
      underlines) and never let it count as important, even when a test name
      contains the word "error".
    - Collapse repeated diagnostics: the third and later ``warning: unused
      variable`` keep only their location, listed in one marker.
    - A short log with nothing to drop is returned unchanged.

    Every cut is a marker carrying the CCR id: ``[sensei: 37 lines omitted;
    retrieve ccr=...]``. The untouched original is in the store.
    """

    IMPORTANT = re.compile(
        r"(error|fatal|critical|fail(?:ed|ure|s)?\b|warn(?:ing)?|exception|traceback|"
        r"panic|assert|denied|refused|timeout|timed out|✗|✘|✖|fixme|\bERR!)",
        re.IGNORECASE,
    )
    SUMMARY = re.compile(
        r"(\b\d+\s+(?:passed|failed|errors?|warnings?|skipped|tests?|suites?)\b|={3,}|"
        r"\btest result:|\bTests?:\s|\bTest Suites:|\bbuild (?:succeeded|failed|success|complete)\b|"
        r"\bfinished\b|\bdone\b|\bsummary\b|^(?:ok|FAIL|PASS)\s+\S+\s+[\d.]+m?s\b)",
        re.IGNORECASE,
    )
    # Lines that are progress, never signal — even when a test is named
    # `test_error_path ... ok`.
    NOISE = re.compile(
        r"^(?:test \S.* \.\.\. (?:ok|ignored)$"  # cargo
        r"|\S+::\S+ PASSED(?:\s+\[\s*\d+%\])?$"  # pytest -v
        r"|\S+\.py \.+\s*(?:\[\s*\d+%\])?$"  # pytest progress rows without failures
        r"|\.+\s*\[\s*\d+%\]$"
        r"|\s*[✓✔√]\s"  # jest / vitest / mocha
        r"|=== RUN\s|--- PASS:|PASS$|ok\s+\S+\s+(?:[\d.]+s|\(cached\))$"  # go test
        r"|\s*(?:Compiling|Checking|Fresh|Downloaded|Downloading|Fetching|Updating|Locking|Adding|"
        r"Unpacking|Blocking|Documenting|Installing|Collecting|Building wheel|Using cached|"
        r"Requirement already satisfied|Resolved|Prepared|Audited|Installed)\s"
        r"|npm (?:http|timing|sill|verb)\s"
        r"|\s*[~^]+\s*$"  # Python 3.11+ caret underlines
        r")"
    )
    # Stack-frame continuation lines worth keeping next to an error.
    FRAME = re.compile(r'^\s*(at |File "|in |\| |#\d+ |\.\.\. |--> |-->)')

    # A traceback is a *block*: frame lines interleaved with the source line
    # each frame points at, and those source lines match nothing above. Treating
    # any indented non-empty line as part of the block keeps Python, Java and
    # JavaScript traces intact without needing a parser per language.
    _BLOCK = re.compile(r"^\s+\S")

    # Bound on how far a block extends from its error line. A 900-frame Java
    # trace is mostly framework noise; the frames nearest the exception are the
    # ones that say what actually happened, and those are the ones this reaches
    # first in both directions.
    MAX_BLOCK = 40

    # rustc / clippy / gcc diagnostic header: `warning: unused variable: `x``.
    _DIAG = re.compile(r"^(warning|error)(\[[\w-]+\])?: (.+)$")
    _LOCATION = re.compile(r"^\s*--> (\S+)")
    MAX_SAME_DIAG = 2

    # Normalize volatile tokens so otherwise-identical lines dedupe together.
    _NORM: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*"), "<ts>"),
        (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<hex>"),
        (re.compile(r"`[^`]*`|'[^']*'|\"[^\"]*\""), "<q>"),
        (re.compile(r"\d+"), "<n>"),
    ]

    # Fewer lines than this left after dropping noise: keep the rest whole.
    SMALL = 40

    def __init__(self, context_after: int = 2, head: int = 3, tail: int = 3) -> None:
        self.context_after = context_after
        self.head = head
        self.tail = tail

    def compress(self, text: str, ctx: Context | None = None) -> str:
        ctx = ctx or Context()
        lines = text.split("\n")
        n = len(lines)
        if n < 10:
            return text

        noise = [bool(self.NOISE.match(line)) for line in lines]
        signal = [
            not noise[i] and bool(self.IMPORTANT.search(line) or self.SUMMARY.search(line))
            for i, line in enumerate(lines)
        ]
        small = n - sum(noise) <= self.SMALL

        keep = [not noise[i] if small else False for i in range(n)]
        for i in range(min(self.head, n)):
            keep[i] = True
        for i in range(max(0, n - self.tail), n):
            keep[i] = True

        for i in range(n):
            if not signal[i]:
                continue
            keep[i] = True
            # Keep a little following context (stack frames, detail lines).
            for j in range(i + 1, min(n, i + 1 + self.context_after)):
                if not noise[j] and (self.FRAME.match(lines[j]) or lines[j].strip()):
                    keep[j] = True
            # Then follow the stack-frame block in both directions.
            #
            # Direction matters and differs by language: Python puts the
            # exception last and the frames above it, Java puts it first with
            # the frames below. Walking both ways keeps whichever it is, and
            # stops at the first line that is not part of the block, so
            # ordinary log noise is untouched.
            for j in range(i - 1, max(-1, i - 1 - self.MAX_BLOCK), -1):
                if noise[j] or not self._in_block(lines[j]):
                    break
                keep[j] = True
            for j in range(i + 1, min(n, i + 1 + self.MAX_BLOCK)):
                if noise[j] or not self._in_block(lines[j]):
                    break
                keep[j] = True

        dropped_diag, absorbed = self._dedupe_diagnostics(lines, keep)

        # Emit kept lines; replace dropped runs with a marker that says what
        # kind of lines they were when it is one kind.
        out: list[str] = []
        i = 0
        while i < n:
            if keep[i]:
                out.append(lines[i])
                i += 1
                continue
            if i in absorbed:
                i += 1
                continue
            j = i
            while j < n and not keep[j] and j not in absorbed:
                j += 1
            count = j - i
            if count == 1 and not noise[i] and len(lines[i]) < 60:
                out.append(lines[i])
            elif all(noise[i:j]):
                out.append(ctx.mark(f"{plural(count, 'progress line')} omitted", count))
            else:
                out.append(ctx.mark(f"{plural(count, 'line')} omitted", count))
            i = j

        for signature, locations in dropped_diag.items():
            shown = ", ".join(locations[:12]) + (", ..." if len(locations) > 12 else "")
            out.append(
                ctx.mark(
                    f"{plural(len(locations), 'more')} '{signature}' at {shown}",
                    len(locations),
                )
            )
        return self._collapse_repeats(out, ctx)

    def _dedupe_diagnostics(
        self, lines: list[str], keep: list[bool]
    ) -> tuple[dict[str, list[str]], set[int]]:
        """Drop the third and later copy of the same rustc/clippy diagnostic.

        The block (header to blank line) goes; its ``-->`` location is
        collected so the marker still says everywhere it occurred.
        """
        seen: dict[str, int] = {}
        dropped: dict[str, list[str]] = {}
        absorbed: set[int] = set()
        n = len(lines)
        i = 0
        while i < n:
            m = self._DIAG.match(lines[i])
            if not m or not keep[i]:
                i += 1
                continue
            j = i + 1
            while j < n and lines[j].strip() and not self._DIAG.match(lines[j]):
                j += 1
            signature = f"{m.group(1)}{m.group(2) or ''}: {self._normalize(m.group(3))}"
            seen[signature] = seen.get(signature, 0) + 1
            if seen[signature] > self.MAX_SAME_DIAG and j - i > 1:
                loc = next(
                    (
                        lm.group(1)
                        for k in range(i + 1, j)
                        if (lm := self._LOCATION.match(lines[k]))
                    ),
                    None,
                )
                if loc:
                    short = f"{m.group(1)}{m.group(2) or ''}: {m.group(3)}"[:80]
                    dropped.setdefault(short.replace("'", ""), []).append(loc)
                    # The block and its trailing blank line are accounted for
                    # by the diagnostic marker, not by a generic run marker.
                    for k in range(i, j + (1 if j < n and not lines[j].strip() else 0)):
                        keep[k] = False
                        absorbed.add(k)
            i = j
        return dropped, absorbed

    def _in_block(self, line: str) -> bool:
        """Is this line part of a stack-frame block?"""
        return bool(self.FRAME.match(line) or self._BLOCK.match(line))

    def _collapse_repeats(self, lines: list[str], ctx: Context) -> str:
        """Runs of lines identical after normalization keep their first and
        last line; the middle becomes a marker (the varying numbers in it are
        facts, so this is a cut, not a fold)."""
        result: list[str] = []
        i = 0
        n = len(lines)
        while i < n:
            norm = self._normalize(lines[i])
            j = i + 1
            while j < n and norm.strip() and self._normalize(lines[j]) == norm:
                j += 1
            run = j - i
            if run >= 4:
                result.append(lines[i])
                result.append(ctx.mark(f"{plural(run - 2, 'similar line')} omitted", run - 2))
                result.append(lines[j - 1])
            else:
                result.extend(lines[i:j])
            i = j
        return "\n".join(result)

    def _normalize(self, line: str) -> str:
        for pat, repl in self._NORM:
            line = pat.sub(repl, line)
        return line.strip()
