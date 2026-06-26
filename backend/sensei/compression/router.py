from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sensei.compression.cachealign import CacheAligner
from sensei.compression.ccr import CCRStore
from sensei.compression.codecomp import CodeCompressor
from sensei.compression.logcomp import LogCompressor
from sensei.compression.smartcrusher import SmartCrusher
from sensei.compression.textcomp import TextCompressor


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
    r'^\s*(\[?\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}|'
    r'\[(?:INFO|DEBUG|WARN|ERROR|TRACE|FATAL)\]|'
    r'(?:INFO|DEBUG|WARN|ERROR|TRACE|FATAL):|at |File "|Traceback)'
)


def _detect_logs(text: str) -> bool:
    """Heuristic: many lines that look like log records (levels/timestamps/frames)."""
    lines = text.split("\n")
    if len(lines) < 8:
        return False
    sample = lines[:80]
    hits = sum(1 for line in sample if _LOG_LEVEL_RE.search(line) or _LOG_LINE_START.match(line))
    return hits >= max(4, int(len(sample) * 0.25))


def _detect_code(text: str) -> bool:
    """Heuristic: check for code fences or common code patterns."""
    if text.strip().startswith("```"):
        return True

    lines = text.split("\n")[:20]

    # Strong signals — a single match is enough to classify as code.
    strong_indicators = [
        r"^\s*(def |async def |class )",
        r"^\s*(function |func |fn )\w",
        r"^\s*import \w",
        r"^\s*from \S+ import ",
        r"^\s*(#include|package |using )",
        r"^\s*(public |private |protected )\w",
    ]
    if any(re.search(p, line) for line in lines for p in strong_indicators):
        return True

    # Weaker signals — need at least two to classify as code.
    weak_indicators = [
        r";\s*$",  # statement terminators
        r"^\s*\}\s*$",  # closing braces
        r"^\s*\{[^}]*\}",  # inline blocks
        r"=>\s*[{(]",  # arrow functions
        r"->\s*\w+",  # return-type arrows
        r"\b(const|let|var|return|print|console\.log)\b",
    ]
    matches = sum(1 for line in lines if any(re.search(p, line) for p in weak_indicators))
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
        content_type = force_type or self.detect_type(content)
        original_tokens = _estimate_tokens(content)

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
                compressed = self.text_compressor.compress(content)
                compressor = "textcompressor"

        compressed_tokens = _estimate_tokens(compressed)

        # Store original in CCR for retrieval
        ccr_id = None
        if self.enable_caching and self.ccr_store and original_tokens > compressed_tokens:
            ccr_id = self.ccr_store.store(content, compressed, content_type.value)

        return CompressionResult(
            original=content,
            compressed=compressed,
            content_type=content_type,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            ccr_id=ccr_id,
            metadata={"compressor": compressor},
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

            compressed_msgs.append({
                "role": role,
                "content": result.compressed,
                **({"name": msg["name"]} if "name" in msg else {}),
            })

        return compressed_msgs, results

    def retrieve_original(self, ccr_id: str) -> str | None:
        """Retrieve the original uncompressed content from CCR."""
        if not self.ccr_store:
            return None
        return self.ccr_store.retrieve(ccr_id)
