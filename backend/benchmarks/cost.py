"""Tokens → dollars, net of prompt caching.

"X% fewer tokens" overstates what a coding agent saves in money, because most
of an agent's input is a cached prefix that already costs a fraction of the
list price, and output tokens are not touched by input compression at all.

How a cached agent session is billed (Anthropic semantics; OpenAI is the same
shape with no write premium):

* every request re-sends the whole conversation;
* the part that was sent before is a **cache read** (0.1x list, 0.05x on the
  Claude 5.5 family);
* what is new since the last request — the previous answer, the new tool
  results, the new user message — is a **cache write** (1.25x for the 5-minute
  TTL) or, without caching, plain uncached input (1x);
* output is billed separately and compression does not change it.

So a tool result of ``n`` tokens that enters at request ``i`` of ``R`` costs
``n x price x (write + read x (R - i - 1))`` until the context is compacted.
Compressing it saves exactly that much per saved token — which is what
``tool_result_savings`` computes, and what ``simulate_session`` applies to a
whole synthetic session.

Assumptions, stated once: the cache never expires mid-session (an active agent
calls more often than every five minutes), the provider caches the whole prefix
up to the last block (Claude Code's breakpoint placement), and compression is
deterministic so the compressed prefix caches exactly as well as the original —
which Sensei's gateway guarantees and ``tests/test_prompt_cache.py`` checks.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Pricing:
    model: str
    input_per_mtok: float
    output_per_mtok: float
    cache_write: float = 1.25
    cache_read: float = 0.1

    def per_token(self) -> float:
        return self.input_per_mtok / 1_000_000


#: List prices checked 2026-10-16 (platform.claude.com / developers.openai.com).
PRICES: dict[str, Pricing] = {
    "claude-opus-5-5": Pricing("claude-opus-5-5", 4.0, 20.0, 1.25, 0.05),
    "claude-sonnet-5-5": Pricing("claude-sonnet-5-5", 2.0, 10.0, 1.25, 0.05),
    "claude-fable-5-1": Pricing("claude-fable-5-1", 10.0, 50.0, 1.25, 0.025),
    "gpt-6.1-sol": Pricing("gpt-6.1-sol", 2.0, 10.0, 1.0, 0.05),
    # The textbook multipliers, for anyone comparing with older write-ups.
    "generic": Pricing("generic", 3.0, 15.0, 1.25, 0.1),
}

DEFAULT_MODEL = "claude-opus-5-5"


@dataclass
class Bill:
    cache_write: float = 0.0
    cache_read: float = 0.0
    uncached: float = 0.0
    output: float = 0.0

    @property
    def input(self) -> float:
        return self.cache_write + self.cache_read + self.uncached

    @property
    def total(self) -> float:
        return self.input + self.output

    def as_dict(self) -> dict[str, float]:
        return {**{k: round(v, 6) for k, v in asdict(self).items()}, "total": round(self.total, 6)}


@dataclass(frozen=True)
class Turn:
    """One request: what entered the context since the last one, and the answer."""

    new_input: int
    output: int


def bill(turns: Sequence[Turn], price: Pricing, *, prefix: int = 0, cached: bool = True) -> Bill:
    """Dollars for a session. ``prefix``: system prompt + tool schemas."""
    b = Bill()
    ptok = price.per_token()
    context = 0
    pending = prefix  # written on the first request
    for turn in turns:
        new = pending + turn.new_input
        if cached:
            b.cache_read += context * ptok * price.cache_read
            b.cache_write += new * ptok * price.cache_write
        else:
            b.uncached += (context + new) * ptok
        b.output += turn.output * price.output_per_mtok / 1_000_000
        context += new
        # The answer is part of the next request's new input.
        pending = turn.output
    return b


def tool_result_savings(saved_tokens: int, later_requests: int, price: Pricing) -> float:
    """Dollars saved by removing ``saved_tokens`` from one tool result."""
    return (
        saved_tokens * price.per_token() * (price.cache_write + price.cache_read * later_requests)
    )


@dataclass(frozen=True)
class SessionShape:
    """A synthetic session to put corpus samples into.

    Defaults are rounded from the real Claude Code sessions this was built
    against (``session_replay`` prints the measured values): a ~20k-token
    system prompt with tool schemas, one tool result per request, short
    answers, and every result staying in context until the session ends.
    """

    system_tokens: int = 20_000
    user_tokens: int = 200
    output_tokens: int = 350


def simulate(
    tool_tokens: Iterable[int], shape: SessionShape, price: Pricing, *, cached: bool = True
) -> Bill:
    sizes = list(tool_tokens)
    turns = [Turn(shape.user_tokens, shape.output_tokens)]
    turns += [Turn(n, shape.output_tokens) for n in sizes]
    return bill(turns, price, prefix=shape.system_tokens, cached=cached)


def compare(
    before: Sequence[int],
    after: Sequence[int],
    shape: SessionShape | None = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Same session twice — original and compressed tool results — priced both ways."""
    shape = shape or SessionShape()
    price = PRICES[model]
    out: dict = {"model": model, "pricing": asdict(price), "shape": asdict(shape)}
    for label, cached in (("cached", True), ("uncached", False)):
        b0 = simulate(before, shape, price, cached=cached)
        b1 = simulate(after, shape, price, cached=cached)
        out[label] = {
            "before": b0.as_dict(),
            "after": b1.as_dict(),
            "saved_usd": round(b0.total - b1.total, 6),
            "saved_pct": round((1 - b1.total / b0.total) * 100, 2) if b0.total else 0.0,
            "input_saved_pct": round((1 - b1.input / b0.input) * 100, 2) if b0.input else 0.0,
        }
    return out
