"""Draw the README's graphics: animated SVGs in a dark and a light variant.

    python docs/assets/generate.py

GitHub renders an SVG referenced with <img> including its own CSS animations,
and a <picture> element can pick the variant that matches the reader's theme.
Every animation respects prefers-reduced-motion, and every file is static
text — no scripts, no external fonts, nothing fetched.

Every number drawn here is read from `backend/benchmarks/results/*.json`;
nothing is typed in by hand. `python -m benchmarks.refresh` (from `backend/`)
re-measures and redraws; `python docs/assets/generate.py --bench` only redraws
the benchmark graphics (no Pillow needed).
"""

from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent.parent / "backend"))

from benchmarks.corpus import HEADROOM_PUBLISHED, HEADROOM_SCENARIOS, KINDS

THEMES = {
    "dark": {
        "canvas": "#131619",
        "deep": "#0d0f10",
        "surface": "#1a1d21",
        "raised": "#22262b",
        "line": "#2b2d30",
        "strong": "#363a3d",
        "fg": "#e8e8e8",
        "muted": "#9b9c9e",
        "faint": "#686b6e",
        "accent": "#a6b0f2",
        "bar": "#7989ec",
        "rival": "#5cc8b0",
        "gold": "#ffd47d",
        "gold_text": "#ffd47d",
        "success": "#4ac97e",
        "glow": "0.10",
    },
    "light": {
        "canvas": "#f6f7f9",
        "deep": "#eff1f5",
        "surface": "#ffffff",
        "raised": "#f1f3f7",
        "line": "#e0e2ea",
        "strong": "#cdd1db",
        "fg": "#161a25",
        "muted": "#5f6478",
        "faint": "#8a8fa0",
        "accent": "#4357dc",
        "bar": "#4d62e5",
        "rival": "#1f8f78",
        "gold": "#ffd47d",
        "gold_text": "#8a5a0c",
        "success": "#17794b",
        "glow": "0.07",
    },
}

FONT = (
    "Inter, 'Segoe UI', -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif"
)
MONO = "'JetBrains Mono', 'Cascadia Mono', ui-monospace, Menlo, Consolas, monospace"

REDUCED = """
  @media (prefers-reduced-motion: reduce) {
    * { animation: none !important; }
  }"""


def hero(t: dict[str, str], before: int, after: int) -> str:
    """Logo whose lines compress, the name, and what it does."""
    b, a = f"{before:,}", f"{after:,} tokens"
    # 20px bold monospace: 12px a character.
    strike_end = 16 + 12 * len(b)
    arrow_x = 18 + 12 * len(b) + 14
    after_x = arrow_x + 32
    chip_w = after_x + 12 * len(a) + 18
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="340" viewBox="0 0 1200 340" role="img" aria-labelledby="t d">
<title id="t">Sensei</title>
<desc id="d">Your AI coding tools, minus the padding.</desc>
<defs>
  <radialGradient id="glowA" cx="18%" cy="20%" r="60%">
    <stop offset="0" stop-color="{t["accent"]}" stop-opacity="{t["glow"]}"/>
    <stop offset="1" stop-color="{t["accent"]}" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="glowB" cx="88%" cy="95%" r="45%">
    <stop offset="0" stop-color="{t["gold"]}" stop-opacity="{float(t["glow"]) * 0.6:.3f}"/>
    <stop offset="1" stop-color="{t["gold"]}" stop-opacity="0"/>
  </radialGradient>
