"""Optional learned prose compressor (the trained Sensei-Compressor).

Loads the DistilBERT token-importance checkpoint produced by
``training/compression_model/train.py`` and drops low-importance words. Same
``compress(text)`` surface as the rule-based ``TextCompressor`` so it slots
straight into ``ContentRouter``.

Everything here is best-effort and lazy: if the feature is disabled, the
checkpoint is missing, or torch/transformers aren't installed, the loader
returns ``None`` and the router transparently falls back to the rule-based
compressor. The heavy model is loaded once (module-level singleton).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sensei.config import settings

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\w+|[^\w\s]")
_PUNCT = re.compile(r"^[^\w\s]$")


def _tidy(out: str) -> str:
    """Clean up artifacts left by dropping words: dangling/duplicate punctuation."""
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)        # space before punctuation
    out = re.sub(r"([,;:]\s*){2,}", ", ", out)        # collapse repeated commas
    out = re.sub(r"\s*([.!?])[\s.,;:]*", r"\1 ", out)  # one terminator, then a space
    out = re.sub(r"^[\s,;:.]+", "", out)              # strip leading punctuation
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out[:1].upper() + out[1:] if out else out


class LearnedTextCompressor:
    def __init__(self, model_dir: str, keep_threshold: float = 0.5, max_length: int = 256):
        import torch  # heavy, optional — imported only when actually loading
        from transformers import AutoTokenizer, DistilBertForTokenClassification

        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = DistilBertForTokenClassification.from_pretrained(model_dir)
        self.model.eval()
        self.keep_threshold = keep_threshold
        self.max_length = max_length
        self.keep_label = self.model.config.label2id.get("KEEP", 1)

    def _keep_probs(self, words: list[str]) -> list[float]:
        torch = self._torch
        enc = self.tokenizer(
            words,
            is_split_into_words=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        )
        with torch.no_grad():
            logits = self.model(**enc).logits[0]
        probs = torch.softmax(logits, dim=-1)[:, self.keep_label]
        word_ids = enc.word_ids(batch_index=0)
        out: list[float] = [1.0] * len(words)
        prev = None
        for idx, wid in enumerate(word_ids):
            if wid is not None and wid != prev:
                out[wid] = float(probs[idx])
            prev = wid
        return out

    def compress(self, text: str) -> str:
        words = _WORD_RE.findall(text)
        if not words:
            return text
        probs = self._keep_probs(words)
        kept = [w for w, p in zip(words, probs) if p >= self.keep_threshold or _PUNCT.match(w)]
        return _tidy(" ".join(kept)) or text


_loaded = False
_instance: LearnedTextCompressor | None = None


def get_prose_compressor() -> LearnedTextCompressor | None:
    """Return the learned compressor if available, else None (→ rule-based)."""
    global _loaded, _instance
    if _loaded:
        return _instance
    _loaded = True
    if not settings.learned_compressor_enabled:
        return None
    path = Path(settings.learned_compressor_path)
    if not path.exists():
        logger.warning("Learned compressor enabled but no checkpoint at %s; using rule-based.", path)
        return None
    try:
        _instance = LearnedTextCompressor(
            str(path),
            keep_threshold=settings.learned_keep_threshold,
            max_length=settings.learned_max_length,
        )
        logger.info("Loaded learned prose compressor from %s", path)
    except Exception as e:  # noqa: BLE001 — never let model loading break the server
        logger.warning("Failed to load learned compressor (%s); using rule-based.", e)
        _instance = None
    return _instance


def reset_cache() -> None:
    """Drop the cached singleton (used by tests / after a config change)."""
    global _loaded, _instance
    _loaded = False
    _instance = None
