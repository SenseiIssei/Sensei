from __future__ import annotations

import re

# Optional Rust accelerator (rust/sensei_core). Byte-compatible with the Python
# path below; soft-imported so installs without the wheel still work.
try:  # pragma: no cover - depends on whether the wheel was built
    import sensei_core as _core
except ImportError:
    _core = None


class LogCompressor:
    """Compress log / build / test output by keeping what matters.

    Inspired by Headroom's LogCompressor. Logs are the highest-redundancy
    content an agent sees — pages of INFO/DEBUG around a few errors. Strategy:
    - Keep ERROR / FATAL / WARN / exception / traceback lines (+ a little context)
    - Keep summary lines ("12 passed, 3 failed", "BUILD FAILED", separators)
    - Keep the first and last few lines (entry point + final status)
    - Drop runs of low-signal noise, replaced by a "… N lines omitted …" marker
    - Collapse consecutive near-identical lines into "(xN)"

    Lossy, but the omitted lines are pure noise; the original stays in the CCR
    store for retrieval when caching is enabled.
    """

    # A line is "important" if it signals an error/warning or a test/build result.
    IMPORTANT = re.compile(
        r"(error|fatal|critical|fail(?:ed|ure)?|warn(?:ing)?|exception|traceback|"
        r"panic|assert|denied|refused|timeout|✗|✘|✖|fixme)",
        re.IGNORECASE,
    )
    SUMMARY = re.compile(
        r"(\b\d+\s+(?:passed|failed|error|warning|skipped)\b|={3,}|-{3,}|"
        r"\bbuild (?:succeeded|failed|success|complete)\b|\bdone\b|\bsummary\b)",
        re.IGNORECASE,
    )
    # Stack-frame continuation lines worth keeping right after an error.
    FRAME = re.compile(r'^\s*(at |File ", "|in |\| |#\d+ |\.\.\. )')

    # Normalize volatile tokens so otherwise-identical lines dedupe together.
    _NORM = [
        (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*"), "<ts>"),
        (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<hex>"),
        (re.compile(r"\b\d+\b"), "<n>"),
    ]

    def __init__(self, context_after: int = 2, head: int = 3, tail: int = 3) -> None:
        self.context_after = context_after
        self.head = head
        self.tail = tail

    def compress(self, text: str) -> str:
        # Fast path: Rust accelerator (byte-identical output) when available.
        if _core is not None:
            return _core.compress_logs(text, self.context_after, self.head, self.tail)

        lines = text.split("\n")
        n = len(lines)
        if n < 10:
            return text

        keep = [False] * n
        for i in range(min(self.head, n)):
            keep[i] = True
        for i in range(max(0, n - self.tail), n):
            keep[i] = True

        for i, line in enumerate(lines):
            if self.IMPORTANT.search(line) or self.SUMMARY.search(line):
                keep[i] = True
                # Keep a little following context (stack frames, detail lines).
                for j in range(i + 1, min(n, i + 1 + self.context_after)):
                    if self.FRAME.match(lines[j]) or lines[j].strip():
                        keep[j] = True

        # Emit kept lines; replace dropped runs with an omission marker.
        out: list[str] = []
        i = 0
        while i < n:
            if keep[i]:
                out.append(lines[i])
                i += 1
            else:
                j = i
                while j < n and not keep[j]:
                    j += 1
                out.append(f"… {j - i} lines omitted …")
                i = j

        return self._collapse_repeats(out)

    def _collapse_repeats(self, lines: list[str]) -> str:
        """Collapse consecutive lines that are identical after normalization."""
        result: list[str] = []
        prev_norm: str | None = None
        count = 0
        for line in lines:
            norm = self._normalize(line)
            if norm == prev_norm and norm.strip():
                count += 1
                continue
            if count > 1:
                result[-1] = f"{result[-1]} (x{count})"
            result.append(line)
            prev_norm = norm
            count = 1
        if count > 1:
            result[-1] = f"{result[-1]} (x{count})"
        return "\n".join(result)

    def _normalize(self, line: str) -> str:
        for pat, repl in self._NORM:
            line = pat.sub(repl, line)
        return line.strip()