</defs>
<style>
  .l {{ stroke: {t["accent"]}; stroke-width: 15; stroke-linecap: round; }}
  .l1 {{ animation: l1 6s cubic-bezier(.4,0,.2,1) infinite; }}
  .l2 {{ animation: l2 6s cubic-bezier(.4,0,.2,1) infinite; }}
  .l3 {{ animation: l3 6s cubic-bezier(.4,0,.2,1) infinite; }}
  .dot {{ fill: {t["gold"]}; transform-box: fill-box; transform-origin: center; animation: dot 6s ease-in-out infinite; }}
  @keyframes l1 {{ 0%,12% {{ d: path("M43 61H137"); }} 30%,88% {{ d: path("M43 61H137"); }} 100% {{ d: path("M43 61H137"); }} }}
  @keyframes l2 {{ 0%,12% {{ d: path("M43 92H137"); }} 30%,88% {{ d: path("M58 92H122"); }} 100% {{ d: path("M43 92H137"); }} }}
  @keyframes l3 {{ 0%,12% {{ d: path("M43 122H137"); }} 30%,88% {{ d: path("M72 122H108"); }} 100% {{ d: path("M43 122H137"); }} }}
  @keyframes dot {{ 0%,26% {{ transform: scale(0); opacity: 0; }} 34% {{ transform: scale(1.25); opacity: 1; }} 40%,86% {{ transform: scale(1); opacity: 1; }} 96%,100% {{ transform: scale(0); opacity: 0; }} }}
  .name {{ font: 700 64px {FONT}; fill: {t["fg"]}; letter-spacing: -1.5px; }}
  .tag {{ font: 400 24px {FONT}; fill: {t["muted"]}; }}
  .chip {{ font: 600 14px {FONT}; fill: {t["muted"]}; }}
  .num {{ font: 700 20px {MONO}; }}
  .before {{ fill: {t["faint"]}; animation: fadeOut 6s ease infinite; }}
  .after {{ fill: {t["gold_text"]}; animation: fadeIn 6s ease infinite; }}
  .strike {{ stroke: {t["faint"]}; stroke-width: 2; animation: strike 6s ease infinite; transform-box: fill-box; transform-origin: left; }}
  @keyframes strike {{ 0%,20% {{ transform: scaleX(0); }} 30%,88% {{ transform: scaleX(1); }} 96%,100% {{ transform: scaleX(0); }} }}
  @keyframes fadeIn {{ 0%,26% {{ opacity: 0; }} 36%,86% {{ opacity: 1; }} 96%,100% {{ opacity: 0; }} }}
  @keyframes fadeOut {{ 0%,24% {{ opacity: 1; }} 32%,88% {{ opacity: .55; }} 100% {{ opacity: 1; }} }}{REDUCED}
</style>
<rect width="1200" height="340" rx="24" fill="{t["canvas"]}"/>
<rect width="1200" height="340" rx="24" fill="url(#glowA)"/>
<rect width="1200" height="340" rx="24" fill="url(#glowB)"/>
<rect x="0.5" y="0.5" width="1199" height="339" rx="23.5" fill="none" stroke="{t["line"]}"/>

<g transform="translate(80 80)">
  <rect width="180" height="180" rx="40" fill="{t["deep"]}" stroke="{t["strong"]}" stroke-width="2"/>
  <g transform="translate(0 0)">
    <path class="l l1" d="M43 61H137"/>
    <path class="l l2" d="M58 92H122"/>
    <path class="l l3" d="M72 122H108"/>
    <circle class="dot" cx="130" cy="122" r="10"/>
  </g>
</g>

<text x="320" y="150" class="name">Sensei</text>
<text x="322" y="194" class="tag">Your AI coding tools, minus the padding.</text>

<g transform="translate(322 222)">
  <rect width="{chip_w}" height="44" rx="10" fill="{t["surface"]}" stroke="{t["line"]}"/>
  <text x="18" y="29" class="num before">{b}</text>
  <line x1="16" y1="23" x2="{strike_end}" y2="23" class="strike"/>
  <text x="{arrow_x}" y="29" class="num" fill="{t["faint"]}">→</text>
  <text x="{after_x}" y="29" class="num after">{a}</text>
</g>

<g transform="translate(700 222)">
  <rect width="420" height="44" rx="10" fill="none" stroke="{t["line"]}"/>
  <circle cx="22" cy="22" r="4" fill="{t["success"]}"/>
  <text x="36" y="27" class="chip">Windows · macOS · Linux   ·   MIT   ·   zero telemetry</text>
