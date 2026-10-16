from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sensei.compression import (
    configcomp,
    dense,
    diffcomp,
    folds,
    gitcomp,
    htmlcomp,
    invisible,
    learned,
    listing,
    search,
)
from sensei.compression.cachealign import CacheAligner
from sensei.compression.ccr import CCRStore
from sensei.compression.codecomp import CodeCompressor
from sensei.compression.configcomp import ConfigCompressor
from sensei.compression.diffcomp import DiffCompressor
from sensei.compression.disasm import DisasmCompressor
from sensei.compression.disasm import detect as _detect_disasm
from sensei.compression.gitcomp import GitCompressor
from sensei.compression.htmlcomp import HTMLCompressor
from sensei.compression.listing import ListingCompressor
from sensei.compression.logcomp import LogCompressor
from sensei.compression.markers import Context, ccr_id_for, has_marker
from sensei.compression.search import SearchCompressor
from sensei.compression.smartcrusher import SmartCrusher
from sensei.compression.textcomp import TextCompressor
from sensei.compression.textcrusher import TextCrusher
from sensei.config import settings

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    json = "json"
    code = "code"
    logs = "logs"
    disasm = "disasm"
    text = "text"
    mixed = "mixed"
    search = "search"
    diff = "diff"
    git = "git"
    listing = "listing"
    config = "config"
    html = "html"


@dataclass
class CompressionResult:
    """Result of compressing a single content block."""

    original: str
    compressed: str
    content_type: ContentType
    original_tokens: int = 0
    compressed_tokens: int = 0
    ccr_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens_saved(self) -> int:
        return max(0, self.original_tokens - self.compressed_tokens)

    @property
    def ratio(self) -> float:
        if self.original_tokens == 0:
            return 1.0
        return self.compressed_tokens / self.original_tokens


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def _detect_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        import json

        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


_LOG_LEVEL_RE = re.compile(r"\b(INFO|DEBUG|WARN(?:ING)?|ERROR|TRACE|FATAL|CRITICAL)\b")
_LOG_LINE_START = re.compile(
    r"^\s*(\[?\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}|"
    r"\[(?:INFO|DEBUG|WARN|ERROR|TRACE|FATAL)\]|"
    r'(?:INFO|DEBUG|WARN|ERROR|TRACE|FATAL):|at |File "|Traceback|'
    # Build output frequently carries no timestamp and no level — a compiler
    # emits `[0042] compiling foo.cpp`, `src/x.cpp:412:19: error:` and
    # `make: *** [Makefile:88]`. None of those matched, so a build log was
    # classified as prose and run through the wrong compressor, which both
    # compressed it barely and dropped the error location.
    r"\[\d+\]|"  # bracketed step counters
    r"\S+:\d+:\d+:|"  # gcc/clang/tsc file:line:col diagnostics
    r"(?:make|ninja|cmake|gradle|mvn|cargo|go|npm ERR!|yarn|pnpm|tsc|eslint)[\s:]"
    r")"
)


def _detect_logs(text: str) -> bool:
    """Heuristic: many lines that look like log records (levels/timestamps/frames)."""
    # maxsplit stops after the sample: a plain split() allocates every line of a
    # multi-megabyte tool result just to look at the first eighty. The bounded
    # split yields the same first 80 entries, so the verdict is unchanged.
    lines = text.split("\n", 80)
    if len(lines) < 8:
        return False
    sample = lines[:80]
    hits = sum(
        1
        for line in sample
        if _LOG_LEVEL_RE.search(line)
        or _LOG_LINE_START.match(line)
        # Test runners and package managers: `test x ... ok`, pytest's dot
        # rows, `✓ renders`, `Compiling foo v1.2`. No level, no timestamp.
        or LogCompressor.is_noise(line)
        or _is_test_line(line)
    )
    return hits >= max(4, int(len(sample) * 0.25))


_TEST_START = re.compile(r"^(?:\s*(?:FAIL|PASS)\s+\S|running \d+ tests?$|--- FAIL:)")
_PYTEST_ROW = re.compile(r"[.FEsxX]+\s*\[\s*\d+%\]")
_PYTEST_BANNER = (
    "test session starts",
    "FAILURES",
    "ERRORS",
    "short test summary",
    "passed",
    "failed",
)


