"""`sensei stats` — how much the compression has actually saved you.

Reads the running server rather than the ledger file directly, so the numbers
here are the same ones the dashboard is showing, from the same query.
"""

from __future__ import annotations

import sys
from typing import Any

from sensei.cli.wrap import gateway_base


def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}" if v >= 0.01 else f"${v:.4f}"


def _block(title: str, s: dict[str, Any]) -> None:
    print(f"\n{title}\n")
    print(f"  Requests          {s.get('requests', 0):,}")
    print(f"  Tokens in         {s.get('tokens_before', 0):,}")
    print(f"  Tokens sent       {s.get('tokens_after', 0):,}")
    print(f"  Tokens saved      {s.get('tokens_saved', 0):,}  ({s.get('percent_saved', 0)}%)")
    print(f"  Estimated saving  {_fmt_usd(s.get('estimated_cost_saved_usd', 0.0))}")


def _table(title: str, rows: list[dict[str, Any]]) -> None:
    rows = [r for r in rows if r.get("tokens_saved")]
    if not rows:
        return
    print(f"\n{title}\n")
    width = max(len(str(r.get("key", ""))) for r in rows)
    for row in rows:
        key = str(row.get("key", ""))
        print(
            f"  {key:<{width}}  {row.get('tokens_saved', 0):>12,}  "
            f"{row.get('percent_saved', 0):>5}%  {_fmt_usd(row.get('estimated_cost_saved_usd', 0.0))}"
        )


def _output_effect(effect: dict[str, Any]) -> None:
    """Report the shaping experiment, or why there is nothing to report.

    Deliberately prints the interval before the point estimate. A reader who
    stops after one line should have seen the uncertainty, not the headline.
    """
    if not effect or not effect.get("enabled"):
        return

    shaped = effect.get("shaped", {})
    control = effect.get("control", {})
    print("\nOutput shaping\n")
    print(
        f"  Shaped     {shaped.get('requests', 0):>6,} requests, "
        f"{shaped.get('mean_output_tokens', 0):>7} tokens/answer on average"
    )
    print(
        f"  Control    {control.get('requests', 0):>6,} requests, "
        f"{control.get('mean_output_tokens', 0):>7} tokens/answer on average"
    )

    verdict = effect.get("verdict", "")
    if "confidence_interval_95" not in effect:
        print(f"\n  {verdict.capitalize()}. {effect.get('detail', '')}")
        return

    low, high = effect["percent_interval_95"]
    print(f"\n  95% confident the change is between {low}% and {high}%")
    print(f"  Best estimate: {effect['percent']}% ({effect['difference_tokens']} tokens/answer)")
    print(f"  Verdict: {verdict}")
    print("\n  Non-streaming responses only — streaming replies report no usage block.")


def run() -> int:
    import asyncio

    async def fetch() -> dict | None:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=4.0) as c:
                r = await c.get(f"{gateway_base()}/api/stats/savings")
                if r.status_code == 200:
                    return r.json()
                print(f"Server responded {r.status_code}.", file=sys.stderr)
        except Exception as exc:
            print(f"Couldn't reach Sensei at {gateway_base()}: {exc}", file=sys.stderr)
        return None

    data = asyncio.run(fetch())
    if data is None:
        print("\nStart it first:  sensei up", file=sys.stderr)
        return 1

    lifetime = data.get("lifetime", {})
    session = data.get("session", {})

    if not lifetime.get("requests"):
        print("\nNothing has been routed through Sensei yet.\n")
        print("  Connect the tools you already have:  sensei setup-tools")
        print("  Or route one by hand:                sensei wrap claude")
        return 0

    _block("All time", lifetime)
    # Only worth a second block when the two differ — on a server that has been
    # up since the first request they are the same numbers twice.
    if session.get("requests") != lifetime.get("requests"):
        _block("This session", session)

    _table("By tool", data.get("by_tool", []))
    _table("By provider", data.get("by_provider", []))
    _output_effect(data.get("output_effect") or {})

    price = lifetime.get("price_per_million_usd", 0.0)
    print(
        f"\n  Priced at {_fmt_usd(price)} per million input tokens (SENSEI_USD_PER_MILLION_TOKENS)."
    )
    if not data.get("persisted", True):
        print("  History is off (SENSEI_SAVINGS_PERSIST=false) — these reset on restart.")
    return 0
