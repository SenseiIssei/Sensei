"""Replay recorded agent conversations through the gateway, priced like a provider.

Per-blob compression benchmarks answer "how much smaller is this text". A
coding agent is billed differently: the whole history is resent every turn,
the provider serves the unchanged prefix from its prompt cache at a tenth of
the price, and anything that changes earlier bytes is billed again as a cache
*write* at 1.25x. A compressor that saves 30% of tokens while breaking the
cache can raise the bill. This harness measures that bill.

Input: Claude Code transcripts (``~/.claude/projects/*/*.jsonl``) on this
machine. They are read at run time and never written anywhere; only aggregate
numbers are printed. Each assistant turn in a transcript becomes one Messages
request: the history before it, with Claude Code's cache breakpoints (end of
the system prompt, last block of the last message).

Upstream: a stub that emulates Anthropic's prompt-cache accounting — prefix
hashes stored at breakpoints, a 20-block lookback, a 5-minute TTL refreshed on
read, a minimum cacheable prefix — and reports ``cache_read_input_tokens`` and
``cache_creation_input_tokens`` back, so the gateway's live zone sees what it
would see in production. Time comes from the transcript's timestamps.

Three arms over the same requests:

- ``raw``: what the client sends, unmodified.
- ``sensei-0.2``: the 0.2 gateway's stateless compression of every message.
- ``sensei``: this gateway, end to end through the HTTP route.

Effective cost = uncached input x 1 + cache writes x 1.25 + cache reads x 0.1,
in units of the model's base input price. Output tokens are not modelled: the
stub cannot know how the model would have answered a compressed prompt, so
they are identical across arms by construction.

What this does not capture, said plainly: Claude Code's real system prompt and
tool definitions are not in the transcript, so a synthetic prefix of fixed size
stands in for them (``--prefix-tokens``); attachments (system reminders) are
not replayed; subagent side-chains are skipped. Token counts use tiktoken's
cl100k encoding, which is not Claude's tokenizer — ratios are meaningful,
absolute counts approximate.

Run::

    python -m benchmarks.gateway_replay --max-sessions 8 --max-turns 150
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

WRITE_5M = 1.25
READ = 0.1


# ── Transcripts → requests ──────────────────────────────────────────────────


def _ts(value: Any) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def requests_from_transcript(path: str, max_turns: int) -> list[tuple[float, list[dict[str, Any]]]]:
    """(time, messages) for every assistant turn on the main chain."""
    history: list[dict[str, Any]] = []
    out: list[tuple[float, list[dict[str, Any]]]] = []
    current_request: str | None = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("isSidechain"):
                continue
            kind = entry.get("type")
            if kind == "system" and entry.get("subtype") == "compact_boundary":
                history, current_request = [], None
                continue
            message = entry.get("message")
            if kind not in ("user", "assistant") or not isinstance(message, dict):
                continue
            blocks = _blocks(message.get("content"))
            if not blocks:
                continue
            if kind == "assistant":
                rid = entry.get("requestId") or message.get("id")
                if rid != current_request:
                    # A new model call: everything before it is the request.
                    if history and history[-1]["role"] == "user":
                        out.append((_ts(entry.get("timestamp")), json.loads(json.dumps(history))))
                        if len(out) >= max_turns:
                            return out
                    current_request = rid
                    history.append({"role": "assistant", "content": []})
                elif not history or history[-1]["role"] != "assistant":
                    history.append({"role": "assistant", "content": []})
                history[-1]["content"].extend(blocks)
            else:
                current_request = None
                if history and history[-1]["role"] == "user":
                    history[-1]["content"].extend(blocks)
                else:
                    history.append({"role": "user", "content": list(blocks)})
    return out


# ── Claude Code's request shape, approximately ──────────────────────────────


def synthetic_prefix(requests: list[tuple[float, list[dict[str, Any]]]], tokens: int):
    """A stand-in system prompt of ~``tokens`` and the tools the session used."""
    words = ("agent", "tool", "file", "edit", "read", "test", "code", "careful", "user", "task")
    filler = " ".join(words[i % len(words)] + str(i % 97) for i in range(int(tokens * 0.75)))
    system = [{"type": "text", "text": filler, "cache_control": {"type": "ephemeral"}}]
    seen: dict[str, set[str]] = {}
    for _, messages in requests:
        for m in messages:
            if m["role"] != "assistant":
                continue
            for b in m["content"]:
                if b.get("type") == "tool_use" and isinstance(b.get("input"), dict):
                    seen.setdefault(str(b.get("name")), set()).update(b["input"].keys())
    tools = [
        {
            "name": name,
            "description": f"The {name} tool.",
            "input_schema": {
                "type": "object",
                "properties": {k: {"type": "string", "description": k} for k in sorted(keys)},
            },
        }
        for name, keys in sorted(seen.items())
    ]
    return system, tools


def with_breakpoint(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = json.loads(json.dumps(messages))
    for m in reversed(out):
        if m["content"]:
            m["content"][-1]["cache_control"] = {"type": "ephemeral"}
            break
    return out


# ── Anthropic prompt-cache emulation ────────────────────────────────────────


_enc = None


def tokens_of(text: str) -> int:
    global _enc
    if _enc is None:
        try:
            import tiktoken

            _enc = tiktoken.get_encoding("cl100k_base")
        except Exception:  # offline: fall back to the 4-chars estimate
            _enc = False
    if _enc is False:
        return max(1, len(text) // 4)
    return len(_enc.encode(text, disallowed_special=()))


_memo: dict[bytes, int] = {}


# Images and PDFs are billed by size, not by the length of their base64. A
# typical screenshot is ~1,600 tokens; counting its base64 as text would make
# one screenshot look like a hundred thousand tokens of prose.
IMAGE_TOKENS = 1600


def _text_tokens(value: Any) -> int:
    """Tokens of a block, with media at a flat rate."""
    if isinstance(value, dict):
        if value.get("type") in ("image", "document"):
            return IMAGE_TOKENS
        return sum(_text_tokens(v) for v in value.values()) + 1
    if isinstance(value, list):
        return sum(_text_tokens(v) for v in value)
    if isinstance(value, str):
        return tokens_of(value)
    return 1


def _block_cost(block: Any) -> tuple[bytes, int, bool]:
    has_cc = isinstance(block, dict) and "cache_control" in block
    clean = (
        {k: v for k, v in block.items() if k != "cache_control"}
        if isinstance(block, dict)
        else block
    )
    raw = json.dumps(clean, sort_keys=True, ensure_ascii=False).encode("utf-8", "surrogatepass")
    key = hashlib.blake2b(raw, digest_size=16).digest()
    n = _memo.get(key)
    if n is None:
        n = _memo[key] = _text_tokens(clean)
    return key, n, has_cc


def render(body: dict[str, Any]) -> list[tuple[bytes, int, bool]]:
    """The request as the cache sees it: tools, then system, then messages."""
    out = []
    for tool in body.get("tools") or []:
        out.append(_block_cost(tool))
    system = body.get("system")
    for block in _blocks(system) if system is not None else []:
        out.append(_block_cost(block))
    for m in body.get("messages") or []:
        for i, block in enumerate(_blocks(m.get("content"))):
            key, n, cc = _block_cost(block)
            if i == 0:  # the role is part of the rendering
                key = hashlib.blake2b(key + m["role"].encode(), digest_size=16).digest()
            out.append((key, n, cc))
    return out


@dataclass
class Bill:
    requests: int = 0
    input: int = 0
    read: int = 0
    write: int = 0

    @property
    def prompt(self) -> int:
        return self.input + self.read + self.write

    @property
    def cost(self) -> float:
        return self.input + WRITE_5M * self.write + READ * self.read

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "prompt_tokens": self.prompt,
            "uncached": self.input,
            "cache_read": self.read,
            "cache_write": self.write,
            "hit_rate": round(self.read / self.prompt, 4) if self.prompt else None,
            "effective_cost_units": round(self.cost),
        }


@dataclass
class CacheEmulator:
    ttl: float = 300.0
    min_tokens: int = 1024
    lookback: int = 20
    entries: dict[bytes, float] = field(default_factory=dict)
    bill: Bill = field(default_factory=Bill)

    def charge(self, body: dict[str, Any], now: float) -> dict[str, int]:
        blocks = render(body)
        prefix: list[bytes] = []
        cum: list[int] = []
        h = b""
        total = 0
        for key, n, _ in blocks:
            h = hashlib.blake2b(h + key, digest_size=16).digest()
            total += n
            prefix.append(h)
            cum.append(total)
        breakpoints = [i for i, (_, _, cc) in enumerate(blocks) if cc]
        hit = -1
        for bp in reversed(breakpoints):
            for j in range(bp, max(-1, bp - self.lookback), -1):
                if self.entries.get(prefix[j], -1.0) >= now:
                    hit = j
                    break
            if hit >= 0:
                break
        read = cum[hit] if hit >= 0 else 0
        if hit >= 0:
            self.entries[prefix[hit]] = now + self.ttl
        write = 0
        if breakpoints:
            last = breakpoints[-1]
            if cum[last] >= self.min_tokens and last > hit:
                write = cum[last] - read
            for bp in breakpoints:
                if cum[bp] >= self.min_tokens:
                    self.entries[prefix[bp]] = now + self.ttl
        uncached = total - read - write
        self.bill.requests += 1
        self.bill.input += uncached
        self.bill.read += read
        self.bill.write += write
        return {
            "input_tokens": uncached,
            "cache_read_input_tokens": read,
            "cache_creation_input_tokens": write,
            "output_tokens": 1,
        }


# ── The three arms ──────────────────────────────────────────────────────────


def run(paths: list[str], max_turns: int, prefix_tokens: int, ttl: float) -> dict[str, Any]:
    import httpx
    from fastapi.testclient import TestClient

    from sensei.config import settings
    from sensei.gateway import ccr, pipeline, session
    from sensei.gateway.session import live_zone
    from sensei.main import app
    from sensei.routers import gateway

    # Nothing from a replay may land in the user's own ledger, audit log or
    # CCR directory.
    settings.savings_persist = False
    settings.gateway_state_persist = False
    settings.audit_enabled = False
    settings.redaction_enabled = False
    settings.output_shaper = False
    settings.fallback_enabled = False
    settings.upstream_retries = 0
    settings.rate_limit_enabled = False
    settings.anthropic_api_base_url = "https://api.anthropic.com/v1"
    settings.gateway_cache_ttl_seconds = int(ttl)

    clock = [0.0]
    session.clock = lambda: clock[0]
    arms = {
        "raw": CacheEmulator(ttl=ttl),
        "sensei-0.2": CacheEmulator(ttl=ttl),
        "sensei": CacheEmulator(ttl=ttl),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        usage = arms["sensei"].charge(body, clock[0])
        return httpx.Response(
            200,
            json={
                "id": "msg",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": usage,
            },
        )

    def factory(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url.rstrip("/"), transport=httpx.MockTransport(handler)
        )

    gateway._pooled_client = factory  # type: ignore[assignment]

    # CPU spent preparing each request, per arm: 0.2 recompresses the whole
    # history every turn, the live zone only the new messages.
    cpu = {"sensei-0.2": 0.0, "sensei": 0.0}
    real_prepare = pipeline.prepare

    def timed_prepare(*a: Any, **kw: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return real_prepare(*a, **kw)
        finally:
            cpu["sensei"] += time.perf_counter() - t0

    pipeline.prepare = timed_prepare  # type: ignore[assignment]
    client = TestClient(app)
    headers = {
        "x-api-key": "replay",
        "anthropic-version": "2023-06-01",
        "user-agent": "claude-cli/replay",
    }

    sessions = 0
    turns = 0
    started = time.time()
    info_totals: dict[str, int] = {}
    causes: dict[str, int] = {}
    for path in paths:
        requests = requests_from_transcript(path, max_turns)
        if len(requests) < 3:
            continue
        sessions += 1
        system, tools = synthetic_prefix(requests, prefix_tokens)
        for at, messages in requests:
            turns += 1
            clock[0] = at
            msgs = with_breakpoint(messages)
            body = {
                "model": "claude-sonnet-5-5",
                "max_tokens": 1024,
                "system": system,
                "tools": tools,
                "messages": msgs,
            }
            arms["raw"].charge(body, at)

            settings.gateway_preserve_cache = False
            copy = json.loads(json.dumps(msgs))
            t0 = time.perf_counter()
            old_system, old_messages, _ = gateway.compress_anthropic_request(system, copy)
            cpu["sensei-0.2"] += time.perf_counter() - t0
            arms["sensei-0.2"].charge({**body, "system": old_system, "messages": old_messages}, at)

            resp = client.post("/v1/messages", json=body, headers=headers)
            if resp.status_code != 200:
                print(f"gateway answered {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
                continue
            for key, value in (resp.json().get("sensei") or {}).items():
                if key in ("tool_tokens_saved", "dedup_tokens_saved", "stale_reads"):
                    info_totals[key] = info_totals.get(key, 0) + int(value)
        for cause, n in live_zone.causes.items():
            causes[cause] = causes.get(cause, 0) + n
        live_zone.clear()
        ccr.store.clear()

    result = {
        "sessions": sessions,
        "turns": turns,
        "ttl_seconds": ttl,
        "prefix_tokens": prefix_tokens,
        "seconds": round(time.time() - started, 1),
        "arms": {name: em.bill.as_dict() for name, em in arms.items()},
        "live_zone_causes": causes,
        "gateway_info": info_totals,
        "cpu_ms_per_request": {k: round(v * 1000 / max(1, turns), 2) for k, v in cpu.items()},
    }
    pipeline.prepare = real_prepare  # type: ignore[assignment]
    raw = arms["raw"].bill
    for name in ("sensei-0.2", "sensei"):
        bill = arms[name].bill
        result["arms"][name]["prompt_tokens_vs_raw"] = (
            round(1 - bill.prompt / raw.prompt, 4) if raw.prompt else None
        )
        result["arms"][name]["cost_vs_raw"] = (
            round(1 - bill.cost / raw.cost, 4) if raw.cost else None
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--glob", default=os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    parser.add_argument("--max-sessions", type=int, default=8)
    parser.add_argument("--max-turns", type=int, default=150)
    parser.add_argument("--min-bytes", type=int, default=200_000)
    parser.add_argument("--prefix-tokens", type=int, default=6000)
    parser.add_argument("--ttl", type=float, default=300.0)
    parser.add_argument(
        "--pick",
        choices=("largest", "spread"),
        default="spread",
        help="largest sessions, or an even spread across sizes",
    )
    args = parser.parse_args()

    paths = [p for p in glob.glob(args.glob) if os.path.getsize(p) >= args.min_bytes]
    # Deterministic choice, by size then name.
    paths.sort(key=lambda p: (-os.path.getsize(p), p))
    if args.pick == "spread" and len(paths) > args.max_sessions:
        step = len(paths) / args.max_sessions
        paths = [paths[int(i * step)] for i in range(args.max_sessions)]
    result = run(paths[: args.max_sessions], args.max_turns, args.prefix_tokens, args.ttl)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