def _is_test_line(line: str) -> bool:
    r"""Test-runner output without a log level. String checks rather than one
    regex: `\S+\.py ...` and `=+ .*x.* =+` backtrack quadratically on long lines."""
    if _TEST_START.match(line):
        return True
    if (
        line.startswith("test ")
        and len(line) > 5
        and not line[5].isspace()
        and line.endswith((" ... ok", " ... FAILED", " ... ignored"))
    ):
        return True
    head, sep, rest = line.partition(" ")
    if sep and head.endswith(".py") and _PYTEST_ROW.fullmatch(rest):
        return True
    # pytest banners: `===== 1 failed, 2 passed in 3.1s =====`
    return (
        line.startswith("=")
        and line.endswith("=")
        and " " in line
        and line.lstrip("=").startswith(" ")
        and line.rstrip("=").endswith(" ")
        and any(k in line for k in _PYTEST_BANNER)
    )


# Detection runs on every message of every request, so the indicator sets are
# compiled once and merged into a single alternation each. Six searches per line
# became one, and the per-call `re` cache lookups disappear entirely.

# Strong signals — a single match is enough to classify as code.
_STRONG_CODE_RE = re.compile(
    r"^\s*(?:def |async def |class )"
    r"|^\s*(?:function |func |fn )\w"
    r"|^\s*import \w"
    r"|^\s*from \S+ import "
    r"|^\s*(?:#include|package |using )"
    r"|^\s*(?:public |private |protected )\w"
)

# Weaker signals — need at least two matching lines to classify as code.
_WEAK_CODE_RE = re.compile(
    r";\s*$"  # statement terminators
    r"|^\s*\}\s*$"  # closing braces
    r"|^\s*\{[^}]*\}"  # inline blocks
    r"|=>\s*[{(]"  # arrow functions
    r"|->\s*\w+"  # return-type arrows
    r"|\b(?:const|let|var|return|print|console\.log)\b"
)


def _detect_code(text: str) -> bool:
    """Heuristic: check for code fences or common code patterns."""
    if text.strip().startswith("```"):
        return True

    head = text.split("\n", 400)[:400]
    if _looks_like_code(head[:20]):
        return True
    # A module that opens with a long docstring or licence header has its
    # first statement past line 20; judge the twenty lines after the preamble.
    rest = _skip_preamble(head)
    if rest is not None and _looks_like_code(rest[:20]):
        return True
    return _is_makefile(head)


def _looks_like_code(lines: list[str]) -> bool:
    if any(_STRONG_CODE_RE.search(line) for line in lines):
        return True
    return sum(1 for line in lines if _WEAK_CODE_RE.search(line)) >= 2


def _skip_preamble(lines: list[str]) -> list[str] | None:
    """The lines after a leading docstring or comment block, or None."""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None
    first = lines[i].strip()
    for opener, closer in (('"""', '"""'), ("'''", "'''"), ("/*", "*/")):
        if first.startswith(opener):
            if closer in first[len(opener) :]:
                return lines[i + 1 :]
            for j in range(i + 1, len(lines)):
                if closer in lines[j]:
                    return lines[j + 1 :]
            return None
    if first.startswith(("#", "//", "--", ";")):
        j = i
        while j < len(lines) and (
            not lines[j].strip() or lines[j].lstrip().startswith(("#", "//", "--", ";"))
        ):
            j += 1
        return lines[j:] if j > i else None
    return None


_MAKE_TARGET = re.compile(r"^[\w./%$()-]+(?: [\w./%$()-]+)*:(?:[^=]|$)")


def _is_makefile(lines: list[str]) -> bool:
    """Make rules: `target: deps` lines followed by tab-indented recipes."""
    if any(line.startswith(".PHONY") for line in lines):
        return True
    targets = sum(
        1
        for k, line in enumerate(lines[:-1])
        if _MAKE_TARGET.match(line) and lines[k + 1].startswith("\t")
    )
    return targets >= 2


# A file shown with line numbers — Claude Code's Read tool (`   12→code` or
# `   12<TAB>code`), `cat -n`, `nl -ba`. That is a view somebody is about to edit by
# exact string match, which is the one thing compression must not interfere with.
_FILE_VIEW_LINE = re.compile(r"^\s*\d+(?:→|\t)")


