"""`sensei stats` — how much the compression has actually saved you.

The savings tracker lives in the server process and is never persisted (zero
telemetry), so this asks the running server rather than reading a file.
"""

from __future__ import annotations

import sys

from sensei.cli.wrap import gateway_base


def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}" if v >= 0.01 else f"${v:.4f}"


def run() -> int:
    import asyncio

    async def fetch() -> dict | None:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=4.0) as c:
                r = await c.get(f"{gateway_base()}/api/stats")
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

    s = data.get("savings", data)
    requests = s.get("requests", 0)

    print("\nCompression savings\n")
    if not requests:
        print("  Nothing routed through Sensei yet.")
        print("\n  Point a tool at it:  sensei wrap claude")
        return 0

    print(f"  Requests          {requests:,}")
    print(f"  Tokens in         {s.get('tokens_before', 0):,}")
    print(f"  Tokens sent       {s.get('tokens_after', 0):,}")
    print(f"  Tokens saved      {s.get('tokens_saved', 0):,}  ({s.get('percent_saved', 0)}%)")
    print(f"  Estimated saving  {_fmt_usd(s.get('estimated_cost_saved_usd', 0.0))}")
    print(
        f"\n  Priced at {_fmt_usd(s.get('price_per_million_usd', 0.0))} per million input tokens"
        " (SENSEI_USD_PER_MILLION_TOKENS)."
    )
    print("  Counters are in-memory and reset when the server restarts.")
    return 0
