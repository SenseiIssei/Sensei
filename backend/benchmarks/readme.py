"""The README's benchmark table, rendered from the results files.

Everything between ``<!-- bench:start -->`` and ``<!-- bench:end -->`` in
README.md is generated here from ``results/agent_corpus.json`` and, when it
exists, ``results/session_replay.json``. The prose around it carries no
numbers, so a re-run can never leave a stale figure behind.
"""

from __future__ import annotations

import re
from pathlib import Path

from benchmarks.corpus import KINDS

START = "<!-- bench:start -->"
END = "<!-- bench:end -->"
README = Path(__file__).resolve().parents[2] / "README.md"


def _pct(v: float) -> str:
    return f"{v:.1f}%"


def _ver(tools: dict, name: str) -> str:
    return tools[name]["version"].split("+")[0]


def render(agent: dict, sessions: dict | None) -> str:
    names = [n for n in ("sensei", "headroom") if n in agent["summary"]]
    title = {"sensei": "Sensei", "headroom": "Headroom"}
    head = (
        "| Measured on | What it is | "
        + " | ".join(f"{title[n]} {_ver(agent['tools'], n)}" for n in names)
        + " |"
    )
    rule = "|---|---|" + "--:|" * len(names)
    rows = [head, rule]

    if sessions:
        tot = sessions["total"]
        by = sessions["sessions_by_agent"]
        who = " + ".join(
            f"{v} {'Claude Code' if k == 'claude-code' else 'Codex'}" for k, v in sorted(by.items())
        )
        cells = []
        for n in names:
            if n in tot:
                cells.append(
                    f"**{_pct(tot[n]['saved_pct'])}** of tokens · **{tot[n]['bill_saved_pct']:.2f}%** of the bill"
                )
            else:
                cells.append("—")
        rows.append(
            f"| **Real sessions** | {who} sessions, {tot['results']:,} tool results, replayed locally "
            f"([how](docs/benchmarks.md#your-own-sessions)) | " + " | ".join(cells) + " |"
        )

    s = agent["summary"]
    agent_n = s["sensei"]["agent"]["samples"]
    rows.append(
        f"| Agent corpus | {agent_n} seeded tool outputs: git, grep, tests, builds, listings, JSON, MCP, file reads | "
        + " | ".join(_pct(s[n]["agent"]["saved_pct"]) for n in names)
        + " |"
    )
    pub = agent.get("headroom_published", {}).get("total")
    rows.append(
        f"| Headroom's scenarios | Its four published scenarios, rebuilt{f' (it publishes {pub}%)' if pub else ''} | "
        + " | ".join(_pct(s[n]["headroom_scenarios"]["total"]["saved_pct"]) for n in names)
        + " |"
    )
    cost_model = next(iter(s["sensei"]["cost"]))
    rows.append(
        f"| Agent corpus, in dollars | One session, cached, priced as `{cost_model}` ([model](docs/benchmarks.md#cost-model)) | "
        + " | ".join(_pct(s[n]["cost"][cost_model]["cached"]["saved_pct"]) for n in names)
        + " |"
    )
    rows.append(
        "| Facts kept | Corpus: every fact an agent needs must still be there | "
        + " | ".join(f"{s[n]['all']['facts_kept']} / {s[n]['all']['facts_total']}" for n in names)
        + " |"
    )
    exact_total = sum(1 for r in agent["samples"] if r["byte_exact"])
    rows.append(
        "| File reads unchanged | Corpus: Read / `cat` output is edited next by exact match | "
        + " | ".join(
            f"{exact_total - s[n]['all']['exact_violations']} / {exact_total}" for n in names
        )
        + " |"
    )
    rows.append(
        "| Latency p50 · p95 | Corpus: the compress call alone, per tool output | "
        + " | ".join(
            f"{s[n]['all']['latency_ms']['p50']:.1f} · {s[n]['all']['latency_ms']['p95']:.0f} ms"
            for n in names
        )
        + " |"
    )
    if sessions and "latency" in sessions:
        tot = sessions["total"]
        cells = []
        for n in names:
            lat = sessions["latency"].get(n)
            if not lat or n not in tot:
                cells.append("—")
                continue
            cell = f"{lat['p95_ms']:.0f} · {lat['p99_ms']:.0f} ms"
            slow, cut = tot[n].get("slow_over_1s", 0), tot[n].get("timeouts", 0)
            if slow or cut:
                limit = sessions.get("timeout_s", {}).get(n) or 30
                cell += f" · {slow} over 1 s, {cut} cut off at {limit:g} s"
            cells.append(cell)
        rows.append(
            "| Latency p95 · p99 | Real sessions: per distinct tool result, and the slow tail | "
            + " | ".join(cells)
            + " |"
        )

    sub = (
        f"<sub>{agent['tokenizer']} on the text the model receives, identical input for both tools · "
        f"corpus seed {agent['corpus']['seed']} (sha256 `{agent['corpus']['digest'][:12]}`) · measured {agent['generated']}"
    )
    if sessions:
        sub += f" · bill = recorded usage priced as `{sessions['pricing']}`, net of prompt caching"
    sub += " · regenerate with `cd backend && python -m benchmarks.refresh`</sub>"

    kinds = [
        "| Tool output | Tokens | " + " | ".join(title[n] for n in names) + " |",
        "|---|--:|" + "--:|" * len(names),
    ]
    for kind, label in KINDS.items():
        k0 = s["sensei"]["by_kind"].get(kind)
        if not k0:
            continue
        kinds.append(
            f"| {label} | {k0['before']:,} | "
            + " | ".join(_pct(s[n]["by_kind"][kind]["saved_pct"]) for n in names)
            + " |"
        )
    detail = ["", "<details>", "<summary><b>Per kind of tool output</b></summary>", "", *kinds]
    if sessions:
        cats = [
            "| Tool / command family | Results | Tokens | "
            + " | ".join(title[n] for n in names)
            + " |",
            "|---|--:|--:|" + "--:|" * len(names),
        ]
        for cat, b in list(sessions["by_category"].items())[:16]:
            cats.append(
                f"| `{cat}` | {b['results']:,} | {b['tokens']:,} | "
                + " | ".join(_pct(b[n]["saved_pct"]) if n in b else "—" for n in names)
                + " |"
            )
        detail += ["", "**Your real sessions, by tool:**", "", *cats]
    detail += ["", "</details>"]

    note = "<!-- Generated by `python -m benchmarks.refresh` from backend/benchmarks/results/*.json. Do not edit by hand. -->"
    return "\n".join([START, note, "", *rows, "", sub, *detail, END])


def update(text: str, block: str) -> str:
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        raise ValueError(f"README has no {START} … {END} block")
    return pattern.sub(lambda _: block, text, count=1)