</g>
</svg>
"""


def flow(t: dict[str, str], before: int, after: int) -> str:
    """Long chunks go in, short chunks go out, the answer comes back."""
    lefts = "".join(
        f'<rect class="pkt in" style="animation-delay:{i * 0.55:.2f}s" x="{-w}" y="{y}" width="{w}" height="10" rx="5"/>'
        for i, (y, w) in enumerate([(0, 120), (18, 96), (36, 132), (54, 84), (72, 110)])
    )
    rights = "".join(
        f'<rect class="pkt out" style="animation-delay:{i * 0.55 + 0.35:.2f}s" x="{-w}" y="{y}" width="{w}" height="10" rx="5"/>'
        for i, (y, w) in enumerate([(0, 34), (18, 26), (36, 40), (54, 22), (72, 30)])
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="320" viewBox="0 0 1200 320" role="img" aria-labelledby="t d">
<title id="t">How Sensei sits between your tool and the model</title>
<desc id="d">On the benchmark corpus your AI tool sends {before:,} tokens of tool output to Sensei on your machine; Sensei sends {after:,} to the model; the answer comes back unchanged.</desc>
<style>
  .card {{ fill: {t["surface"]}; stroke: {t["line"]}; }}
  .mid {{ fill: {t["deep"]}; stroke: {t["accent"]}; stroke-width: 1.5; }}
  .h {{ font: 600 19px {FONT}; fill: {t["fg"]}; }}
  .s {{ font: 400 14px {FONT}; fill: {t["muted"]}; }}
  .n {{ font: 700 15px {MONO}; }}
  .pkt {{ fill: {t["bar"]}; }}
  .in {{ animation: goIn 2.75s linear infinite; }}
  .out {{ animation: goOut 2.75s linear infinite; fill: {t["gold"]}; }}
  .back {{ stroke: {t["faint"]}; stroke-width: 2; stroke-dasharray: 6 8; fill: none; animation: dash 1.4s linear infinite; }}
  .pulse {{ animation: pulse 2.75s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }}
  @keyframes goIn {{ 0% {{ transform: translateX(0); opacity: 1; }} 100% {{ transform: translateX(330px); opacity: 1; }} }}
  @keyframes goOut {{ 0% {{ transform: translateX(0); opacity: 1; }} 100% {{ transform: translateX(240px); opacity: 1; }} }}
  @keyframes dash {{ to {{ stroke-dashoffset: 28; }} }}
  @keyframes pulse {{ 0%,100% {{ opacity: .55; }} 50% {{ opacity: 1; }} }}{REDUCED}
</style>
<rect width="1200" height="320" rx="20" fill="{t["canvas"]}"/>
<rect x="0.5" y="0.5" width="1199" height="319" rx="19.5" fill="none" stroke="{t["line"]}"/>

<rect class="card" x="40" y="70" width="250" height="140" rx="14"/>
<text x="64" y="112" class="h">Your AI tool</text>
<text x="64" y="138" class="s">Claude Code · Codex · Cursor</text>
<text x="64" y="160" class="s">Aider · Cline · Zed · …</text>
<text x="64" y="192" class="n" fill="{t["faint"]}">{before:,} tokens</text>

<rect class="mid" x="475" y="50" width="250" height="180" rx="16"/>
<g transform="translate(503 82) scale(0.36)">
  <rect width="100" height="100" rx="22" fill="{t["canvas"]}" stroke="{t["strong"]}" stroke-width="3"/>
  <path d="M24 34h52M32 51h36M40 68h20" stroke="{t["accent"]}" stroke-width="8.5" stroke-linecap="round"/>
  <circle cx="72" cy="68" r="5.5" fill="{t["gold"]}"/>
</g>
<text x="555" y="104" class="h">Sensei</text>
<text x="503" y="146" class="s">compresses JSON, logs,</text>
<text x="503" y="168" class="s">code and disassembly</text>
<text x="503" y="204" class="s pulse" fill="{t["success"]}">● on your machine</text>

<rect class="card" x="910" y="70" width="250" height="140" rx="14"/>
<text x="934" y="112" class="h">The model</text>
<text x="934" y="138" class="s">Anthropic · OpenAI · Gemini</text>
<text x="934" y="160" class="s">or local: Ollama, llama.cpp</text>
<text x="934" y="192" class="n" fill="{t["gold_text"]}">{after:,} tokens</text>

<defs>
  <clipPath id="laneL"><rect x="0" y="-4" width="185" height="96"/></clipPath>
  <clipPath id="laneR"><rect x="0" y="-4" width="185" height="96"/></clipPath>
</defs>
<g transform="translate(290 100)"><g clip-path="url(#laneL)">{lefts}</g></g>
<g transform="translate(725 100)"><g clip-path="url(#laneR)">{rights}</g></g>

<path class="back" d="M1035 222 C 1035 290, 165 290, 165 222"/>
<text x="600" y="296" text-anchor="middle" class="s">the answer comes back unchanged</text>
</svg>
"""


