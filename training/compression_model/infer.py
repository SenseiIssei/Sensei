"""Inference for the Sensei-Compressor — a learned, drop-in TextCompressor.

Loads the trained token-importance model and drops the lowest-importance words
to hit a target ratio (or a fixed keep-probability threshold). Falls back to no
change if a token can't be scored.

    PYTHONPATH=../../backend python infer.py --config config.yaml --text "..."
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

_WORD_RE = re.compile(r"\w+|[^\w\s]")
_PUNCT = re.compile(r"^[^\w\s]$")


class LearnedTextCompressor:
    """Token-importance prose compressor. Same `compress(text)` surface as the
    rule-based ``TextCompressor`` so it can drop straight into ``ContentRouter``.
    """

    def __init__(self, model_dir: str, keep_threshold: float = 0.5, max_length: int = 256):
        try:
            import torch
            from transformers import AutoTokenizer, DistilBertForTokenClassification
        except ImportError as exc:  # pragma: no cover - heavy optional deps
            raise SystemExit(
                "Inference deps missing. Install: pip install -r requirements.txt\n"
                f"(import error: {exc})"
            )
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

    def compress(self, text: str, target_ratio: float | None = None) -> str:
        words = _WORD_RE.findall(text)
        if not words:
            return text
        probs = self._keep_probs(words)

        if target_ratio is not None:
            # Keep the highest-importance words until we hit the target length.
            keep_n = max(1, int(len(words) * target_ratio))
            cutoff = sorted(probs, reverse=True)[keep_n - 1]
            threshold = cutoff
        else:
            threshold = self.keep_threshold

        kept = [w for w, p in zip(words, probs) if p >= threshold or _PUNCT.match(w)]
        out = " ".join(kept)
        out = re.sub(r"\s+([,.;:!?])", r"\1", out)  # tidy punctuation spacing
        return out.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--text", required=True)
    ap.add_argument("--target-ratio", type=float, default=None)
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    comp = LearnedTextCompressor(
        model_dir=cfg["output_dir"],
        keep_threshold=float(cfg.get("keep_threshold", 0.5)),
        max_length=int(cfg.get("max_length", 256)),
    )
    out = comp.compress(args.text, target_ratio=args.target_ratio)
    print("--- original  ---\n" + args.text)
    print("--- compressed ---\n" + out)
    print(f"\nwords: {len(_WORD_RE.findall(args.text))} -> {len(_WORD_RE.findall(out))}")


if __name__ == "__main__":
    main()
