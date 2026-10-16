"""From the client's request to the bytes Sensei forwards, for all three APIs.

One pass, in this order:

1. **Plan** (:mod:`.session`): which leading messages were forwarded before
   and can be replayed as they were, and why not if not.
2. **Transform each new message**: put back a hidden retrieve exchange the
   client never saw (:mod:`.intercept`), answer a retrieve call the client did
   see, otherwise compress — with a retrieve marker on every lossy block when
   the tool is available — then deduplicate against earlier tool results.
   Assistant messages are never rewritten: they are the model's own words, and
   on Claude they may carry signed thinking.
3. **Stale reads**, past the frozen boundary only.
4. **Reassemble** with the current request's ``cache_control`` markers and
   remember what was forwarded.
5. **Tools**: compaction, the retrieve tool, Anthropic tool search.

The compressor itself is passed in, so this module does not depend on the HTTP
layer.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sensei import output_shaping
from sensei.config import settings
from sensei.gateway import ccr, dedup, tools, wire
from sensei.gateway.intercept import fingerprint
from sensei.gateway.session import Plan, apply_cache_control, canon, lineage_key, live_zone

# (text, before, after, saved, blocks)
CompressText = Callable[..., tuple[Any, int, int, int, int]]
Counts = tuple[int, int, int, int]

_TEXT_PART_TYPES = ("input_text", "output_text", "text")


@dataclass
class Prepared:
    api: str
    payload: dict[str, Any]
    savings: dict[str, Any]
    inject: bool = False
    key: str = ""
    cause: str = "off"
    shaped: int = -1
    plan: Plan | None = None
    info: dict[str, Any] = field(default_factory=dict)


class _Tally:
    __slots__ = ("after", "before", "blocks", "saved")

    def __init__(self) -> None:
        self.before = self.after = self.saved = self.blocks = 0

    def add(self, before: int, after: int, saved: int, blocks: int) -> None:
        self.before += before
        self.after += after
        self.saved += saved
        self.blocks += blocks

    def counts(self) -> Counts:
        return (self.before, self.after, self.saved, self.blocks)


def _no_savings() -> dict[str, Any]:
    return {
        "compression_enabled": False,
        "tokens_saved": 0,
        "blocks_compressed": 0,
        "prompt_tokens_before": 0,
        "prompt_tokens_after": 0,
        "compression_ratio": 1.0,
    }


def _savings(before: int, after: int, saved: int, blocks: int) -> dict[str, Any]:
    return {
        "compression_enabled": True,
        "tokens_saved": saved,
        "blocks_compressed": blocks,
        "prompt_tokens_before": before,
        "prompt_tokens_after": after,
        "compression_ratio": round(after / before, 4) if before else 1.0,
    }


def is_oauth(headers: dict[str, str]) -> bool:
    """A Claude subscription request: a bearer token rather than an API key."""
    lowered = {k.lower(): v for k, v in headers.items()}
    if "oauth" in lowered.get("anthropic-beta", ""):
        return True
    auth = lowered.get("authorization", "")
    return auth.lower().startswith("bearer ") and "x-api-key" not in lowered


def _tokens(value: Any) -> int:
    return len(canon(value)) // 4 if value else 0


class _Builder:
    def __init__(self, api: str, compress_text: CompressText, ccr_on: bool) -> None:
        self.api = api
        self.compress_text = compress_text
        self.ccr_on = ccr_on

    def text(self, value: Any, tally: _Tally, *, edit_target: bool) -> Any:
        if not isinstance(value, str):
            return value
        new, before, after, saved, blocks = self.compress_text(value, edit_target=edit_target)
        if self.ccr_on and isinstance(new, str) and blocks and new != value:
            annotated = ccr.annotate(value, new, before, after)
            if annotated != new:
                # The marker is sent, so it is counted.
                after += max(0, (len(annotated) - len(new)) // 4)
                saved = max(0, before - after)
                new = annotated
        tally.add(before, after, saved, blocks)
        return new

    def parts(
        self, parts: list[Any], tally: _Tally, *, edit_target: bool, types: tuple[str, ...]
    ) -> list[Any]:
        out = []
        for part in parts:
            if (
                isinstance(part, dict)
                and part.get("type") in types
                and isinstance(part.get("text"), str)
            ):
                new = self.text(part["text"], tally, edit_target=edit_target)
                out.append(part if new is part["text"] else {**part, "text": new})
            else:
                out.append(part)
        return out

    def message(self, msg: Any, tally: _Tally) -> Any:
        """Compress one message (or Responses item). Assistant turns pass."""
        if not isinstance(msg, dict):
            return msg
        if self.api == "anthropic":
            if msg.get("role") == "assistant":
                return msg
            content = msg.get("content")
            if isinstance(content, str):
                return {**msg, "content": self.text(content, tally, edit_target=False)}
            if not isinstance(content, list):
                return msg
            out = []
            for block in content:
                if not isinstance(block, dict):
                    out.append(block)
                elif block.get("type") == "text":
                    out.append(
                        {**block, "text": self.text(block.get("text"), tally, edit_target=False)}
                    )
                elif block.get("type") == "tool_result":
                    inner = block.get("content")
                    if isinstance(inner, str):
                        inner = self.text(inner, tally, edit_target=True)
                    elif isinstance(inner, list):
                        inner = self.parts(inner, tally, edit_target=True, types=("text",))
                    out.append({**block, "content": inner})
                else:
                    out.append(block)
            return {**msg, "content": out}

        if self.api == "openai":
            role = msg.get("role", "user")
            if role == "assistant":
                return msg
            if role in ("system", "developer") and not settings.gateway_compress_system:
                return msg
            edit_target = role in ("tool", "function")
            content = msg.get("content")
            if isinstance(content, str):
                return {**msg, "content": self.text(content, tally, edit_target=edit_target)}
            if isinstance(content, list):
                return {
                    **msg,
                    "content": self.parts(content, tally, edit_target=edit_target, types=("text",)),
                }
            return msg

        kind = msg.get("type", "message" if "role" in msg else "")
        if kind == "message":
            role = msg.get("role")
            if role == "assistant":
                return msg
            if role in ("system", "developer") and not settings.gateway_compress_system:
                return msg
            content = msg.get("content")
            if isinstance(content, str):
                return {**msg, "content": self.text(content, tally, edit_target=False)}
            if isinstance(content, list):
                return {
                    **msg,
                    "content": self.parts(
                        content, tally, edit_target=False, types=_TEXT_PART_TYPES
                    ),
                }
            return msg
        if kind in wire.RESPONSES_TOOL_OUTPUTS:
            output = msg.get("output")
            if isinstance(output, str):
                return {**msg, "output": self.text(output, tally, edit_target=True)}
            if isinstance(output, list):
                return {
                    **msg,
                    "output": self.parts(output, tally, edit_target=True, types=_TEXT_PART_TYPES),
                }
        return msg


def _is_assistant(api: str, msg: Any) -> bool:
    if not isinstance(msg, dict):
        return False
    if api == "responses":
        kind = msg.get("type", "message" if "role" in msg else "")
        return (kind == "message" and msg.get("role") == "assistant") or kind in (
            "reasoning",
            "function_call",
            "custom_tool_call",
            "local_shell_call",
        )
    return msg.get("role") == "assistant"


def _shape(api: str, msg: Any) -> list[Any] | None:
    """The shaper instruction at the tail of a new turn, kept in the history.

    Appended as its own block or message after the turn's content, never
    edited into it: the turn is replayed with the instruction on later
    requests, so the history stays append-only and the cache keeps hitting.
    """
    if not isinstance(msg, dict):
        return None
    text = output_shaping.instruction()
    if api == "anthropic":
        if msg.get("role") != "user":
            return None
        content = msg.get("content")
        if isinstance(content, str):
            return [
                {
                    **msg,
                    "content": [{"type": "text", "text": content}, {"type": "text", "text": text}],
                }
            ]
        if isinstance(content, list):
            return [{**msg, "content": [*content, {"type": "text", "text": text}]}]
        return None
    if api == "openai":
        if msg.get("role") not in ("user", "tool", "function"):
            return None
        return [msg, {"role": "system", "content": text}]
    if _is_assistant(api, msg):
        return None
    return [msg, {"type": "message", "role": "developer", "content": text}]


def prepare(
    api: str,
    body: dict[str, Any],
    *,
    compress_text: CompressText,
    oauth: bool = False,
    first_party: bool = False,
    commit: bool = True,
    shape: bool = True,
) -> Prepared:
    """Build the payload to forward. ``commit=False`` is a dry run (count_tokens)."""
    payload = dict(body)
    list_key = "input" if api == "responses" else "messages"
    messages = body.get(list_key)
    info: dict[str, Any] = {}
    if not isinstance(messages, list) or not settings.compression_enabled:
        return Prepared(api, payload, _no_savings())

    raw_tools = body.get("tools")
    tool_list = raw_tools if isinstance(raw_tools, list) else []
    may_touch_tools = bool(tool_list) and (not oauth or settings.gateway_oauth_tool_changes)
    inject = (
        settings.gateway_retrieve_tool
        and may_touch_tools
        and ccr.TOOL_NAME not in ccr.tool_names(api, tool_list)
    )

    if api == "anthropic":
        system_material: Any = body.get("system")
        first = messages[0] if messages else None
    elif api == "openai":
        system_material = None
        first = messages[:2]
    else:
        system_material = body.get("instructions")
        first = messages[0] if messages else None
    key = lineage_key(api, system_material, first, flags=f"r{int(inject)}")

    live = (
        settings.gateway_live_zone
        and not (api == "responses" and body.get("previous_response_id"))
        and bool(messages)
    )
    head = {"system": system_material, "tools": tool_list}
    if live:
        plan = live_zone.plan(api=api, key=key, head=head, messages=messages, body=body)
    else:
        plan = live_zone.plan(api=api, key="", head=head, messages=messages, body=body)
        plan.reuse, plan.groups, plan.cause = 0, [], "off"
    stripped = plan.stripped

    builder = _Builder(api, compress_text, ccr_on=inject)
    index = dedup.DedupIndex(settings.gateway_dedup_min_lines, settings.gateway_dedup_min_chars)
    reuse_counts: list[Counts] = list(plan.sticky.get("counts", []))[: plan.reuse]
    if len(reuse_counts) < plan.reuse:
        reuse_counts += [(0, 0, 0, 0)] * (plan.reuse - len(reuse_counts))

    # Retrieve calls the client saw (and answered with an error, having no
    # such tool): their results get the real original.
    names: dict[str, str] = {}
    retrieve_args: dict[str, dict[str, Any]] = {}
    for msg in stripped:
        for call in wire.tool_calls(api, msg):
            names[call.call_id] = call.name
            if call.name == ccr.TOOL_NAME:
                retrieve_args[call.call_id] = call.args

    shaped = -1
    last = len(stripped) - 1
    groups: list[list[Any]] = []
    expanded: set[int] = set()
    counts: list[Counts] = []
    deduped = 0
    for i, msg in enumerate(stripped):
        if i < plan.reuse:
            group = plan.groups[i]
            count = reuse_counts[i]
        else:
            tally = _Tally()
            group = None
            if _is_assistant(api, msg):
                fp = fingerprint(api, msg)
                real = live_zone.expansion(fp) if fp else None
                if real is not None:
                    group = copy.deepcopy(real)
                    expanded.add(i)
                else:
                    group = [msg]
            else:
                texts = wire.tool_texts(api, msg)
                answered = [t for t in texts if t.call_id in retrieve_args]
                if answered:
                    new = msg
                    for t in answered:
                        new = wire.set_path(new, t.path, ccr.resolve(retrieve_args[t.call_id]))
                    group = [new]
                else:
                    # `gateway_preserve_cache`: only the newest message is
                    # compressed; with the live zone it then stays compressed.
                    keep = settings.gateway_preserve_cache and i != last
                    new = msg if keep else builder.message(msg, tally)
                    if settings.gateway_dedup and not keep:
                        for t in wire.tool_texts(api, new):
                            if t.is_error or t.text.startswith("[sensei: "):
                                continue
                            replaced = index.apply(t.text)
                            if replaced != t.text:
                                before_chars = len(t.text)
                                new = wire.set_path(new, t.path, replaced)
                                saved = max(0, (before_chars - len(replaced)) // 4)
                                tally.add(0, -saved, saved, 0)
                                deduped += saved
                    group = [new]
                    if i == last and shape and settings.output_shaper:
                        shaped = int(output_shaping.assign())
                        if shaped:
                            shaped_group = _shape(api, new)
                            if shaped_group is None:
                                shaped = -1
                            else:
                                group = shaped_group
                                cost = len(output_shaping.instruction()) // 4
                                tally.add(0, cost, -cost, 0)
                                info["shaper_instruction_tokens"] = cost
            count = tally.counts()
        for fm in group:
            for t in wire.tool_texts(api, fm):
                index.add(t.text, f"{names.get(t.call_id, 'tool')} result {t.call_id}".strip())
        groups.append(group)
        counts.append(count)

    # Stale reads: only where rewriting history is free.
    if settings.gateway_stale_reads and plan.frozen < len(stripped):
        groups = _stale_reads(api, stripped, groups, expanded, plan.frozen, names, info)

    if commit and live:
        plan.sticky["counts"] = counts
        live_zone.commit(plan, groups)

    out_messages: list[Any] = []
    for i, group in enumerate(groups):
        marks = plan.marks[i]
        if not marks:
            out_messages.extend(group)
        elif i in expanded:
            out_messages.extend([*group[:-1], apply_cache_control(group[-1], marks)])
        else:
            out_messages.extend([apply_cache_control(group[0], marks), *group[1:]])
    payload[list_key] = out_messages

    total = _Tally()
    for c in counts:
        total.add(*c)

    # System prompt / instructions: compressed as before, deterministic.
    if api == "anthropic" and body.get("system") is not None and settings.gateway_compress_system:
        payload["system"] = _compress_system(builder, body["system"], total)
    elif (
        api == "responses"
        and isinstance(body.get("instructions"), str)
        and settings.gateway_compress_system
    ):
        payload["instructions"] = builder.text(body["instructions"], total, edit_target=False)

    # Tools.
    if may_touch_tools:
        new_tools = list(tool_list)
        if (
            settings.gateway_tool_schema_compaction
            or settings.gateway_tool_description_max_chars > 0
        ):
            new_tools = tools.compact_tools(api, new_tools)
            before_t, after_t = _tokens(tool_list), _tokens(new_tools)
            if before_t > after_t:
                total.add(before_t, after_t, before_t - after_t, 0)
                info["tool_tokens_saved"] = before_t - after_t
        if inject:
            new_tools.append(ccr.tool_definition(api))
        if api == "anthropic":
            new_tools, deferred = tools.apply_tool_search(new_tools, first_party=first_party)
            if deferred:
                info["tools_deferred"] = deferred
                info["deferred_tokens"] = tools.deferred_tokens(new_tools)
        payload["tools"] = new_tools

    if deduped:
        info["dedup_tokens_saved"] = deduped
    savings = _savings(*total.counts()) if (total.before or total.blocks) else _no_savings()
    if info.get("shaper_instruction_tokens"):
        savings["shaper_instruction_tokens"] = info["shaper_instruction_tokens"]
    return Prepared(
        api=api,
        payload=payload,
        savings=savings,
        inject=inject,
        key=key if live else "",
        cause=plan.cause,
        shaped=shaped,
        plan=plan if live else None,
        info=info,
    )


def _compress_system(builder: _Builder, system: Any, tally: _Tally) -> Any:
    if isinstance(system, str):
        return builder.text(system, tally, edit_target=False)
    if isinstance(system, list):
        return builder.parts(system, tally, edit_target=False, types=("text",))
    return system


def _stale_reads(
    api: str,
    stripped: list[Any],
    groups: list[list[Any]],
    expanded: set[int],
    frozen: int,
    names: dict[str, str],
    info: dict[str, Any],
) -> list[list[Any]]:
    """Stub Read results whose file a later, successful write changed."""
    results: dict[str, bool] = {}  # call id -> was an error
    for msg in stripped:
        for t in wire.tool_texts(api, msg):
            results[t.call_id] = results.get(t.call_id, False) or t.is_error
    args_by_id: dict[str, dict[str, Any]] = {}
    writes: dict[str, int] = {}  # file -> last message with a successful write
    for i, msg in enumerate(stripped):
        for call in wire.tool_calls(api, msg):
            args_by_id[call.call_id] = call.args
            path = dedup.file_of(call.args)
            if (
                path
                and call.name.lower() in dedup.WRITE_TOOLS
                and results.get(call.call_id) is False
            ):
                writes[path] = i
    reads: list[tuple[int, str, str]] = []  # (message, call id, file)
    for i, msg in enumerate(stripped):
        for t in wire.tool_texts(api, msg):
            path = dedup.file_of(args_by_id.get(t.call_id, {}))
            if path and not t.is_error and names.get(t.call_id, "").lower() in dedup.READ_TOOLS:
                reads.append((i, t.call_id, path))
    out = list(groups)
    stubs = 0
    for i, call_id, path in reads:
        if i < frozen or i in expanded or len(out[i]) != 1 or writes.get(path, -1) <= i:
            continue
        message = out[i][0]
        for t in wire.tool_texts(api, message):
            if t.call_id == call_id and not t.text.startswith("[sensei: stale Read"):
                original_text = next(
                    (o.text for o in wire.tool_texts(api, stripped[i]) if o.path == t.path), t.text
                )
                message = wire.set_path(message, t.path, dedup.stale_stub(path, original_text))
                stubs += 1
        out[i] = [message]
    if stubs:
        info["stale_reads"] = stubs
    return out