RESULTS = OUT.parent.parent / "backend" / "benchmarks" / "results"


def load_results() -> dict:
    """The committed benchmark results; every number drawn below comes from here.

    ``agent_corpus.json`` is written by ``python -m benchmarks.agent_bench``;
    ``session_replay.json`` (optional, numbers only) by
    ``python -m benchmarks.session_replay --summary-json``. Regenerate both and
    these graphics with ``python -m benchmarks.refresh`` from ``backend/``.
    """
    agent = json.loads((RESULTS / "agent_corpus.json").read_text(encoding="utf-8"))
    path = RESULTS / "session_replay.json"
    sessions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    path = RESULTS / "gateway_replay.json"
    gateway = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    return {"agent": agent, "sessions": sessions, "gateway": gateway}


def headline_tokens(data: dict) -> tuple[int, int]:
    """Before/after for the hero and flow graphics: the whole agent corpus."""
    s = data["agent"]["summary"]["sensei"]["agent"]
    return s["before"], s["after"]


def _fmt_pct(v: float) -> str:
    return f"{v:.1f}%" if abs(v) < 10 else f"{v:.0f}%"


def _bars(
    t: dict[str, str],
    rows: list[tuple[str, dict[str, float]]],
    tools: list[str],
    top: int,
    x0: int,
    width: int,
) -> tuple[str, int]:
    """Grouped horizontal bars, one per tool, growing to their value."""
    colours = {"sensei": t["bar"], "headroom": t["rival"]}
    out = []
    y = top
    for i, (label, vals) in enumerate(rows):
        out.append(
            f'<text x="{x0 - 18}" y="{y + 9 + 7 * (len(tools) - 1)}" text-anchor="end" class="lbl">{escape(label)}</text>'
        )
        for j, tool in enumerate(tools):
            v = vals.get(tool)
            yy = y + j * 14
            out.append(
                f'<rect x="{x0}" y="{yy}" width="{width}" height="10" rx="4" fill="{t["raised"]}"/>'
            )
            if v is None:
                continue
            w = max(0.0, min(100.0, v)) * width / 100
            delay = 0.1 + i * 0.05 + j * 0.03
            if w > 0:
                out.append(
                    f'<rect class="bar" style="animation-delay:{delay:.2f}s" x="{x0}" y="{yy}" width="{w:.1f}" height="10" rx="4" fill="{colours[tool]}"/>'
                )
            out.append(
                f'<text class="pct" style="animation-delay:{delay + 0.5:.2f}s" x="{x0 + w + 8:.1f}" y="{yy + 9}">{_fmt_pct(v)}</text>'
            )
        y += 14 * len(tools) + 12
    return "".join(out), y


def _legend(
    t: dict[str, str], tools: list[str], versions: dict[str, str], x: int, y: int
) -> str:
    colours = {"sensei": t["bar"], "headroom": t["rival"]}
    names = {"sensei": "Sensei", "headroom": "Headroom"}
    out = []
    for tool in tools:
        v = versions.get(tool, "").split("+")[0]
        label = f"{names[tool]} {v}".strip()
        out.append(
            f'<rect x="{x}" y="{y - 10}" width="12" height="12" rx="3" fill="{colours[tool]}"/>'
        )
        out.append(f'<text x="{x + 20}" y="{y}" class="s">{escape(label)}</text>')
        x += 40 + len(label) * 8
    return "".join(out)