def _is_file_view(text: str) -> bool:
    lines = [line for line in text.split("\n", 50)[:50] if line.strip()]
    if len(lines) < 3:
        return False
    hits = sum(1 for line in lines if _FILE_VIEW_LINE.match(line))
    return hits >= len(lines) * 0.6


def _wordish(word: str) -> bool:
    """A plain word: a letter, then lowercase letters, apostrophes or hyphens,
    with at most one trailing punctuation mark."""
    if word and word[-1] in ",.;:!?":
        word = word[:-1]
    if len(word) < 2 or not ("A" <= word[0] <= "Z" or "a" <= word[0] <= "z"):
        return False
    return all("a" <= c <= "z" or c in "'-" for c in word[1:])


_CODEISH = re.compile(r"[{}\[\]<>=;|\\/_`@#$%^*~]|::|->")


def _is_prose(text: str) -> bool:
    """Mostly sentences: lines of several plain words, and little of the
    punctuation that only code, paths, tables and command output use."""
    prose = total = 0
    for line in text.split("\n", 120)[:120]:
        words = line.split()
        if not words:
            continue
        total += len(line)
        if len(words) < 5:
            continue
        plain = sum(1 for w in words if _wordish(w))
        if plain >= len(words) * 0.7 and len(_CODEISH.findall(line)) <= len(words) * 0.15:
            prose += len(line)
    return total > 0 and prose >= total * 0.5


# Types whose compressor works line by line, so the lossless folds run first.
# Diffs are never folded: a repeated `+` block folded into a back-reference
# would then be trimmed as context by the diff compressor.
_LINE_TYPES = frozenset({"logs", "text", "search", "git", "listing", "config", "disasm"})


def _shape_type(text: str) -> ContentType:
    """Detection for one run of a mixed output (no JSON, no HTML)."""
    if diffcomp.detect(text):
        return ContentType.diff
    if gitcomp.detect_log(text) or gitcomp.detect_status(text):
        return ContentType.git
    if search.detect(text):
        return ContentType.search
    if listing.detect(text):
        return ContentType.listing
    if _detect_logs(text):
        return ContentType.logs
    if _detect_code(text):
        return ContentType.code
    return ContentType.text


def _segments(text: str) -> list[tuple[ContentType, str]] | None:
    """Split a mixed tool output (``git status; ls; sed -n 1,80p x.py``) into
    runs of one kind each, at blank lines. ``None`` when it is all one kind."""
    lines = text.split("\n")
    if len(lines) < 8:
        return None
    chunks: list[list[str]] = [[]]
    for line in lines:
        chunks[-1].append(line)
        if not line.strip():
            chunks.append([])
    if not chunks[-1]:
        chunks.pop()
    if len(chunks) < 2:
        return None
    # Short chunks (a heading, `--- ports ---`) and plain text join their
    # neighbour: text between two runs of test output is test output, and text
    # next to code is safest treated as part of it.
    merged: list[tuple[ContentType, list[str]]] = []
    pending: list[str] = []
    for chunk in chunks:
        body = sum(1 for ln in chunk if ln.strip())
        kind = _shape_type("\n".join(chunk)) if body >= 3 else None
        if kind is ContentType.text:
            kind = None
        if kind is None:
            if merged:
                merged[-1][1].extend(chunk)
            else:
                pending.extend(chunk)
            continue
        if merged and merged[-1][0] is kind:
            merged[-1][1].extend(chunk)
        else:
            merged.append((kind, pending + chunk))
            pending = []
    if not merged:
        return None
    merged[-1][1].extend(pending)
    if len(merged) < 2:
        return None
    # Every run but the last ends where a line ended, so joining the runs with
    # "\n" reproduces the input exactly.
    return [(kind, "\n".join(chunk)) for kind, chunk in merged]


_NAMES = {
    ContentType.json: "smartcrusher",
    ContentType.search: "searchcompressor",
    ContentType.diff: "diffcompressor",
    ContentType.git: "gitcompressor",
    ContentType.listing: "listingcompressor",
    ContentType.config: "configcompressor",
    ContentType.html: "htmlcompressor",
    ContentType.disasm: "disasmcompressor",
    ContentType.logs: "logcompressor",
    ContentType.code: "codecompressor",
    ContentType.text: "textcompressor",
}


