"""Long prose must not lose sentences nobody asked to lose.

Everything else in this pipeline removes material that is repeated or carries no
meaning — duplicate log lines, JSON keys hoisted into a schema, filler words.
Paragraph truncation removes sentences, and it decides which ones by whether a
line happens to be longer than 500 characters.

That distinction is invisible to the person pasting the text. The same document
keeps everything when it has paragraph breaks and loses almost all of it when it
does not, which is the difference between a file and the same file copied out of
a PDF. Measured before this was turned off: 160 sentences kept one way, 2 the
other — and the model is handed "first sentence [...] last sentence" with no
indication that 158 are missing.
"""

from __future__ import annotations

import random

import pytest

from sensei.compression.ccr import CCRStore
from sensei.compression.router import ContentRouter
from sensei.config import settings


def _document(sentences: int = 160) -> str:
    """Prose where every sentence is distinct.

    The first version drew from four fixed phrases and repeated itself, so the
    line-broken variant lost six sentences to duplicate-line removal — which is
    ordinary compression doing its job, not the truncation under test. A
    measurement number makes each sentence unique and keeps the two apart.
    """
    rng = random.Random(3)
    subject = ["Der Messaufbau", "Die Regelung", "Das Kamerasystem", "Der Pruefstand"]
    verb = ["zeigt", "erfordert", "liefert", "begrenzt"]
    obj = ["eine Streuung von", "einen Drift von", "eine Abweichung von", "eine Toleranz von"]
    return " ".join(
        f"{rng.choice(subject)} {rng.choice(verb)} {rng.choice(obj)} {i / 10:.1f} Prozent."
        for i in range(sentences)
    )


@pytest.fixture(autouse=True)
def _default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "text_truncate_paragraphs", False)


def test_a_long_single_line_document_keeps_its_sentences() -> None:
    """The case that was silently destroyed: prose with no line breaks."""
    doc = _document()

    result = ContentRouter(enable_caching=False).compress(doc)

    assert result.compressed.count(".") == doc.count(".")
    assert "[...]" not in result.compressed


def test_line_breaks_make_no_difference_to_what_survives() -> None:
    """The old behaviour turned on a property of the text the user cannot see.
    Whether a document keeps its content should not depend on whether it was
    pasted out of a PDF."""
    flat = _document(80)
    broken = flat.replace(". ", ".\n", 40)

    router = ContentRouter(enable_caching=False)
    assert router.compress(flat).compressed.count(".") == router.compress(broken).compressed.count(
        "."
    )


class TestWhenItIsAskedFor:
    def test_the_marker_says_how_much_went(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An ellipsis says "something is missing". A count says how much, and
        where to get it — which is the difference between a model that asks and
        one that answers around the gap."""
        monkeypatch.setattr(settings, "text_truncate_paragraphs", True)
        doc = _document()

        out = ContentRouter(enable_caching=False).compress(doc).compressed

        assert "sentences removed by Sensei" in out
        assert "ccr_id" in out
        assert out.count(".") < doc.count(".")

    def test_the_original_is_still_retrievable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Which is what makes the pointer in the marker worth printing."""
        monkeypatch.setattr(settings, "text_truncate_paragraphs", True)
        doc = _document()

        # A store has to be handed in; `enable_caching` alone only turns on the
        # in-process memo, and without this the id comes back None.
        router = ContentRouter(ccr_store=CCRStore(), enable_caching=True)
        result = router.compress(doc)

        assert result.ccr_id is not None
        assert result.original == doc