_BAR_STYLE = """
  .h {{ font: 600 20px {font}; fill: {fg}; }}
  .s {{ font: 400 14px {font}; fill: {muted}; }}
  .lbl {{ font: 500 14px {font}; fill: {fg}; }}
  .pct {{ font: 700 12px {mono}; fill: {fg}; opacity: 0; animation: show .4s ease forwards; }}
  .bar {{ transform-box: fill-box; transform-origin: left; transform: scaleX(0); animation: grow 1.1s cubic-bezier(.4,0,.2,1) forwards; }}
  .big {{ font: 700 72px {font}; fill: {gold}; letter-spacing: -2px; }}
  .mid {{ font: 700 26px {font}; fill: {fg}; }}
  @keyframes grow {{ to {{ transform: scaleX(1); }} }}
  @keyframes show {{ to {{ opacity: 1; }} }}
  @media (prefers-reduced-motion: reduce) {{
    .bar {{ animation: none; transform: none; }}
    .pct {{ animation: none; opacity: 1; }}
  }}"""


def _style(t: dict[str, str]) -> str:
    return _BAR_STYLE.format(
        font=FONT, mono=MONO, fg=t["fg"], muted=t["muted"], gold=t["gold_text"]
    )


def benchmark_svg(t: dict[str, str], data: dict, kinds: dict[str, str]) -> str:
    agent = data["agent"]
    tools = [x for x in ("sensei", "headroom") if x in agent["summary"]]
    versions = {k: v["version"] for k, v in agent["tools"].items()}
    rows = []
    for kind, label in kinds.items():
        vals = {
            tool: agent["summary"][tool]["by_kind"][kind]["saved_pct"]
            for tool in tools
            if kind in agent["summary"][tool]["by_kind"]
        }
        if vals:
            rows.append((label, vals))
    x0, width, top = 250, 470, 132
    bars, bottom = _bars(t, rows, tools, top, x0, width)
    height = bottom + 52

    # Right panel: the number that matters — real sessions — if there is one.
    px = 860
    right = []
    sessions = data.get("sessions")
    s_agent = agent["summary"]["sensei"]
    if sessions:
        tot = sessions["total"]
        n = sum(sessions["sessions_by_agent"].values())
        right += [
            f'<text x="{px}" y="150" class="s">Your real sessions</text>',
            f'<text x="{px}" y="168" class="s">{n} sessions · {tot["results"]:,} tool results</text>',
            f'<text x="{px - 4}" y="240" class="big">{_fmt_pct(tot["sensei"]["saved_pct"])}</text>',
            f'<text x="{px}" y="266" class="s">of tool-output tokens removed</text>',
            f'<text x="{px}" y="288" class="s">{tot["sensei"]["bill_saved_pct"]:.2f}% of the bill, net of caching</text>',
        ]
        if "headroom" in tot:
            right.append(
                f'<text x="{px}" y="318" class="s">Headroom on the same data: {_fmt_pct(tot["headroom"]["saved_pct"])} · {tot["headroom"]["bill_saved_pct"]:.2f}%</text>'
            )
        y2 = 380
        gw = (data.get("gateway") or {}).get("arms", {}).get("sensei")
        if gw and gw.get("cost_vs_raw") is not None:
            right.append(
                f'<text x="{px}" y="340" class="s">Gateway end to end, net of caching: input bill −{gw["cost_vs_raw"] * 100:.2f}%</text>'
            )
            y2 = 400
    else:
        y2 = 160
    right += [
        f'<text x="{px}" y="{y2}" class="s">Seeded agent corpus</text>',
        f'<text x="{px}" y="{y2 + 34}" class="mid">{_fmt_pct(s_agent["agent"]["saved_pct"])}'
        + (
            f' <tspan class="s">vs Headroom {_fmt_pct(agent["summary"]["headroom"]["agent"]["saved_pct"])}</tspan>'
            if "headroom" in tools
            else ""
        )
        + "</text>",
        f'<text x="{px}" y="{y2 + 60}" class="s">facts kept {s_agent["all"]["facts_kept"]}/{s_agent["all"]["facts_total"]} · file reads changed {s_agent["all"]["exact_violations"]}</text>',
        f'<text x="{px}" y="{y2 + 82}" class="s">latency p50 {s_agent["all"]["latency_ms"]["p50"]:.1f} ms · p95 {s_agent["all"]["latency_ms"]["p95"]:.0f} ms</text>',
    ]
    scen = s_agent["headroom_scenarios"].get("total")
    if scen:
        y3 = y2 + 130
        right += [
            f'<text x="{px}" y="{y3}" class="s">Headroom\'s four scenarios</text>',
            f'<text x="{px}" y="{y3 + 34}" class="mid">{_fmt_pct(scen["saved_pct"])}'
            + (
                f' <tspan class="s">vs Headroom {_fmt_pct(agent["summary"]["headroom"]["headroom_scenarios"]["total"]["saved_pct"])}</tspan>'
                if "headroom" in tools
                else ""
            )
            + "</text>",
            f'<text x="{px}" y="{y3 + 60}" class="s">code search · SRE incident · exploration · triage</text>',
        ]
    desc = "; ".join(
        f"{label}: " + ", ".join(f"{k} {v:.1f}%" for k, v in vals.items())
        for label, vals in rows
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-labelledby="t d">
<title id="t">Tokens removed from coding-agent tool output, by kind</title>
<desc id="d">{escape(desc)}</desc>
<style>{_style(t)}</style>
<rect width="1200" height="{height}" rx="20" fill="{t["canvas"]}"/>
<rect x="0.5" y="0.5" width="1199" height="{height - 1}" rx="19.5" fill="none" stroke="{t["line"]}"/>
<text x="40" y="56" class="h">Tokens removed, by kind of tool output</text>
<text x="40" y="80" class="s">Seeded corpus (seed {agent["corpus"]["seed"]}) · {agent["tokenizer"]} on what the model receives · same input for both tools</text>
{_legend(t, tools, versions, 40, 112)}
{bars}
<line x1="{px - 40}" y1="132" x2="{px - 40}" y2="{bottom - 12}" stroke="{t["line"]}"/>
{"".join(right)}
<text x="40" y="{height - 22}" class="s">Reproduce: cd backend &amp;&amp; python -m benchmarks.refresh · measured {agent["generated"]}</text>
</svg>
"""


def headtohead_svg(
    t: dict[str, str], data: dict, scenarios: dict[str, str], published: dict[str, int]
) -> str:
    """Headroom's own four scenarios, rebuilt, with both tools run on them."""
    agent = data["agent"]
    tools = [x for x in ("sensei", "headroom") if x in agent["summary"]]
    versions = {k: v["version"] for k, v in agent["tools"].items()}
    rows = []
    for key, label in [*scenarios.items(), ("total", "All four")]:
        vals = {
            tool: agent["summary"][tool]["headroom_scenarios"][key]["saved_pct"]
            for tool in tools
            if key in agent["summary"][tool]["headroom_scenarios"]
        }
        rows.append((label, vals))
    x0, width, top = 250, 600, 132
    bars, bottom = _bars(t, rows, tools, top, x0, width)
    # Headroom's published figure as a tick on each row.
    ticks = []
    y = top
    for key in [*scenarios, "total"]:
        if key in published:
            x = x0 + width * published[key] / 100
            ticks.append(
                f'<line x1="{x:.1f}" y1="{y - 4}" x2="{x:.1f}" y2="{y + 14 * len(tools)}" stroke="{t["muted"]}" stroke-width="2" stroke-dasharray="3 3"/>'
            )
        y += 14 * len(tools) + 12
    height = bottom + 52
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-labelledby="t d">
<title id="t">Sensei and Headroom on Headroom's benchmark scenarios</title>
<desc id="d">{escape("; ".join(f"{label}: " + ", ".join(f"{k} {v:.1f}%" for k, v in vals.items()) for label, vals in rows))}. Dashed lines mark the figures Headroom publishes.</desc>
<style>{_style(t)}</style>
<rect width="1200" height="{height}" rx="20" fill="{t["canvas"]}"/>
<rect x="0.5" y="0.5" width="1199" height="{height - 1}" rx="19.5" fill="none" stroke="{t["line"]}"/>
<text x="40" y="56" class="h">Head to head on Headroom's own scenarios</text>
<text x="40" y="80" class="s">Rebuilt from Headroom's published proof table · both tools on identical input · dashed: the figure Headroom publishes</text>
{_legend(t, tools, versions, 40, 112)}
{bars}
{"".join(ticks)}
<text x="40" y="{height - 22}" class="s">Reproduce: cd backend &amp;&amp; python -m benchmarks.agent_bench --headroom · measured {agent["generated"]}</text>
</svg>
"""


def main(bench_only: bool = False) -> None:
    data = load_results()
    before, after = headline_tokens(data)
    for name, theme in THEMES.items():
        if not bench_only:
            (OUT / f"hero-{name}.svg").write_text(
                hero(theme, before, after), encoding="utf-8"
            )
            (OUT / f"flow-{name}.svg").write_text(
                flow(theme, before, after), encoding="utf-8"
            )
        (OUT / f"benchmark-{name}.svg").write_text(
            benchmark_svg(theme, data, KINDS), encoding="utf-8"
        )
        (OUT / f"headtohead-{name}.svg").write_text(
            headtohead_svg(theme, data, HEADROOM_SCENARIOS, HEADROOM_PUBLISHED),
            encoding="utf-8",
        )
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))


def tour(width: int = 1000) -> None:
    """A slow cross-fading tour of the real screenshots, as an animated GIF."""
    from PIL import Image

    shots = OUT.parent / "screenshots"
    names = [
        "overview-dark",
        "overview-light",
        "connections-dark",
        "settings-light",
        "chat-light",
    ]
    slides = []
    for name in names:
        img = Image.open(shots / f"{name}.png").convert("RGB")
        img = img.resize(
            (width, round(img.height * width / img.width)), Image.Resampling.LANCZOS
        )
        slides.append(img)

    frames: list[Image.Image] = []
    durations: list[int] = []
    for i, slide in enumerate(slides):
        frames.append(slide)
        durations.append(2600)
        nxt = slides[(i + 1) % len(slides)]
        for step in range(1, 7):
            frames.append(Image.blend(slide, nxt, step / 7))
            durations.append(60)

    # One palette for every frame, built from all slides plus generous swatches
    # of the accent colours: per-frame median cut drops small areas, and the
    # gold of the headline number is exactly such an area.
    accents = [
        "#ffd47d",
        "#8a5a0c",
        "#a6b0f2",
        "#4357dc",
        "#7989ec",
        "#4d62e5",
        "#4ac97e",
        "#17794b",
        "#f3b45a",
        "#8a5a0c",
        "#f26d6a",
        "#b83636",
    ]
    sheet = Image.new(
        "RGB", (width, slides[0].height * len(slides) + 120 * len(accents))
    )
    for i, slide in enumerate(slides):
        sheet.paste(slide, (0, i * slide.height))
    for i, colour in enumerate(accents):
        top = slides[0].height * len(slides) + 120 * i
        sheet.paste(Image.new("RGB", (width, 120), colour), (0, top))
    palette = sheet.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    palette_frames = [
        f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames
    ]
    palette_frames[0].save(
        OUT / "tour.gif",
        save_all=True,
        append_images=palette_frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )
    print("wrote tour.gif", round((OUT / "tour.gif").stat().st_size / 1024), "kB")


# Feature icons: paths from Lucide (https://lucide.dev, ISC licence), drawn in
# the mid-tone accent that reads on both GitHub themes.
ICONS = {
    "compress": '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    "tools": '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
    "private": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    "mcp": '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/><path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12"/><path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"/>',
    "numbers": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "platforms": '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>',
}


def icons() -> None:
    folder = OUT / "icons"
    folder.mkdir(exist_ok=True)
    for name, body in ICONS.items():
        (folder / f"{name}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="-4 -4 32 32" '
            'fill="none" stroke="#7989ec" stroke-width="1.75" stroke-linecap="round" '
            'stroke-linejoin="round"><rect x="-4" y="-4" width="32" height="32" rx="8" '
            f'fill="#7989ec" fill-opacity="0.12" stroke="none"/>{body}</svg>\n',
            encoding="utf-8",
        )


if __name__ == "__main__":
    if "--bench" in sys.argv:
        main(bench_only=True)
    else:
        main()
        icons()
        tour()
