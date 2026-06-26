from __future__ import annotations

import re


class TextCompressor:
    """Compress prose/text by removing verbosity while preserving meaning.

    Zero-dependency and rule-based (no model needed at this tier). Strategies:
    - Replace verbose phrases with concise equivalents ("in order to" -> "to")
    - Delete filler words and discourse markers ("basically", "in fact", ...)
    - Collapse repeated whitespace, blank lines, and duplicate lines
    - Truncate very long paragraphs with a summary marker

    The transform is lossy but readable: punctuation left dangling by a deletion
    is cleaned up and sentence capitalization is restored. The full original is
    kept in the CCR store, so the model can always retrieve it on demand.
    """

    # Verbose phrase -> concise equivalent. Applied longest-first, case-insensitive.
    PHRASE_REPLACEMENTS = {
        "in order to": "to",
        "due to the fact that": "because",
        "owing to the fact that": "because",
        "in spite of the fact that": "although",
        "despite the fact that": "although",
        "in the event that": "if",
        "for the purpose of": "for",
        "with regard to": "about",
        "with respect to": "about",
        "in relation to": "about",
        "a large number of": "many",
        "a great deal of": "much",
        "the vast majority of the": "most of the",
        "the majority of the": "most of the",
        "the vast majority of": "most",
        "the majority of": "most",
        "a majority of": "most",
        "a number of": "several",
        "all of the": "all the",
        "at this point in time": "now",
        "at the present time": "now",
        "in a timely manner": "promptly",
        "on a regular basis": "regularly",
        "has the ability to": "can",
        "have the ability to": "can",
        "is able to": "can",
        "are able to": "can",
        "is going to": "will",
        "are going to": "will",
        "make sure that": "ensure",
        "various different": "various",
    }

    # Filler words / discourse markers deleted entirely (with surrounding commas).
    FILLER = [
        "basically", "actually", "really", "very", "quite", "simply",
        "literally", "essentially", "obviously", "clearly", "honestly",
        "totally", "definitely", "certainly", "arguably", "ultimately",
        "in fact", "of course", "as a matter of fact", "at the end of the day",
        "for all intents and purposes", "needless to say",
        "it goes without saying that", "generally speaking",
        "as you can see", "as we can see", "as you know",
        "it is very important to note that", "it is important to note that",
        "it is worth noting that", "it should be noted that",
        "please note that",
    ]

    # Standalone boilerplate sentences / references to strip.
    BOILERPLATE = [
        r"As mentioned (?:earlier|above|before)\s*,?\s*",
        r"As (?:stated|described) (?:earlier|above)\s*,?\s*",
        r"For more (?:information|details)\s*,?\s*see\s+\S+\s*",
        r"See (?:the )?(?:documentation|docs|README|guide) for more details\.?",
    ]

    # Max paragraph length before truncation.
    MAX_PARAGRAPH = 500

    def __init__(self) -> None:
        # Precompile; longest phrase first so multi-word matches win.
        self._replacements = [
            (re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE), v)
            for k, v in sorted(
                self.PHRASE_REPLACEMENTS.items(), key=lambda kv: len(kv[0]), reverse=True
            )
        ]
        self._fillers = [
            re.compile(rf"\s*,?\s*\b{re.escape(f)}\b\s*,?\s*", re.IGNORECASE)
            for f in sorted(self.FILLER, key=len, reverse=True)
        ]
        self._boilerplate = [re.compile(p, re.IGNORECASE) for p in self.BOILERPLATE]

    def compress(self, text: str) -> str:
        """Compress prose text."""
        # 1. Strip boilerplate references.
        for pat in self._boilerplate:
            text = pat.sub("", text)

        # 2. Replace verbose phrases with concise equivalents.
        for pat, repl in self._replacements:
            text = pat.sub(repl, text)

        # 3. Delete filler words / discourse markers, leaving a single space.
        for pat in self._fillers:
            text = pat.sub(" ", text)

        # 4. Repair punctuation/whitespace left behind by the deletions.
        text = self._cleanup(text)

        # 5. Collapse blank lines and duplicate lines.
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = self._dedupe_lines(text)

        # 6. Truncate very long paragraphs.
        text = self._truncate_paragraphs(text)

        # 7. Restore sentence capitalization and trim.
        text = self._fix_caps(text)
        return text.strip()

    def _cleanup(self, text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)                # collapse spaces/tabs
        text = re.sub(r" *\n *", "\n", text)               # trim around newlines
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)       # no space before punctuation
        text = re.sub(r"(,\s*){2,}", ", ", text)           # collapse repeated commas
        text = re.sub(r"^[ \t]*[,;:][ \t]*", "", text, flags=re.MULTILINE)  # leading punct
        return text

    def _dedupe_lines(self, text: str) -> str:
        seen: set[str] = set()
        deduped: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped and len(stripped) > 20 and stripped in seen:
                continue
            if stripped:
                seen.add(stripped)
            deduped.append(line)
        return "\n".join(deduped)

    def _truncate_paragraphs(self, text: str) -> str:
        result: list[str] = []
        for line in text.split("\n"):
            if len(line) > self.MAX_PARAGRAPH:
                sentences = re.split(r"(?<=[.!?])\s+", line)
                if len(sentences) > 3:
                    result.append(sentences[0] + " […] " + sentences[-1])
                else:
                    result.append(line[: self.MAX_PARAGRAPH] + "…")
            else:
                result.append(line)
        return "\n".join(result)

    def _fix_caps(self, text: str) -> str:
        """Capitalize the first letter at start-of-text, after a sentence
        terminator, or after a newline — undoing case lost to deletions."""
        return re.sub(
            r"(^\s*|[.!?]\s+|\n\s*)([a-z])",
            lambda m: m.group(1) + m.group(2).upper(),
            text,
        )