class ContentRouter:
    """Routes content to the appropriate compressor based on detected type.

    Inspired by Headroom's ContentRouter. Detection order: JSON, HTML, diff,
    git, search results, disassembly, logs / test / build output, directory
    listings, config, code, prose. A tool result that mixes several of those
    (``git status && ls && sed -n 1,80p x.py``) is split at blank lines and each
    run goes to its own compressor; code runs stay byte-exact.

    Pipeline per block:

    1. Protection: content the model may edit next by exact string match —
       code, file views, JSON objects, config, small HTML — passes through
       byte-exact when it arrived as a tool result.
    2. Terminal rendering (ANSI codes, carriage-return progress bars) and the
       invisible-character pass.
    3. Lossless folds (repeated lines and blocks), verified by round-trip.
    4. The type's compressor. Every lossy cut leaves
       ``[sensei: <what>; retrieve ccr=<id>]``.
    5. Fail-open: a result that is not smaller than its input is discarded.
    """

    def __init__(
        self,
        ccr_store: CCRStore | None = None,
        enable_caching: bool = True,
    ):
        self.smart_crusher = SmartCrusher()
        self.code_compressor = CodeCompressor(mode=settings.code_compression)
        self.disasm_compressor = DisasmCompressor()
        self.text_compressor = TextCompressor()
        # Learned prose compressor when available, else the rule-based one.
        self.prose_compressor = learned.get_prose_compressor() or self.text_compressor
        self.text_crusher = TextCrusher()
        self.log_compressor = LogCompressor()
        self.search_compressor = SearchCompressor()
        self.diff_compressor = DiffCompressor()
        self.git_compressor = GitCompressor()
        self.listing_compressor = ListingCompressor()
        self.config_compressor = ConfigCompressor()
        self.html_compressor = HTMLCompressor()
        self.cache_aligner = CacheAligner()
        self.ccr_store = ccr_store
        self.enable_caching = enable_caching

    def detect_type(self, content: str) -> ContentType:
        """Detect the content type of a text block."""
        if _detect_json(content):
            return ContentType.json
        if htmlcomp.detect(content):
            return ContentType.html
        if diffcomp.detect(content):
            return ContentType.diff
        if gitcomp.detect_log(content) or gitcomp.detect_status(content):
            return ContentType.git
        if search.detect(content):
            return ContentType.search
        if _detect_disasm(content):
            return ContentType.disasm
        if _detect_logs(content):
            return ContentType.logs
        if listing.detect(content):
            return ContentType.listing
        if configcomp.detect(content):
            return ContentType.config
        if _detect_code(content):
            return ContentType.code
        return ContentType.text

    @staticmethod
    def _protected(content: str, content_type: ContentType, edit_target: bool) -> bool:
        """A file the model may edit next by exact string match."""
        if not edit_target or settings.code_compression == "aggressive":
            return False
        if content_type in (ContentType.code, ContentType.config):
            return True
        # JSON on disk (package.json, tsconfig, a fixture) is pretty-printed;
        # an API or MCP response is one line. Only the first is a file to edit.
        if content_type is ContentType.json and "\n" in content.strip():
            return True
        # An HTML page fetched with curl and a template read with cat look the
        # same, and only one of them is safe to rewrite.
        if content_type is ContentType.html:
            return True
        return _is_file_view(content)

    def compress(
        self,
        content: str,
        force_type: ContentType | None = None,
        *,
        edit_target: bool = False,
        query: str = "",
    ) -> CompressionResult:
        """Compress a single content block.

        Args:
            content: The text to compress.
            force_type: Override content type detection.
            edit_target: The text reached the model as a tool result, so the
                model may edit it next by exact string match (Claude Code's
                Edit, Codex's apply_patch). Source code, config, line-numbered
                file views and JSON objects then pass through byte-exact
                unless ``SENSEI_CODE_COMPRESSION=aggressive``: a model that
                never saw a comment writes an ``old_string`` without it, the
                edit fails, and the retry costs more than the compression saved.
            query: What the model is looking for, when the caller knows (the
                user's last message, the tool call's arguments). Lossy
                compressors prefer to keep what matches it; it never makes
                anything less exact.

        Returns:
            CompressionResult with original, compressed, and metadata.
        """
        # Held before anything touches it. The CCR store's whole promise is that
        # `sensei_retrieve` hands back what the caller actually sent, byte for
        # byte — stripping first and storing the result would quietly make the
        # "original" a thing that never existed.
        untouched = content

        content_type = force_type or self.detect_type(content)
        original_tokens = _estimate_tokens(content)
        protect = self._protected(content, content_type, edit_target)

        store = self.ccr_store if (self.enable_caching and self.ccr_store) else None
        ctx = Context(ccr_id=ccr_id_for(untouched) if store else None, query=query or "")

        # Before compressing, not after: every compressor below is line- and
        # word-oriented and none of them looks at individual characters, so a
        # zero-width space survives all of them and is billed. Detection runs
        # first because how aggressive this can safely be depends on whether
        # the payload is source code — the joiners are structural in Devanagari
        # and Persian and hold emoji sequences together, and mean nothing in
        # source. Protected content is not touched at all: "byte-exact" means it.
        findings = invisible.Findings()
        if protect:
            compressed = content
            compressor = "passthrough (edit target)"
        else:
            if content_type is not ContentType.json:
                content = folds.render_terminal(content)
            if settings.strip_invisible:
                content, findings = invisible.clean(
                    content,
                    is_code=content_type is ContentType.code,
                    strip_nbsp=settings.strip_nbsp,
                )
            if settings.compression_lossy:
                compressed, compressor = self._dispatch(content, content_type, ctx, edit_target)
            else:
                compressed = self._lossless(content, content_type, edit_target)
                compressor = f"{content_type.value} (lossless only)"
            # Fail-open: never hand back more than came in. Logs used to grow.
            if len(compressed) >= len(content):
                compressed, ctx.lossy, ctx.omitted = content, False, 0
            if len(compressed) >= len(untouched):
                compressed, ctx.lossy, ctx.omitted = untouched, False, 0
                compressor = "passthrough (no gain)"

        # The output is the authority: a step that cut and was then discarded
        # by fail-open must not be reported as lossy.
        if ctx.lossy and not has_marker(compressed):
            ctx.lossy, ctx.omitted = False, 0

        compressed_tokens = _estimate_tokens(compressed)

        # The original goes to the store whenever the block got smaller, and
        # always when a marker points at it.
        ccr_id = None
        if store is not None and (ctx.lossy or original_tokens > compressed_tokens):
            ccr_id = store.store(untouched, compressed, content_type.value, ccr_id=ctx.ccr_id)

        metadata: dict[str, Any] = {"compressor": compressor, "lossy": ctx.lossy}
        if ctx.lossy:
            metadata["omitted"] = ctx.omitted
        if findings.anything:
            metadata.update(findings.as_dict())

        # The token saving needs no announcement — stripping happens before the
        # count, so it is already in the headline number. These two do: a bidi
        # override is a Trojan Source vector and a mixed-script identifier is
        # either an attack or a paste accident, and removing one silently is
        # not the same as telling somebody it was there.
        if findings.bidi:
            logger.warning(
                "Removed %d bidirectional control character(s) from a %s payload — "
                "these can make source render differently from how it compiles "
                "(CVE-2021-42574).",
                findings.bidi,
                content_type.value,
            )
        if findings.smuggled:
            logger.warning(
                "Removed %d tag character(s) or variation selector(s) from a %s "
                "payload. These render as nothing at all and each maps to an "
                "ASCII character, so they can carry readable instructions that a "
                "model sees and a human reviewing the text does not.",
                findings.smuggled,
                content_type.value,
            )
        if findings.mixed_script_words:
            logger.warning(
                "Payload contains identifier(s) mixing Latin with another alphabet, "
                "which read as ordinary words but are not: %s. Left unchanged.",
                ", ".join(findings.mixed_script_words[:5]),
            )

        return CompressionResult(
            original=untouched,
            compressed=compressed,
            content_type=content_type,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            ccr_id=ccr_id,
            metadata=metadata,
        )

    def compress_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], list[CompressionResult]]:
        """Compress a list of chat messages.

        Preserves system messages uncompressed (they're usually short and
        need to stay exact for prompt caching). Compresses user and assistant
        message content.

        Returns:
            Tuple of (compressed_messages, compression_results)
        """
        compressed_msgs: list[dict[str, str]] = []
        results: list[CompressionResult] = []

        # Stabilize prefix with CacheAligner
        messages = self.cache_aligner.align(messages)

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Don't compress system messages or very short content
            if role == "system" or len(content) < 100:
                compressed_msgs.append(msg)
                continue

            result = self.compress(content)
            results.append(result)

            compressed_msgs.append(
                {
                    "role": role,
                    "content": result.compressed,
                    **({"name": msg["name"]} if "name" in msg else {}),
                }
            )

        return compressed_msgs, results

    # ─── dispatch ────────────────────────────────────────────────────────────

    def _dispatch(
        self, content: str, content_type: ContentType, ctx: Context, edit_target: bool
    ) -> tuple[str, str]:
        """Compress one unprotected block; return (text, compressor name)."""
        if content_type in (ContentType.text, ContentType.logs, ContentType.mixed):
            segments = _segments(content)
            if segments is not None:
                parts = [self._typed(seg, kind, ctx, edit_target) for kind, seg in segments]
                kinds = "+".join(dict.fromkeys(kind.value for kind, _ in segments))
                return "\n".join(parts), f"segmented({kinds})"
        name = _NAMES.get(content_type, content_type.value)
        if content_type is ContentType.text and self.prose_compressor is not self.text_compressor:
            name = "learned-compressor"
        return self._typed(content, content_type, ctx, edit_target), name

    def _typed(
        self, content: str, content_type: ContentType, ctx: Context, edit_target: bool
    ) -> str:
        """One run of a single type through its compressor, fail-open."""
        if content_type is ContentType.code:
            if edit_target and settings.code_compression != "aggressive":
                return content
            out = self.code_compressor.compress(content)
            return out if len(out) < len(content) else content

        # Text that reached the model as a tool result may be a file it edits
        # next (a README, a template, source the detector did not recognise):
        # nothing in it is rewritten or folded. Only marked elision of blobs
        # and minified lines applies, which says exactly what it removed.
        if content_type is ContentType.text and edit_target:
            out = dense.elide_dense(content, ctx)
            return out if len(out) < len(content) else content

        match content_type:
            case ContentType.json:
                out = self.smart_crusher.compress(content, ctx)
            case ContentType.search:
                out = self.search_compressor.compress(content, ctx)
            case ContentType.diff:
                out = self.diff_compressor.compress(content, ctx)
            case ContentType.git:
                out = self.git_compressor.compress(content)
            case ContentType.listing:
                out = self.listing_compressor.compress(content, ctx, edit_target=edit_target)
            case ContentType.config:
                out = self.config_compressor.compress(content, ctx)
            case ContentType.html:
                out = self.html_compressor.compress(content, ctx)
            case ContentType.disasm:
                out = self.disasm_compressor.compress(content)
            case ContentType.logs:
                out = dense.elide_dense(self.log_compressor.compress(content, ctx), ctx)
            case _:
                out = self._prose(content, ctx)
        # Folds run last, on what will actually be sent: a back-reference
        # computed before a lossy step could point at a line that step removed.
        if content_type.value in _LINE_TYPES:
            out = folds.fold(out)
        return out if len(out) < len(content) else content

    def _prose(self, text: str, ctx: Context) -> str:
        text = dense.elide_dense(text, ctx)
        # The prose compressors rewrite words and capitalise after every
        # newline. On a table, a command's output or an identifier list that
        # turns `tests::case_131` into `Tests::case_131`; only sentences get it.
        if not _is_prose(text):
            return text
        if settings.compression_prose == "extractive":
            text = self.text_crusher.compress(text, ctx)
        if self.prose_compressor is self.text_compressor:
            return self.text_compressor.compress(text, ctx)
        return self.prose_compressor.compress(text)

    def _lossless(self, content: str, content_type: ContentType, edit_target: bool) -> str:
        """``compression_lossy = false``: only transforms that lose nothing."""
        if content_type is ContentType.code:
            return content
        if content_type is ContentType.json:
            return self.smart_crusher.compress_lossless(content)
        if edit_target and content_type in (ContentType.text, ContentType.listing):
            return content
        work = folds.fold(content) if content_type.value in _LINE_TYPES else content
        if content_type is ContentType.search:
            return self.search_compressor.group(work)
        if content_type is ContentType.git:
            return self.git_compressor.compress(work)
        return work

    def retrieve_original(self, ccr_id: str) -> str | None:
        """Retrieve the original uncompressed content from CCR."""
        if not self.ccr_store:
            return None
        return self.ccr_store.retrieve(ccr_id)
