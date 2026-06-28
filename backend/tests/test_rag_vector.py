from __future__ import annotations

from sensei.rag.embeddings import cosine, get_embedding_backend
from sensei.rag.store import DocumentStore


class _FakeEmbedder:
    """Toy 3-D semantic space: [vehicle, finance, animal]."""

    _AXES = (
        ("car", "automobile", "vehicle", "truck", "drive"),
        ("money", "bank", "finance", "loan", "credit"),
        ("dog", "cat", "animal", "pet", "puppy"),
    )

    def _vec(self, text: str) -> list[float]:
        t = text.lower()
        return [float(sum(w in t for w in axis)) for axis in self._AXES]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def test_cosine_basic():
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([], [1]) == 0.0


def test_hybrid_beats_lexical_gap(tmp_path):
    store = DocumentStore(path=tmp_path / "rag.json", embedder=_FakeEmbedder())
    assert store.backend == "hybrid"
    store.add_document("vehicles", "The automobile market grew strongly this year.")
    store.add_document("finance", "Banks now offer cheaper loans and credit.")
    store.add_document("animals", "Dogs make wonderful loyal pets.")

    # "car" never appears lexically — BM25 alone would miss the vehicles doc.
    results = store.search("I want to buy a car", k=1)
    assert results and results[0]["doc"] == "vehicles"


def test_falls_back_to_bm25_when_embedder_errors(tmp_path):
    class _Broken:
        def embed(self, texts):
            raise RuntimeError("embeddings down")

    store = DocumentStore(path=tmp_path / "rag.json", embedder=_Broken())
    # add_document swallows the embedding error; chunks still indexed for BM25.
    assert store.add_document("d", "alpha beta gamma delta") == 1
    results = store.search("gamma", k=1)
    assert results and results[0]["doc"] == "d"


def test_get_embedding_backend_disabled_by_default(monkeypatch):
    from sensei.config import settings

    monkeypatch.setattr(settings, "embeddings_enabled", False)
    assert get_embedding_backend() is None
    monkeypatch.setattr(settings, "embeddings_enabled", True)
    monkeypatch.setattr(settings, "embeddings_api_key", "")
    assert get_embedding_backend() is None  # no key → still None
