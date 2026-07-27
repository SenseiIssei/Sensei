"""Shared test fixtures.

The rate limiter is a process-wide singleton with a sliding 60-second window,
and `TestClient` requests all arrive from the same client id. Without this the
suite silently accumulates: every test that makes an HTTP call spends part of a
shared budget, and once the total crosses the limit, whichever tests happen to
run last start failing with 429s that have nothing to do with what they assert.

That is exactly what happened when the setup-API tests were added — ten new
requests pushed the total over, and two webhook tests started failing. The
tests were fine; the isolation was missing.
"""

from __future__ import annotations

import pytest

from sensei.security.rate_limit import rate_limiter


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    """Give every test a fresh rate-limit budget."""
    rate_limiter.reset_all()
    yield
    rate_limiter.reset_all()
