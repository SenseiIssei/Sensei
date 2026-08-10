"""Guardrail: compression must not delete the facts an agent needs.

The same check the nightly `fact retention` job runs, in the normal test suite
so that a pull request fails on it immediately rather than overnight. It costs
milliseconds and it is the only automated check in this repository that looks at
*what* compression kept rather than *how much* it removed.
"""

from __future__ import annotations

import pytest

from benchmarks.quality_eval import CORPUS, evaluate


def test_no_fact_is_lost() -> None:
    data = evaluate()
    lost = [(case["name"], fact) for case in data["cases"] for fact in case["missing"]]
    assert not lost, "compression dropped facts an agent would need: " + ", ".join(
        f"{name}: {fact!r}" for name, fact in lost
    )
    assert data["aggregate"]["retention_pct"] == 100.0


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
def test_every_case_declares_something_to_check(case) -> None:
    """A case with no facts would pass silently and prove nothing."""
    assert case.facts, f"{case.name} declares no facts"
    for fact in case.facts:
        assert fact in case.content, (
            f"{case.name} expects {fact!r} to survive compression, but it is not "
            f"in the input to begin with — the case is testing nothing."
        )


def test_compression_still_happens() -> None:
    """Retention is trivially 100% if nothing is compressed.

    Without this, the honest way to pass the retention gate would be to turn
    compression off, which is exactly the failure mode a one-sided metric
    invites.
    """
    data = evaluate()
    assert data["aggregate"]["size_reduction_pct"] > 25
