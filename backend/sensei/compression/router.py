from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sensei.compression import invisible, learned
from sensei.compression.cachealign import CacheAligner
from sensei.compression.ccr import CCRStore
from sensei.compression.codecomp import CodeCompressor
from sensei.compression.logcomp import LogCompressor
from sensei.compression.smartcrusher import SmartCrusher
from sensei.compression.textcomp import TextCompressor
from sensei.config import settings

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    json = "json"
    code = "code"
    logs = "logs"
    text = "text"
    mixed = "mixed"


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
    hits = sum(1 for line in sample if _LOG_LEVEL_RE.search(line) or _LOG_LINE_START.match(line))
    return hits >= max(4, int(len(sample) * 0.25))


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

    lines = text.split("\n", 20)[:20]

    if any(_STRONG_CODE_RE.search(line) for line in lines):
        return True

    matches = sum(1 for line in lines if _WEAK_CODE_RE.search(line))
    return matches >= 2


class ContentRouter:
    """Routes content to the appropriate compressor based on detected type.

    Inspired by Headroom's ContentRouter — detects content type and selects
    the right compressor (SmartCrusher for JSON, CodeCompressor for code,
    TextCompressor for prose).
    """

    def __init__(
        self,
        ccr_store: CCRStore | None = None,
        enable_caching: bool = True,
    ):
        self.smart_crusher = SmartCrusher()
        self.code_compressor = CodeCompressor()
        self.text_compressor = TextCompressor()
        # Learned prose compressor when available, else the rule-based one.
        self.prose_compressor = learned.get_prose_compressor() or self.text_compressor
        self.log_compressor = LogCompressor()
        self.cache_aligner = CacheAligner()
        self.ccr_store = ccr_store
        self.enable_caching = enable_caching

    def detect_type(self, content: str) -> ContentType:
        """Detect the content type of a text block."""
        if _detect_json(content):
            return ContentType.json
        if _detect_logs(content):
            return ContentType.logs
        if _detect_code(content):
            return ContentType.code
        return ContentType.text

    def compress(self, content: str, force_type: ContentType | None = None) -> CompressionResult:
        """Compress a single content block.

        Args:
            content: The text to compress.
            force_type: Override content type detection.

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

        # Before compressing, not after: every compressor below is line- and
        # word-oriented and none of them looks at individual characters, so a
        # zero-width space survives all of them and is billed. Detection runs
        # first because how aggressive this can safely be depends on whether
        # the payload is source code — the joiners are structural in Devanagari
        # and Persian and hold emoji sequences together, and mean nothing in
        # source.
        findings = invisible.Findings()
        if settings.strip_invisible:
            content, findings = invisible.clean(
                content,
                is_code=content_type is ContentType.code,
                strip_nbsp=settings.strip_nbsp,
            )

        match content_type:
            case ContentType.json:
                compressed = self.smart_crusher.compress(content)
                compressor = "smartcrusher"
            case ContentType.code:
                compressed = self.code_compressor.compress(content)
                compressor = "codecompressor"
            case ContentType.logs:
                compressed = self.log_compressor.compress(content)
                compressor = "logcompressor"
            case _:
                compressed = self.prose_compressor.compress(content)
                compressor = (
                    "textcompressor"
                    if self.prose_compressor is self.text_compressor
                    else "learned-compressor"
                )

        compressed_tokens = _estimate_tokens(compressed)

        # Store original in CCR for retrieval
        ccr_id = None
        if self.enable_caching and self.ccr_store and original_tokens > compressed_tokens:
            ccr_id = self.ccr_store.store(untouched, compressed, content_type.value)

        metadata: dict[str, Any] = {"compressor": compressor}
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

    def retrieve_original(self, ccr_id: str) -> str | None:
        """Retrieve the original uncompressed content from CCR."""
        if not self.ccr_store:
            return None
        return self.ccr_store.retrieve(ccr_id)
