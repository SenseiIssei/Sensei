"""What invisible characters cost, on content that really carries them.

The claim this feature is sold on is a token overhead, so it gets measured the
same way the compression claim does: real `tiktoken` counts, a fixed corpus, and
a floor CI can fail on.

    python benchmarks/invisible_benchmark.py
    python benchmarks/invisible_benchmark.py --json out.json --min-overhead 15

The corpus is not adversarial. Every entry is something an ordinary paste
produces: a zero-width space per line out of a rendered web page, a BOM from a
Windows editor, non-breaking spaces out of a wiki. The Trojan Source sample is
the exception and is there for the security half rather than the cost half.
"""

from __future__ import annotations

import argparse
import json
import sys

from sensei.compression import invisible

ZWSP = chr(0x200B)
BOM = chr(0xFEFF)
NBSP = chr(0x00A0)
RLO = chr(0x202E)
PDF = chr(0x202C)


def _source() -> str:
    return (
        "def handle(request):\n    payload = parse(request.body)\n    return process(payload)\n"
    ) * 25


def _markdown() -> str:
    return (
        "## Setup\n\n"
        "Install the dependencies and run the server.\n\n"
        "```bash\nnpm ci && npm run dev\n```\n\n"
    ) * 12


CORPUS: tuple[tuple[str, str, str], None] | tuple = (
    # name, clean text, how it arrives after a paste
    ("code pasted from a rendered page", _source(), lambda t: t.replace("\n", ZWSP + "\n")),
    ("code with a stray BOM per block", _source(), lambda t: t.replace("def ", BOM + "def ")),
    ("markdown out of a wiki", _markdown(), lambda t: t.replace(" ", NBSP, 60)),
    (
        "source carrying a Trojan Source override",
        _source(),
        lambda t: t.replace("return process(payload)", f"return process(payload)  # {RLO}x{PDF}"),
    ),
)


def _tokeniser():
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda s: len(enc.encode(s))), "tiktoken/cl100k"
    except Exception:  # pragma: no cover - offline fallback
        return (lambda s: max(1, len(s) // 4)), "estimate (len//4)"


def measure() -> dict:
    tok, metric = _tokeniser()
    samples = []
    total_dirty = total_clean = 0

    for name, clean, dirty_fn in CORPUS:
        dirty = dirty_fn(clean)
        stripped, findings = invisible.clean(dirty, is_code="markdown" not in name)

        d, s = tok(dirty), tok(stripped)
        total_dirty += d
        total_clean += s
        samples.append(
            {
                "name": name,
                "tokens_as_pasted": d,
                "tokens_after_stripping": s,
                "overhead_pct": round((d - s) / s * 100, 1) if s else 0.0,
                "invisible_removed": findings.invisible,
                "bidi_removed": findings.bidi,
                "nbsp_seen": findings.nbsp,
            }
        )

    return {
        "metric": metric,
        "samples": samples,
        "aggregate": {
            "tokens_as_pasted": total_dirty,
            "tokens_after_stripping": total_clean,
            "overhead_pct": round((total_dirty - total_clean) / total_clean * 100, 1)
            if total_clean
            else 0.0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", metavar="PATH", help="write results here ('-' for stdout)")
    parser.add_argument(
        "--min-overhead",
        type=float,
        default=None,
        metavar="PCT",
        help="exit non-zero if the overhead removed falls below this — a regression "
        "here means the stripper stopped stripping",
    )
    args = parser.parse_args()

    data = measure()
    print(f"Token metric: {data['metric']}\n")
    print(f"{'sample':<42}{'pasted':>8}{'clean':>8}{'waste':>8}{'removed':>9}{'seen':>6}")
    print("-" * 79)
    for s in data["samples"]:
        removed = s["invisible_removed"] + s["bidi_removed"]
        print(
            f"{s['name']:<42}{s['tokens_as_pasted']:>8}{s['tokens_after_stripping']:>8}"
            f"{s['overhead_pct']:>7.0f}%{removed:>9}{s['nbsp_seen']:>6}"
        )
    agg = data["aggregate"]
    print("-" * 79)
    print(
        f"{'AGGREGATE':<42}{agg['tokens_as_pasted']:>8}"
        f"{agg['tokens_after_stripping']:>8}{agg['overhead_pct']:>7.0f}%"
    )
    print("\nWaste is what you were billed for characters that render as nothing.")
    print(
        "`seen` is non-breaking spaces: counted, never rewritten, because an NBSP is\n"
        "deliberate in typeset prose. SENSEI_STRIP_NBSP=true turns that into a space."
    )

    if args.json:
        payload = json.dumps(data, indent=2)
        if args.json == "-":
            print(payload)
        else:
            with open(args.json, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")

    if args.min_overhead is not None and agg["overhead_pct"] < args.min_overhead:
        print(
            f"\nFAIL: only {agg['overhead_pct']}% of overhead removed, "
            f"floor is {args.min_overhead}%",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
