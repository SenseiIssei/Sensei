"""Re-measure everything and redraw every published number. One command.

    cd backend
    python -m benchmarks.refresh                 # corpus (+ Headroom if its venv exists), graphics, README
    python -m benchmarks.refresh --sessions      # also replay your own sessions (numbers only)
    python -m benchmarks.refresh --render-only   # redraw from the committed results
    python -m benchmarks.refresh --check         # fail if README/graphics are stale

Steps:

1. ``agent_bench`` on the seeded corpus → ``results/agent_corpus.json``.
   Headroom is included when ``--headroom`` names its interpreter or the venv
   from ``python -m benchmarks.headroom_env`` exists; otherwise its last
   numbers are kept as long as the corpus is byte-identical.
2. With ``--sessions``: ``session_replay`` over ``~/.claude/projects`` and
   ``~/.codex/sessions`` → ``results/session_replay.json`` (counts and token
   sums only; see that module for exactly what it contains).
3. ``docs/assets/generate.py``: hero, flow, benchmark and head-to-head SVGs,
   light and dark.
4. README.md: the block between ``<!-- bench:start -->`` and
   ``<!-- bench:end -->``.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from benchmarks import agent_bench, readme
from benchmarks.corpus import DEFAULT_SEED
from benchmarks.harness import RESULTS, default_headroom_python, read_json, write_json

ROOT = Path(__file__).resolve().parents[2]
GENERATE = ROOT / "docs" / "assets" / "generate.py"
SESSIONS = RESULTS / "session_replay.json"


def _generator():
    spec = importlib.util.spec_from_file_location("sensei_docs_generate", GENERATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rendered() -> dict[Path, str]:
    """Every generated file, as it should be for the committed results."""
    gen = _generator()
    data = gen.load_results()
    before, after = gen.headline_tokens(data)
    out: dict[Path, str] = {}
    for name, theme in gen.THEMES.items():
        out[gen.OUT / f"hero-{name}.svg"] = gen.hero(theme, before, after)
        out[gen.OUT / f"flow-{name}.svg"] = gen.flow(theme, before, after)
        out[gen.OUT / f"benchmark-{name}.svg"] = gen.benchmark_svg(theme, data, gen.KINDS)
        out[gen.OUT / f"headtohead-{name}.svg"] = gen.headtohead_svg(
            theme, data, gen.HEADROOM_SCENARIOS, gen.HEADROOM_PUBLISHED
        )
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    out[ROOT / "README.md"] = readme.update(text, readme.render(data["agent"], data["sessions"]))
    return out


def render() -> None:
    for path, content in rendered().items():
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")


def stale() -> list[str]:
    return [
        str(p.relative_to(ROOT))
        for p, content in rendered().items()
        if not p.exists() or p.read_text(encoding="utf-8") != content
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--headroom", metavar="PYTHON", help="Headroom's interpreter (default: auto-detect)"
    )
    parser.add_argument(
        "--no-headroom", action="store_true", help="do not run Headroom even if available"
    )
    parser.add_argument(
        "--sessions", action="store_true", help="also replay your own sessions (opt-in)"
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--render-only", action="store_true", help="redraw from the committed results"
    )
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if README or graphics are stale"
    )
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.check:
        out = stale()
        if out:
            print(
                "stale (run `python -m benchmarks.refresh --render-only`):",
                *out,
                sep="\n  ",
                file=sys.stderr,
            )
            return 1
        print("README and graphics match the committed results")
        return 0

    if not args.render_only:
        hp = None if args.no_headroom else (args.headroom or default_headroom_python())
        print(f"agent corpus: Sensei{' + Headroom' if hp else ''} …")
        data = agent_bench.run(DEFAULT_SEED, args.repeats, hp)
        agent_bench.carry_over_headroom(data, read_json(agent_bench.DEFAULT_OUT))
        agent_bench.print_table(data)
        write_json(agent_bench.DEFAULT_OUT, data)

        if args.sessions:
            from benchmarks import cost, session_replay
            from benchmarks.harness import HeadroomCompressor, Tokenizer, WatchedSenseiCompressor

            files = list(
                session_replay.discover(
                    Path.home() / ".claude" / "projects", Path.home() / ".codex" / "sessions"
                )
            )
            tools: dict[str, object] = {"sensei": WatchedSenseiCompressor()}
            if hp:
                tools["headroom"] = HeadroomCompressor(hp)
            summary = session_replay.replay(
                files, tools, Tokenizer(), cost.PRICES[cost.DEFAULT_MODEL]
            )
            session_replay.print_report(summary)
            write_json(SESSIONS, session_replay.shareable(summary))

    render()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
