"""Sensei (and optionally Headroom) on the seeded agent corpus.

    python -m benchmarks.agent_bench                       # Sensei only
    python -m benchmarks.agent_bench --headroom            # head-to-head
    python -m benchmarks.agent_bench --check results/agent_corpus.json --max-drop 1

What is measured, per sample and per tool:

* tokens before and after, with **one** tokenizer (tiktoken cl100k) over the
  text the model would receive — neither tool's own estimate is used;
* whether every required fact is still literally present;
* whether file reads came back byte-exact (they are edited next by exact
  string match, so any change is a defect);
* the latency of the compress call alone, p50 and p95 over every call;
* what the savings are worth in dollars once prompt caching is accounted for
  (``benchmarks.cost``).

The denominator is the original tool output, the same for both tools. The
``agent`` group is everyday coding-agent traffic; the ``headroom:*`` groups
are the four scenarios of Headroom's published table, rebuilt from scratch.

``--check`` re-measures and compares with a committed results file. It fails
when Sensei's savings drop by more than ``--max-drop`` points, when a fact
that used to survive is lost, or when a file read stops being byte-exact. That
is what the nightly workflow runs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

from benchmarks import cost
from benchmarks.corpus import (
    DEFAULT_SEED,
    HEADROOM_PUBLISHED,
    HEADROOM_SCENARIOS,
    KINDS,
    Sample,
    build_corpus,
    corpus_digest,
)
from benchmarks.harness import (
    RESULTS,
    HeadroomCompressor,
    Output,
    SenseiCompressor,
    Tokenizer,
    default_headroom_python,
    median_ms,
    missing_facts,
    percentile,
    read_json,
    write_json,
)

DEFAULT_OUT = RESULTS / "agent_corpus.json"
SCHEMA = 1


def _pct(before: int, after: int) -> float:
    return round((1 - after / before) * 100, 2) if before else 0.0


def _measure(samples: list[Sample], outs: list[Output], tok: Tokenizer) -> list[dict]:
    rows = []
    for s, o in zip(samples, outs, strict=True):
        before, after = tok.count(s.text), tok.count(o.text)
        lost = missing_facts(s.facts, o.text)
        rows.append(
            {
                "tokens": after,
                "saved_pct": _pct(before, after),
                "grew": after > before,
                "facts_total": len(s.facts),
                "facts_kept": len(s.facts) - len(lost),
                "missing": lost,
                "exact_ok": (o.text == s.text) if s.byte_exact else None,
                "ms_p50": round(median_ms(o.seconds), 3),
                "_seconds": o.seconds,
            }
        )
    return rows


def _aggregate(rows: list[tuple[dict, dict]]) -> dict:
    """rows: (sample_row, tool_row) pairs."""
    before = sum(r["tokens"] for r, _ in rows)
    after = sum(t["tokens"] for _, t in rows)
    seconds = [x for _, t in rows for x in t["_seconds"]]
    return {
        "samples": len(rows),
        "before": before,
        "after": after,
        "saved_pct": _pct(before, after),
        "facts_total": sum(t["facts_total"] for _, t in rows),
        "facts_kept": sum(t["facts_kept"] for _, t in rows),
        "exact_violations": sum(1 for _, t in rows if t["exact_ok"] is False),
        "grew": sum(1 for _, t in rows if t["grew"]),
        "latency_ms": {
            "p50": round(percentile(seconds, 50) * 1000, 3),
            "p95": round(percentile(seconds, 95) * 1000, 3),
        },
    }


def summarise(sample_rows: list[dict], tool: str) -> dict:
    pairs = [(r, r[tool]) for r in sample_rows if tool in r]
    agent = [p for p in pairs if p[0]["group"] == "agent"]
    by_kind: dict[str, list] = defaultdict(list)
    for p in agent:
        by_kind[p[0]["kind"]].append(p)
    scen: dict[str, list] = defaultdict(list)
    for p in pairs:
        if p[0]["group"].startswith("headroom:"):
            scen[p[0]["group"].split(":", 1)[1]].append(p)
    hr_all = [p for ps in scen.values() for p in ps]
    out = {
        "agent": _aggregate(agent),
        "by_kind": {k: _aggregate(by_kind[k]) for k in KINDS if k in by_kind},
        "headroom_scenarios": {k: _aggregate(scen[k]) for k in HEADROOM_SCENARIOS if k in scen},
        "all": _aggregate(pairs),
    }
    if hr_all:
        out["headroom_scenarios"]["total"] = _aggregate(hr_all)
    out["cost"] = {
        m: cost.compare([r["tokens"] for r, _ in agent], [t["tokens"] for _, t in agent], model=m)
        for m in (cost.DEFAULT_MODEL, "claude-sonnet-5-5", "gpt-6.1-sol")
    }
    return out


def run(seed: int, repeats: int, headroom_python: str | None) -> dict:
    samples = build_corpus(seed)
    tok = Tokenizer()
    texts = [s.text for s in samples]

    tools: dict[str, dict] = {}
    measured: dict[str, list[dict]] = {}

    sensei = SenseiCompressor()
    from sensei.config import settings

    measured["sensei"] = _measure(samples, sensei.run(texts, repeats), tok)
    tools["sensei"] = {
        "version": sensei.version,
        "mode": "ContentRouter.compress(edit_target=True), as the gateway applies it to tool results",
        "settings": {
            "code_compression": settings.code_compression,
            "strip_invisible": settings.strip_invisible,
        },
    }

    if headroom_python:
        hr = HeadroomCompressor(headroom_python)
        measured["headroom"] = _measure(samples, hr.run(texts, repeats), tok)
        tools["headroom"] = {
            "version": hr.version,
            "mode": "headroom.compress() on an OpenAI-format tool message, CompressConfig(protect_recent=0)",
            "model": hr.model,
        }

    sample_rows = []
    for i, s in enumerate(samples):
        row = {
            "name": s.name,
            "kind": s.kind,
            "group": s.group,
            "tool": s.tool,
            "byte_exact": s.byte_exact,
            "tokens": tok.count(s.text),
        }
        for name, rows in measured.items():
            row[name] = rows[i]
        sample_rows.append(row)

    summary = {name: summarise(sample_rows, name) for name in measured}
    for row in sample_rows:
        for name in measured:
            row[name].pop("_seconds", None)

    return {
        "schema": SCHEMA,
        "generated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"),
        "tokenizer": tok.name,
        "corpus": {"seed": seed, "digest": corpus_digest(samples), "samples": len(samples)},
        "repeats": repeats,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "tools": tools,
        "headroom_published": HEADROOM_PUBLISHED,
        "samples": sample_rows,
        "summary": summary,
    }


def carry_over_headroom(data: dict, previous: dict | None) -> None:
    """Keep last run's Headroom numbers when the corpus is byte-identical.

    Headroom is pinned to one version, so its output is a function of the
    corpus alone; re-measuring it needs its venv, which nightly CI on main
    does not have to install to check Sensei.
    """
    if not previous or "headroom" in data["tools"]:
        return
    if previous.get("corpus", {}).get("digest") != data["corpus"]["digest"]:
        return
    if "headroom" not in previous.get("tools", {}):
        return
    by_name = {r["name"]: r for r in previous["samples"]}
    for row in data["samples"]:
        if "headroom" in by_name.get(row["name"], {}):
            row["headroom"] = by_name[row["name"]]["headroom"]
    data["tools"]["headroom"] = {
        **previous["tools"]["headroom"],
        "carried_over_from": previous.get("generated"),
    }
    data["summary"]["headroom"] = previous["summary"]["headroom"]


def check(data: dict, baseline: dict, max_drop: float) -> list[str]:
    """Regressions of Sensei against a committed run. Empty list: all good."""
    problems = []
    now, then = data["summary"]["sensei"], baseline["summary"]["sensei"]
    for scope in ("agent", "all"):
        drop = then[scope]["saved_pct"] - now[scope]["saved_pct"]
        if drop > max_drop:
            problems.append(
                f"{scope}: savings fell {drop:.2f} points ({then[scope]['saved_pct']}% → {now[scope]['saved_pct']}%)"
            )
    if now["all"]["exact_violations"] > then["all"]["exact_violations"]:
        problems.append(
            f"file reads no longer byte-exact: {now['all']['exact_violations']} violation(s)"
        )
    prev = {r["name"]: r["sensei"] for r in baseline["samples"]}
    for row in data["samples"]:
        old = prev.get(row["name"])
        if old is None:
            continue
        newly_lost = set(row["sensei"]["missing"]) - set(old["missing"])
        if newly_lost:
            problems.append(f"{row['name']}: lost {sorted(newly_lost)}")
    return problems


def print_table(data: dict) -> None:
    tools = list(data["summary"])
    print(
        f"Tokenizer {data['tokenizer']} · corpus seed {data['corpus']['seed']} · digest {data['corpus']['digest'][:12]}"
    )
    print(", ".join(f"{t} {data['tools'][t]['version']}" for t in tools))
    print()
    head = f"{'kind':<26}{'tokens':>9}" + "".join(f"{t:>12}" for t in tools)
    print(head)
    print("-" * len(head))
    for kind, label in KINDS.items():
        s0 = data["summary"][tools[0]]["by_kind"].get(kind)
        if not s0:
            continue
        cells = "".join(
            f"{data['summary'][t]['by_kind'][kind]['saved_pct']:>11.1f}%" for t in tools
        )
        print(f"{label:<26}{s0['before']:>9}{cells}")
    print("-" * len(head))
    a = data["summary"][tools[0]]["agent"]
    print(
        f"{'AGENT CORPUS':<26}{a['before']:>9}"
        + "".join(f"{data['summary'][t]['agent']['saved_pct']:>11.1f}%" for t in tools)
    )
    print()
    for scen, label in [*HEADROOM_SCENARIOS.items(), ("total", "Headroom scenarios total")]:
        s0 = data["summary"][tools[0]]["headroom_scenarios"].get(scen)
        if not s0:
            continue
        cells = "".join(
            f"{data['summary'][t]['headroom_scenarios'][scen]['saved_pct']:>11.1f}%" for t in tools
        )
        print(
            f"{label:<26}{s0['before']:>9}{cells}   (Headroom publishes {HEADROOM_PUBLISHED[scen]}%)"
        )
    print()
    for t in tools:
        s = data["summary"][t]
        a = s["all"]
        c = s["cost"][cost.DEFAULT_MODEL]["cached"]
        print(
            f"{t:<10} facts {a['facts_kept']}/{a['facts_total']} · byte-exact violations {a['exact_violations']}"
            f" · outputs that grew {a['grew']} · latency p50 {a['latency_ms']['p50']:.2f} ms p95 {a['latency_ms']['p95']:.2f} ms"
            f" · session bill ({cost.DEFAULT_MODEL}, cached) -{c['saved_pct']:.1f}%"
        )
        lost = [(r["name"], r[t]["missing"]) for r in data["samples"] if t in r and r[t]["missing"]]
        for name, miss in lost:
            print(f"    lost in {name}: {miss}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--repeats", type=int, default=5, help="timed calls per sample (default 5)")
    parser.add_argument(
        "--headroom",
        nargs="?",
        const="auto",
        metavar="PYTHON",
        help="also run Headroom; PYTHON is its venv interpreter (default: $HEADROOM_PYTHON or the benchmarks.headroom_env venv)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"write results here (default with --write: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"write {DEFAULT_OUT.relative_to(RESULTS.parent.parent)}",
    )
    parser.add_argument(
        "--check",
        type=Path,
        metavar="BASELINE",
        help="fail on regressions against this results file",
    )
    parser.add_argument("--max-drop", type=float, default=1.0, metavar="POINTS")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    hp = None
    if args.headroom:
        hp = default_headroom_python() if args.headroom == "auto" else args.headroom
        if not hp:
            print(
                "Headroom venv not found; run `python -m benchmarks.headroom_env` first",
                file=sys.stderr,
            )
            return 2

    data = run(args.seed, args.repeats, hp)
    out = args.out or (DEFAULT_OUT if args.write else None)
    carry_over_headroom(data, read_json(out or DEFAULT_OUT))
    print_table(data)

    if out:
        write_json(out, data)
        print(f"\nwrote {out}")

    if args.check:
        baseline = read_json(args.check)
        if baseline is None:
            print(f"no baseline at {args.check}", file=sys.stderr)
            return 2
        problems = check(data, baseline, args.max_drop)
        if problems:
            print("\nREGRESSION against", args.check, file=sys.stderr)
            for p in problems:
                print("  -", p, file=sys.stderr)
            return 1
        print(f"\nno regression against {args.check} (max drop {args.max_drop} points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
