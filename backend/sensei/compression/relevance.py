"""Small, dependency-free relevance scoring shared by the lossy compressors.

BM25 over a handful of "documents" (rows, records, sentences) against whatever
the caller knows the model is looking for, plus the signals every compressor
wants to keep regardless of the query: errors, numbers that stand out, and
words that are rare in this payload.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+|\d+(?:\.\d+)?")
ERROR_RE = re.compile(
    r"\b(?:error|errors|fail(?:ed|ure|s)?|fatal|exception|panic|critical|denied|refused|"
    r"timeout|timed out|invalid|unauthori[sz]ed|forbidden|not found|crash(?:ed)?)\b|\b[45]\d\d\b",
    re.IGNORECASE,
)

_STOP = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "this",
        "that",
        "at",
        "by",
        "from",
        "as",
        "not",
        "no",
        "but",
        "if",
        "then",
        "than",
        "so",
        "do",
        "does",
        "did",
        "can",
        "could",
        "should",
        "would",
        "will",
        "just",
        "into",
        "out",
        "up",
        "down",
        "der",
        "die",
        "das",
        "und",
        "oder",
        "ist",
        "nicht",
        "ein",
        "eine",
        "zu",
        "mit",
        "von",
        "auf",
        "fuer",
    ]
)


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text) if t.lower() not in _STOP]


def bm25(docs: list[list[str]], query: list[str], k1: float = 1.2, b: float = 0.75) -> list[float]:
    """BM25 score of every tokenized doc against the query tokens."""
    if not docs or not query:
        return [0.0] * len(docs)
    n = len(docs)
    avg = sum(len(d) for d in docs) / n or 1.0
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    q = [t for t in dict.fromkeys(query) if t in df]
    if not q:
        return [0.0] * n
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in q}
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in q:
            f = tf.get(t, 0)
            if f:
                s += idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return scores


def otsu_threshold(values: list[float]) -> float:
    """The cut that best separates high scores from the rest (Otsu, on 32 bins)."""
    vals = [v for v in values if v > 0]
    if len(vals) < 2:
        return max(values, default=0.0)
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return lo
    bins = 32
    hist = [0] * bins
    for v in vals:
        hist[min(bins - 1, int((v - lo) / (hi - lo) * bins))] += 1
    total = len(vals)
    sum_all = sum(i * h for i, h in enumerate(hist))
    w0 = sum0 = 0.0
    best, best_k = -1.0, 0
    for k in range(bins):
        w0 += hist[k]
        if w0 in (0, total):
            continue
        sum0 += k * hist[k]
        m0 = sum0 / w0
        m1 = (sum_all - sum0) / (total - w0)
        between = w0 * (total - w0) * (m0 - m1) ** 2
        if between > best:
            best, best_k = between, k
    return lo + (best_k + 1) * (hi - lo) / bins


def kneedle(curve: list[float]) -> int | None:
    """Index of the knee of an increasing, concave coverage curve, or None."""
    n = len(curve)
    if n < 4 or curve[-1] <= curve[0]:
        return None
    y0, y1 = curve[0], curve[-1]
    best, best_i = 0.0, None
    for i, y in enumerate(curve):
        x = i / (n - 1)
        yn = (y - y0) / (y1 - y0)
        d = yn - x
        if d > best:
            best, best_i = d, i
    return best_i if best > 0.1 else None


def zscore_outliers(values: list[float], sigma: float = 2.5) -> set[int]:
    if len(values) < 8:
        return set()
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    if var <= 0:
        return set()
    sd = math.sqrt(var)
    return {i for i, v in enumerate(values) if abs(v - mean) > sigma * sd}


def change_points(values: list[float], window: int = 5, sigma: float = 2.0) -> set[int]:
    """Indices where the mean of the next window departs from the previous one."""
    n = len(values)
    if n < 4 * window:
        return set()
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    if sd <= 0:
        return set()
    out: set[int] = set()
    for i in range(window, n - window + 1):
        before = sum(values[i - window : i]) / window
        after = sum(values[i : i + window]) / window
        if abs(after - before) > sigma * sd:
            out.add(i)
    # A shift is detected at every index near it; keep the strongest per run.
    pruned: set[int] = set()
    for i in sorted(out):
        if not any(abs(i - j) < window for j in pruned):
            pruned.add(i)
    return pruned
