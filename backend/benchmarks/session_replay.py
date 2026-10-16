"""Replay your own agent sessions through Sensei — locally, numbers only.

    python -m benchmarks.session_replay                         # print a report
    python -m benchmarks.session_replay --headroom              # and Headroom on the same data
    python -m benchmarks.session_replay --summary-json out.json # opt-in: numbers only

A synthetic corpus can be tuned until it says anything. The number that
matters is what Sensei would have removed from the sessions you actually ran,
so this reads them where the agents keep them:

* Claude Code — ``~/.claude/projects/**/*.jsonl``
* Codex       — ``~/.codex/sessions/**/*.jsonl``

and pushes every tool result through the same path the gateway uses for
``tool_result`` blocks (``ContentRouter.compress(edit_target=True)``).

Privacy, precisely: transcripts are read, never copied. Nothing is written
unless you pass ``--summary-json``, and that file holds counts and token sums
per fixed category (``git``, ``test``, ``Read``, ``mcp`` …) — no text, no
command lines, no file or project names, no tool names beyond a fixed list.
It is safe to commit; the README's headline comes from such a file.

What it reports:

* tokens before and after per tool and per command family, counting every
  occurrence (identical results are compressed once and weighted by count);
* how much of the tool-result volume is an exact repeat of an earlier result in
  the same session — the share cross-turn deduplication could remove;
* the real bill, from the usage each request recorded (cache writes, cache
  reads, uncached input, output), and the dollars compression would have
  taken off it: a result that enters at request ``i`` of a context segment is
  re-read on every later request until the next compaction, so each saved
  token is worth ``write + read x later_requests`` (``benchmarks.cost``).

The tokenizer is tiktoken cl100k for both before and after. Claude's own
tokenizer counts code differently (about 30% more on Claude 4.7+), so the
dollar figure is an estimate in the conservative direction; the percentages
are ratios and do not depend on it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from benchmarks import cost
from benchmarks.harness import (
    HeadroomCompressor,
    Output,
    Tokenizer,
    WatchedSenseiCompressor,
    default_headroom_python,
    percentile,
    write_json,
)

MIN_CHARS = 100  # the gateway leaves anything shorter alone

# ─── Classification: a fixed vocabulary, so the summary can never leak names ──

_SHELL_FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("git", re.compile(r"^git\b")),
    ("gh", re.compile(r"^gh\b")),
    ("search", re.compile(r"^(?:grep|rg|ag|ack|egrep|fgrep|findstr|select-string)\b", re.I)),
    ("listing", re.compile(r"^(?:ls|dir|find|fd|tree|get-childitem|du|wc)\b", re.I)),
    (
        "file_view",
        re.compile(r"^(?:cat|head|tail|sed|nl|less|more|type|get-content|awk|jq)\b", re.I),
    ),
    (
        "test",
        re.compile(
            r"^(?:pytest|python3? -m pytest|npx (?:vitest|jest|playwright)|vitest|jest|cargo test|go test|"
            r"npm (?:run )?test|pnpm (?:run )?test|yarn test|uv run pytest|tox|nox|ctest|mvn test|gradle test)\b",
            re.I,
        ),
    ),
    (
        "lint",
        re.compile(
            r"^(?:ruff|eslint|npx eslint|mypy|pyright|tsc|npx tsc|cargo clippy|clippy|prettier|black|flake8)\b",
            re.I,
        ),
    ),
    (
        "build",
        re.compile(
            r"^(?:cargo (?:build|check|run)|npm run build|pnpm (?:run )?build|yarn build|make|cmake|go build|"
            r"docker (?:build|compose)|maturin|vite build|npx vite|gradle|mvn|dotnet build|msbuild|pyinstaller)\b",
            re.I,
        ),
    ),
    (
        "install",
        re.compile(
            r"^(?:pip3?|uv|npm (?:i|install|ci)|pnpm (?:i|install)|yarn (?:add|install)|cargo add|winget|brew|apt|choco)\b",
            re.I,
        ),
    ),
    (
        "http",
        re.compile(r"^(?:curl|wget|invoke-webrequest|invoke-restmethod|iwr|irm|http)\b", re.I),
    ),
    ("containers", re.compile(r"^(?:docker|kubectl|helm|podman)\b", re.I)),
    (
        "run",
        re.compile(
            r"^(?:python3?|py|node|npx|uv run|deno|bun|cargo|go|java|dotnet|\.?/|powershell|pwsh)",
            re.I,
        ),
    ),
)

_CLAUDE_TOOLS = {
    "Read": "Read",
    "Grep": "Grep",
    "Glob": "Glob",
    "WebFetch": "WebFetch",
    "WebSearch": "WebSearch",
    "Edit": "Edit",
    "MultiEdit": "Edit",
    "Write": "Write",
    "NotebookEdit": "Edit",
    "Task": "Agent",
    "Agent": "Agent",
    "TodoWrite": "Todo",
}


def shell_family(command: str) -> str:
    """The command family, from a fixed list. Never returns the command."""
    cmd = command.strip()
    # Strip the usual wrappers so `cd x && git log` counts as git.
    for _ in range(4):
        cmd = re.sub(
            r"^(?:cd\s+\S+\s*(?:&&|;)\s*|[A-Z_][A-Z0-9_]*=\S+\s+|sudo\s+|time\s+|\(\s*)", "", cmd
        )
    cmd = re.sub(r"^\S*[\\/](?=(?:python3?|node|git|pytest|cargo|npm|uv)\b)", "", cmd)
    for name, rx in _SHELL_FAMILIES:
        if rx.search(cmd):
            return name
    return "other"


def claude_category(name: str, tool_input: dict) -> str:
    if name == "Bash":
        return "shell:" + shell_family(str(tool_input.get("command", "")))
    if name.startswith("mcp__"):
        return "mcp"
    return _CLAUDE_TOOLS.get(name, "other")


def codex_category(name: str, args: str) -> str:
    if name in ("shell", "exec", "local_shell", "container.exec", "exec_command", "shell_command"):
        cmd = args
        try:
            parsed = json.loads(args)
            c = parsed.get("command") or parsed.get("cmd") or ""
            cmd = " ".join(c) if isinstance(c, list) else str(c)
            # ["bash", "-lc", "git log"] → git log
            cmd = re.sub(r"^(?:bash|sh|zsh|powershell(?:\.exe)?|pwsh)\s+(?:-\w+\s+)*", "", cmd)
        except (ValueError, AttributeError):
            pass
        return "shell:" + shell_family(cmd)
    if name == "apply_patch":
        return "Edit"
    if name.startswith("mcp") or "__" in name:
        return "mcp"
    return "other"


# ─── Reading sessions ─────────────────────────────────────────────────────────


@dataclass
class Result:
    text: str
    category: str
    segment: int  # context segment (bumped at each compaction)
    position: int  # requests already sent in this session before this result


@dataclass
class Session:
    agent: str
    results: list[Result] = field(default_factory=list)
    # Requests per segment, and the usage they recorded.
    requests: Counter = field(default_factory=Counter)
    usage: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    request_count: int = 0


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text")
        ]
    return []


def read_claude(path: Path) -> Session:
    s = Session("claude-code")
    names: dict[str, tuple[str, dict]] = {}
    seen_ids: set[str] = set()
    segment = 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "system" and ev.get("subtype") == "compact_boundary":
                segment += 1
                continue
            msg = ev.get("message") or {}
            if ev.get("type") == "assistant" and isinstance(msg, dict):
                mid = msg.get("id")
                usage = msg.get("usage")
                if mid and usage and mid not in seen_ids:
                    seen_ids.add(mid)
                    s.request_count += 1
                    s.requests[segment] += 1
                    s.usage["input"] += int(usage.get("input_tokens") or 0)
                    s.usage["cache_write"] += int(usage.get("cache_creation_input_tokens") or 0)
                    s.usage["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                    s.usage["output"] += int(usage.get("output_tokens") or 0)
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    names[block.get("id", "")] = (block.get("name", "?"), block.get("input") or {})
                elif block.get("type") == "tool_result":
                    name, tin = names.get(block.get("tool_use_id", ""), ("?", {}))
                    cat = claude_category(name, tin if isinstance(tin, dict) else {})
                    for text in _texts(block.get("content")):
                        if len(text) >= MIN_CHARS:
                            s.results.append(Result(text, cat, segment, s.requests[segment]))
    return s


def read_codex(path: Path) -> Session:
    s = Session("codex")
    calls: dict[str, tuple[str, str]] = {}
    segment = 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type")
            p = ev.get("payload") or {}
            if kind == "compacted":
                segment += 1
                continue
            if kind == "token_usage_record":
                u = p.get("usage") or {}
                s.request_count += 1
                s.requests[segment] += 1
                cached = int(u.get("cached_input_tokens") or 0)
                write = int(u.get("cache_write_input_tokens") or 0)
                s.usage["cache_read"] += cached
                s.usage["cache_write"] += write
                s.usage["input"] += max(0, int(u.get("input_tokens") or 0) - cached - write)
                s.usage["output"] += int(u.get("output_tokens") or 0)
                continue
            if kind != "response_item":
                continue
            t = p.get("type")
            if t in ("function_call", "custom_tool_call", "local_shell_call"):
                args = p.get("arguments") or p.get("input") or json.dumps(p.get("action") or {})
                calls[p.get("call_id", "")] = (
                    p.get("name") or "local_shell",
                    args if isinstance(args, str) else json.dumps(args),
                )
            elif t in (
                "function_call_output",
                "custom_tool_call_output",
                "local_shell_call_output",
            ):
                name, args = calls.get(p.get("call_id", ""), ("?", ""))
                cat = codex_category(name, args)
                out = p.get("output")
                if isinstance(out, dict):
                    out = out.get("content") or out.get("output") or ""
                for text in _texts(out):
                    if len(text) >= MIN_CHARS:
                        s.results.append(Result(text, cat, segment, s.requests[segment]))
    return s


def discover(claude_dir: Path | None, codex_dir: Path | None) -> Iterator[tuple[str, Path]]:
    if claude_dir and claude_dir.exists():
        for p in sorted(claude_dir.rglob("*.jsonl")):
            yield "claude-code", p
    if codex_dir and codex_dir.exists():
        for p in sorted(codex_dir.rglob("*.jsonl")):
            yield "codex", p


# ─── Measuring ────────────────────────────────────────────────────────────────


@dataclass
class Bucket:
    n: int = 0
    before: int = 0
    after: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    saved_usd: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    duplicate: int = 0
    timeouts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    slow: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def as_dict(self, tools: list[str]) -> dict:
        out = {"results": self.n, "tokens": self.before, "repeat_tokens": self.duplicate}
        for t in tools:
            a = self.after[t]
            out[t] = {
                "after": a,
                "saved_pct": round((1 - a / self.before) * 100, 2) if self.before else 0.0,
                "saved_usd": round(self.saved_usd[t], 4),
                "slow_over_1s": self.slow[t],
                "timeouts": self.timeouts[t],
            }
        return out


def replay(
    files: list[tuple[str, Path]],
    tools: dict[str, object],
    tok: Tokenizer,
    price: cost.Pricing,
    progress: bool = True,
) -> dict:
    # Sensei's warnings quote the payload they fired on; here that payload is
    # somebody's transcript, which this tool promises never to echo.
    logging.getLogger("sensei").setLevel(logging.ERROR)
    sessions: list[Session] = []
    for i, (agent, path) in enumerate(files):
        try:
            sessions.append(read_claude(path) if agent == "claude-code" else read_codex(path))
        except OSError as exc:
            print(f"skipped a file: {exc.__class__.__name__}", file=sys.stderr)
        if progress and (i + 1) % 50 == 0:
            print(f"  read {i + 1}/{len(files)} files", file=sys.stderr)

    # Compress each distinct text once; weight by occurrences.
    unique: dict[str, str] = {}
    for s in sessions:
        for r in s.results:
            unique.setdefault(hashlib.sha256(r.text.encode("utf-8", "replace")).hexdigest(), r.text)
    keys = list(unique)
    texts = [unique[k] for k in keys]
    if progress:
        print(
            f"  {sum(len(s.results) for s in sessions)} tool results, {len(texts)} distinct",
            file=sys.stderr,
        )

    before_tok = {k: tok.count(t) for k, t in zip(keys, texts, strict=True)}
    after_tok: dict[str, dict[str, int]] = {}
    flags: dict[str, dict[str, tuple[bool, bool]]] = {}  # (timed out, slower than 1 s)
    latency: dict[str, dict[str, float]] = {}
    timing: dict[str, float] = {}
    for name, comp in tools.items():
        started = time.perf_counter()
        outs: list[Output] = []
        batch = 2000
        for j in range(0, len(texts), batch):
            outs += comp.run(texts[j : j + batch], 1)  # type: ignore[attr-defined]
            if progress:
                print(f"  {name}: {min(j + batch, len(texts))}/{len(texts)}", file=sys.stderr)
        timing[name] = time.perf_counter() - started
        after_tok[name] = {k: tok.count(o.text) for k, o in zip(keys, outs, strict=True)}
        flags[name] = {
            k: (o.timed_out, bool(o.seconds) and max(o.seconds) > 1.0)
            for k, o in zip(keys, outs, strict=True)
        }
        secs = [max(o.seconds) for o in outs if o.seconds and not o.timed_out]
        latency[name] = {
            "p50_ms": round(percentile(secs, 50) * 1000, 2),
            "p95_ms": round(percentile(secs, 95) * 1000, 2),
            "p99_ms": round(percentile(secs, 99) * 1000, 2),
            "max_ms": round(max(secs, default=0) * 1000, 1),
        }
        del outs

    names = list(tools)
    by_cat: dict[str, Bucket] = defaultdict(Bucket)
    by_agent: dict[str, Bucket] = defaultdict(Bucket)
    total = Bucket()
    bill = {"cache_write": 0.0, "cache_read": 0.0, "uncached": 0.0, "output": 0.0}
    ptok = price.per_token()
    requests = 0
    for s in sessions:
        requests += s.request_count
        bill["uncached"] += s.usage["input"] * ptok
        bill["cache_write"] += s.usage["cache_write"] * ptok * price.cache_write
        bill["cache_read"] += s.usage["cache_read"] * ptok * price.cache_read
        bill["output"] += s.usage["output"] * price.output_per_mtok / 1_000_000
        seen: set[str] = set()
        for r in s.results:
            k = hashlib.sha256(r.text.encode("utf-8", "replace")).hexdigest()
            b = before_tok[k]
            later = max(0, s.requests[r.segment] - r.position - 1) if s.request_count else 0
            dup = b if k in seen else 0
            seen.add(k)
            for bucket in (by_cat[r.category], by_agent[s.agent], total):
                bucket.n += 1
                bucket.before += b
                bucket.duplicate += dup
                for t in names:
                    a = after_tok[t][k]
                    bucket.after[t] += a
                    timed_out, slow = flags[t][k]
                    bucket.timeouts[t] += timed_out
                    bucket.slow[t] += slow
                    # A result that grew is sent as it was: the gateway keeps
                    # whichever is smaller only if the compressor does, so count
                    # growth honestly as a cost.
                    if s.request_count:
                        bucket.saved_usd[t] += cost.tool_result_savings(b - a, later, price)
        s.results.clear()

    billed = sum(bill.values())
    summary = {
        "schema": 1,
        "privacy": "aggregate counts and token sums only; no text, commands, paths or project names",
        "tokenizer": tok.name,
        "pricing": price.model,
        "sessions": len(sessions),
        "sessions_by_agent": dict(Counter(s.agent for s in sessions)),
        "requests": requests,
        "distinct_results": len(texts),
        "tools": {t: getattr(c, "version", "?") for t, c in tools.items()},
        "seconds": {t: round(v, 1) for t, v in timing.items()},
        "latency": latency,
        "timeout_s": {t: getattr(c, "timeout", None) for t, c in tools.items()},
        "total": total.as_dict(names),
        "by_agent": {a: b.as_dict(names) for a, b in sorted(by_agent.items())},
        "by_category": {
            c: b.as_dict(names) for c, b in sorted(by_cat.items(), key=lambda kv: -kv[1].before)
        },
        "bill_usd": {k: round(v, 2) for k, v in bill.items()} | {"total": round(billed, 2)},
    }
    for t in names:
        summary["total"][t]["bill_saved_pct"] = (
            round(total.saved_usd[t] / billed * 100, 2) if billed else 0.0
        )
    return summary


def shareable(summary: dict) -> dict:
    """The summary without absolute spend: what gets written to disk.

    Token counts and percentages say how well compression works; what somebody
    spent on their agents says something about them, and nobody needs it to
    check a benchmark. Dollar amounts become shares of the bill.
    """
    out = json.loads(json.dumps(summary))
    bill = out.pop("bill_usd", {})
    total = bill.get("total") or 0.0
    out["bill_mix_pct"] = {
        k: round(v / total * 100, 2) for k, v in bill.items() if k != "total" and total
    }

    def scrub(bucket: dict) -> None:
        for name in out["tools"]:
            if name in bucket:
                usd = bucket[name].pop("saved_usd", 0.0)
                bucket[name]["bill_saved_pct"] = round(usd / total * 100, 3) if total else 0.0

    scrub(out["total"])
    for group in ("by_agent", "by_category"):
        for bucket in out[group].values():
            scrub(bucket)
    return out


def print_report(summary: dict) -> None:
    names = list(summary["tools"])
    t = summary["total"]
    print(
        f"\n{summary['sessions']} sessions ({', '.join(f'{v} {k}' for k, v in summary['sessions_by_agent'].items())}), "
        f"{summary['requests']} requests, {t['results']} tool results ({summary['distinct_results']} distinct)"
    )
    print(f"tokenizer {summary['tokenizer']} · prices {summary['pricing']}\n")
    head = f"{'category':<20}{'results':>9}{'tokens':>12}{'repeat':>8}" + "".join(
        f"{n:>11}" for n in names
    )
    print(head)
    print("-" * len(head))
    for cat, b in summary["by_category"].items():
        rep = b["repeat_tokens"] / b["tokens"] * 100 if b["tokens"] else 0
        cells = "".join(f"{b[n]['saved_pct']:>10.1f}%" for n in names)
        print(f"{cat:<20}{b['results']:>9}{b['tokens']:>12}{rep:>7.0f}%{cells}")
    print("-" * len(head))
    rep = t["repeat_tokens"] / t["tokens"] * 100 if t["tokens"] else 0
    print(
        f"{'TOTAL':<20}{t['results']:>9}{t['tokens']:>12}{rep:>7.0f}%"
        + "".join(f"{t[n]['saved_pct']:>10.1f}%" for n in names)
    )
    bill = summary["bill_usd"]
    print(
        f"\nRecorded usage priced as {summary['pricing']}: ${bill['total']:.2f} "
        f"(cache writes ${bill['cache_write']:.2f}, cache reads ${bill['cache_read']:.2f}, "
        f"uncached ${bill['uncached']:.2f}, output ${bill['output']:.2f})"
    )
    for n in names:
        print(f"  {n}: -${t[n]['saved_usd']:.2f} ({t[n]['bill_saved_pct']:.2f}% of that bill)")
    print()
    for n in names:
        lat = summary["latency"][n]
        print(
            f"  {n} latency per distinct result: p50 {lat['p50_ms']} ms · p95 {lat['p95_ms']} ms · "
            f"p99 {lat['p99_ms']} ms · max {lat['max_ms']} ms · over 1 s: {t[n]['slow_over_1s']} · "
            f"cut off: {t[n]['timeouts']}"
        )
    print("\n'repeat' = tokens that exactly repeat an earlier tool result in the same session.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    home = Path.home()
    parser.add_argument("--claude-dir", type=Path, default=home / ".claude" / "projects")
    parser.add_argument(
        "--codex-dir",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", home / ".codex")) / "sessions",
    )
    parser.add_argument(
        "--project", help="only Claude Code project folders containing this substring"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="at most this many session files (newest first)"
    )
    parser.add_argument(
        "--headroom", nargs="?", const="auto", metavar="PYTHON", help="also replay through Headroom"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds per tool result before Sensei is cut off",
    )
    parser.add_argument("--model", default=cost.DEFAULT_MODEL, choices=sorted(cost.PRICES))
    parser.add_argument(
        "--summary-json", type=Path, metavar="PATH", help="write the numbers-only summary here"
    )
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = list(discover(args.claude_dir, args.codex_dir))
    if args.project:
        files = [
            (a, p)
            for a, p in files
            if a != "claude-code" or args.project in str(p.relative_to(args.claude_dir))
        ]
    if args.limit:
        files = sorted(files, key=lambda f: f[1].stat().st_mtime, reverse=True)[: args.limit]
    if not files:
        print("no session files found", file=sys.stderr)
        return 1

    tools: dict[str, object] = {"sensei": WatchedSenseiCompressor(args.timeout)}
    if args.headroom:
        hp = default_headroom_python() if args.headroom == "auto" else args.headroom
        if not hp:
            print(
                "Headroom venv not found; run `python -m benchmarks.headroom_env` first",
                file=sys.stderr,
            )
            return 2
        tools["headroom"] = HeadroomCompressor(hp)

    print(f"replaying {len(files)} session files …", file=sys.stderr)
    summary = replay(files, tools, Tokenizer(), cost.PRICES[args.model])
    print_report(summary)
    if args.summary_json:
        write_json(args.summary_json, shareable(summary))
        print(f"\nwrote {args.summary_json} (numbers only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
