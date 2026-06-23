from __future__ import annotations

import re


class TextCompressor:
    """Compress prose/text content by removing redundancy and verbosity.

    Inspired by Headroom's Kompress-base — uses rule-based compression
    for zero-dependency operation. Strategies:
    - Remove repeated whitespace and blank lines
    - Collapse repeated phrases
    - Truncate very long paragraphs with summary markers
    - Remove boilerplate phrases common in tool outputs
    """

    # Common boilerplate phrases to strip
    BOILERPLATE = [
        r"In order to\s+",
        r"It is worth noting that\s+",
        r"It should be noted that\s+",
        r"Please note that\s+",
        r"As mentioned (?:earlier|above|before)\s*,?\s*",
        r"As (?:stated|described) (?:earlier|above)\s*,?\s*",
        r"For more (?:information|details)\s*,?\s*see\s+\S+\s*",
        r"See (?:the )?(?:documentation|docs|README|guide) for more details\.?",
    ]

    # Max paragraph length before truncation
    MAX_PARAGRAPH = 500

    def compress(self, text: str) -> str:
        """Compress prose text."""
        # Step 1: Remove boilerplate phrases
        for pattern in self.BOILERPLATE:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # Step 2: Normalize whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Step 3: Collapse repeated lines
        lines = text.split("\n")
        seen: set[str] = set()
        deduped: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and stripped in seen and len(stripped) > 20:
                continue
            if stripped:
                seen.add(stripped)
            deduped.append(line)

        # Step 4: Truncate long paragraphs
        result = []
        for line in deduped:
            if len(line) > self.MAX_PARAGRAPH:
                # Keep first and last sentences, summarize middle
                sentences = re.split(r"(?<=[.!?])\s+", line)
                if len(sentences) > 3:
                    kept = sentences[0] + " […] " + sentences[-1]
                    result.append(kept)
                else:
                    result.append(line[: self.MAX_PARAGRAPH] + "…")
            else:
                result.append(line)

        return "\n".join(result)
