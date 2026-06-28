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
    def __init__(self, path: Path | str | None = None, embedder: Any = None):
        self.path = Path(path) if path is not None else Path(settings.rag_file)
        self._lock = threading.Lock()
        self._chunks: list[dict[str, Any]] = []  # {doc, text, tokens, vec?}
        self._embedder = embedder
        self._load()

    @property
    def backend(self) -> str:
        return "hybrid" if self._embedder is not None else "bm25"

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
            new: list[dict[str, Any]] = [
                {"doc": name, "text": ch, "tokens": _tokenize(ch)} for ch in chunk_text(text)
            ]
            if self._embedder is not None and new:
                try:  # embeddings are best-effort; ingestion must not fail on a network hiccup
                    for c, vec in zip(new, self._embedder.embed([c["text"] for c in new])):
                        c["vec"] = vec
                except Exception:  # noqa: BLE001
                    pass
            self._chunks.extend(new)
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
        if self._embedder is not None and any("vec" in c for c in self._chunks):
            try:
                return self._hybrid_search(query, k)
            except Exception:  # noqa: BLE001 — degrade to BM25 on any embedding failure
                pass
        return self._bm25_search(query, k)

    def _bm25_raw(self, q: list[str]) -> list[float]:
        chunks = self._chunks
        n_docs = len(chunks)
        if not q or not chunks:
            return [0.0] * n_docs
        df: dict[str, int] = {}
        for ch in chunks:
            for term in set(ch["tokens"]):
                df[term] = df.get(term, 0) + 1
        avgdl = sum(len(c["tokens"]) for c in chunks) / n_docs

        scores: list[float] = []
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
            scores.append(score)
        return scores

    def _bm25_search(self, query: str, k: int) -> list[dict[str, Any]]:
        scores = self._bm25_raw(_tokenize(query))
        ranked = sorted(
            ((s, c) for s, c in zip(scores, self._chunks) if s > 0),
            key=lambda x: x[0],
            reverse=True,
        )
        return [{"doc": c["doc"], "text": c["text"], "score": round(s, 4)} for s, c in ranked[:k]]

    def _hybrid_search(self, query: str, k: int) -> list[dict[str, Any]]:
        from sensei.rag.embeddings import cosine

        chunks = self._chunks
        if not chunks:
            return []
        qvec = self._embedder.embed([query])[0]
        cos = [cosine(qvec, c["vec"]) if c.get("vec") else 0.0 for c in chunks]
        bm = self._bm25_raw(_tokenize(query))

        def _norm(xs: list[float]) -> list[float]:
            top = max(xs) if xs else 0.0
            return [x / top if top > 0 else 0.0 for x in xs]

        cn, bn = _norm(cos), _norm(bm)
        combined = [
            (0.5 * cn[i] + 0.5 * bn[i], chunks[i]) for i in range(len(chunks))
        ]
        combined = [(s, c) for s, c in combined if s > 0]
        combined.sort(key=lambda x: x[0], reverse=True)
        return [{"doc": c["doc"], "text": c["text"], "score": round(s, 4)} for s, c in combined[:k]]


_store: DocumentStore | None = None


def get_store() -> DocumentStore:
    global _store
    if _store is None:
        from sensei.rag.embeddings import get_embedding_backend

        _store = DocumentStore(embedder=get_embedding_backend())
    return _store
