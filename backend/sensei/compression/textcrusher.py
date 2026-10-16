"""Query-aware extractive compression for long prose.

The rule-based TextCompressor rewrites words and never drops a sentence. This
one does the opposite: it keeps whole sentences, verbatim, and drops the ones
that matter least. A sentence's score combines

- **relevance**: BM25 against the query (the user's question, the tool call),
- **salience**: numbers, paths, identifiers, negations, errors and rare words —
  the things a summary must not lose,
- **position**: the first sentences of the text and of each paragraph,

and near-duplicates (word-shingle Jaccard >= 0.85 with a kept sentence) are
suppressed. Kept sentences stay in their original order; every dropped run is
a marker carrying the CCR id. Headings, list items, code fences and short
lines are always kept, so structure survives.
"""

from __future__ import annotations

import re

from sensei.compression import relevance
from sensei.compression.markers import Context, plural

_SENTENCE_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\"'([")


def split_sentences(line: str) -> list[str]:
    r"""Split after `.`, `!` or `?` plus whitespace, when the next sentence
    starts with a capital, a digit, a quote or a bracket.

    A scan rather than `(?<=[.!?])\s+(?=[A-Z...])`: same result, and no
    regex to retry a long whitespace run from every offset."""
    out: list[str] = []
    start = i = 0
    n = len(line)
    while i < n:
        if line[i] not in ".!?":
            i += 1
            continue
        j = i + 1
        while j < n and line[j].isspace():
            j += 1
        if j > i + 1 and j < n and line[j] in _SENTENCE_START:
            out.append(line[start : i + 1])
            start = j
        i = j if j > i + 1 else i + 1
    out.append(line[start:])
    return out


_NEGATION = re.compile(
    r"\b(?:not|no|never|none|without|cannot|can't|don't|doesn't|isn't|won't|must|nicht|kein)\b",
    re.I,
)
_SALIENT = re.compile(r"\d|[/\\]\w|`|\w\.\w{1,5}\b|\b[A-Z]{2,}\b|[a-z][A-Z]|_\w")
_STRUCT = re.compile(r"^\s*(?:#|[-*+] |\d+[.)] |```|\||>)")


_MAX_POSTING = 64


def _shingles(tokens: list[str], k: int = 3) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + k]) for i in range(max(1, len(tokens) - k + 1))}


class TextCrusher:
    def __init__(self, ratio: float = 0.5, min_chars: int = 1500) -> None:
        self.ratio = ratio
        self.min_chars = min_chars

    def compress(self, text: str, ctx: Context | None = None) -> str:
        ctx = ctx or Context()
        if len(text) < self.min_chars:
            return text
        # Units: structural lines stay whole; prose lines split into sentences.
        units: list[tuple[str, bool, bool]] = []  # (text, protected, starts_paragraph)
        new_para = True
        in_fence = False
        for line in text.split("\n"):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                units.append((line, True, False))
                continue
            if in_fence or not line.strip() or _STRUCT.match(line) or len(line) < 60:
                units.append((line, True, False))
                new_para = not line.strip()
                continue
            for k, s in enumerate(split_sentences(line)):
                units.append((s, False, new_para and k == 0))
            new_para = False
            units.append(("\n", True, False))  # restores the line break
        prose = [i for i, (_, p, _) in enumerate(units) if not p]
        if len(prose) < 8:
            return text

        toks = [relevance.tokens(units[i][0]) for i in prose]
        rel = relevance.bm25(toks, relevance.tokens(ctx.query)) if ctx.query else [0.0] * len(prose)
        top = max(rel) or 1.0
        df: dict[str, int] = {}
        for t in toks:
            for w in set(t):
                df[w] = df.get(w, 0) + 1
        scores = []
        for j, i in enumerate(prose):
            s = units[i][0]
            sal = 0.0
            sal += 0.6 * min(3, len(_SALIENT.findall(s))) / 3
            sal += 0.6 * bool(_NEGATION.search(s))
            sal += 0.8 * bool(relevance.ERROR_RE.search(s))
            rare = sum(1 for w in set(toks[j]) if df[w] == 1)
            sal += 0.4 * min(1.0, rare / 4)
            pos = 1.0 if j == 0 else (0.6 if units[i][2] else 0.0)
            scores.append(2.0 * rel[j] / top + 1.5 * sal + 1.0 * pos)

        budget = int(sum(len(units[i][0]) for i in prose) * self.ratio)
        keep: set[int] = set()
        # Near-duplicate check through an index of kept shingles instead of a
        # comparison with every kept sentence, which was quadratic (39 s on
        # 1.4 MB). A posting list stops growing at _MAX_POSTING: a shingle that
        # common says little, and a real near-duplicate shares rare ones too.
        index: dict[tuple[str, ...], list[int]] = {}
        sizes: list[int] = []
        used = 0
        for j in sorted(range(len(prose)), key=lambda j: -scores[j]):
            if used >= budget:
                break
            sh = _shingles(toks[j])
            overlap: dict[int, int] = {}
            for g in sh:
                for k in index.get(g, ()):
                    overlap[k] = overlap.get(k, 0) + 1
            if any(c / max(1, len(sh) + sizes[k] - c) >= 0.85 for k, c in overlap.items()):
                continue
            kid = len(sizes)
            sizes.append(len(sh))
            for g in sh:
                posting = index.setdefault(g, [])
                if len(posting) < _MAX_POSTING:
                    posting.append(kid)
            keep.add(prose[j])
            used += len(units[prose[j]][0])

        out: list[str] = []
        dropped = 0
        line: list[str] = []
        for i, (s, protected, _) in enumerate(units):
            if protected:
                if s == "\n":
                    if dropped:
                        line.append(ctx.mark(f"{plural(dropped, 'sentence')} omitted", dropped))
                        dropped = 0
                    out.append(" ".join(line))
                    line = []
                else:
                    out.append(s)
                continue
            if i in keep:
                if dropped:
                    line.append(ctx.mark(f"{plural(dropped, 'sentence')} omitted", dropped))
                    dropped = 0
                line.append(s)
            else:
                dropped += 1
        if line:
            out.append(" ".join(line))
        return "\n".join(out)
