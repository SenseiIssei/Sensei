"""Local document store with BM25 retrieval — zero-dependency RAG.

Documents are chunked, tokenized, and scored with Okapi BM25 at query time. No
embedding model or API key required, so it works fully offline. Chunks persist
to a JSON file. (A vector/embedding backend can slot in behind this interface.)
"""
from __future__ import annotations

import json
import math
import re
import threading
from pathlib import Path
from typing import Any

from sensei.config import settings

_TOKEN = re.compile(r"[a-z0-9]+")
_K1 = 1.5
_B = 0.75


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 1]


def chunk_text(text: str, target: int = 600) -> list[str]:
    """Split into ~target-char chunks on paragraph boundaries, hard-splitting
    any paragraph that's far too long."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    merged: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) + 1 > target:
            merged.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        merged.append(cur)

    out: list[str] = []
    for c in merged:
        if len(c) <= target * 2:
            out.append(c)
        else:
            for i in range(0, len(c), target):
                out.append(c[i : i + target])
    if not out and text.strip():
        out.append(text.strip())
    return out


class DocumentStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else Path(settings.rag_file)
        self._lock = threading.Lock()
        self._chunks: list[dict[str, Any]] = []  # {doc, text, tokens}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._chunks = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._chunks = []

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._chunks, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def add_document(self, name: str, text: str) -> int:
        with self._lock:
            self._chunks = [c for c in self._chunks if c["doc"] != name]  # replace existing
            for ch in chunk_text(text):
                self._chunks.append({"doc": name, "text": ch, "tokens": _tokenize(ch)})
            self._save()
            return sum(1 for c in self._chunks if c["doc"] == name)

    def delete_document(self, name: str) -> int:
        with self._lock:
            before = len(self._chunks)
            self._chunks = [c for c in self._chunks if c["doc"] != name]
            removed = before - len(self._chunks)
            if removed:
                self._save()
            return removed

    def list_documents(self) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for c in self._chunks:
            counts[c["doc"]] = counts.get(c["doc"], 0) + 1
        return [{"name": name, "chunks": n} for name, n in sorted(counts.items())]

    def search(self, query: str, k: int = 4) -> list[dict[str, Any]]:
        q = _tokenize(query)
        chunks = self._chunks
        if not q or not chunks:
            return []

        n_docs = len(chunks)
        df: dict[str, int] = {}
        for ch in chunks:
            for term in set(ch["tokens"]):
                df[term] = df.get(term, 0) + 1
        avgdl = sum(len(c["tokens"]) for c in chunks) / n_docs

        scored: list[tuple[float, dict[str, Any]]] = []
        for ch in chunks:
            dl = len(ch["tokens"])
            tf: dict[str, int] = {}
            for term in ch["tokens"]:
                tf[term] = tf.get(term, 0) + 1
            score = 0.0
            for term in q:
                f = tf.get(term, 0)
                if not f:
                    continue
                idf = math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1)
                score += idf * (f * (_K1 + 1)) / (f + _K1 * (1 - _B + _B * dl / avgdl))
            if score > 0:
                scored.append((score, ch))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"doc": c["doc"], "text": c["text"], "score": round(s, 4)} for s, c in scored[:k]]


_store: DocumentStore | None = None


def get_store() -> DocumentStore:
    global _store
    if _store is None:
        _store = DocumentStore()
    return _store
