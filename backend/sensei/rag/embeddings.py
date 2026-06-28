"""Optional embedding backend for semantic RAG.

Off by default (``SENSEI_EMBEDDINGS_ENABLED=false``) so the store stays
zero-dependency and fully offline. When enabled and an API key is configured,
chunks are embedded via any OpenAI-compatible ``/embeddings`` endpoint and the
store does hybrid (BM25 + cosine) retrieval. Any embedding failure degrades
gracefully back to BM25.
"""
from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

import httpx

from sensei.config import settings


@runtime_checkable
class EmbeddingBackend(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAIEmbeddingBackend:
    """Calls any OpenAI-compatible POST /embeddings endpoint (sync)."""

    def __init__(self, base_url: str, model: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        return [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def get_embedding_backend() -> EmbeddingBackend | None:
    if not settings.embeddings_enabled:
        return None
    key = settings.embeddings_api_key
    if not key:
        return None
    return OpenAIEmbeddingBackend(settings.embeddings_base_url, settings.embeddings_model, key)
