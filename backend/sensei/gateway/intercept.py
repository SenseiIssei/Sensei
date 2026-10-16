"""Answering ``sensei_retrieve`` inside the gateway — opt-in.

**The default** (``gateway_retrieve_intercept=false``) hides nothing: the call
goes to the client, the client answers an unknown tool with an error result,
and on the next request the gateway swaps that result for the real original
(see :mod:`.pipeline`). The swap is stored per conversation (:mod:`.state`), so
every later request forwards the same text, across restarts too. One extra
round trip, and the history the provider sees is exactly the one it produced.

**With interception on**, when the model calls the retrieve tool — and only
that tool — the gateway resolves the call, appends the exchange to the request
and asks the provider again; the client receives one response. Rounds are
capped by ``gateway_retrieve_max_rounds``. Follow-ups go through redaction and
the block-list like any request.

**When it is never hidden**: the model called a client tool in the same turn
(before or after ours), the response carries thinking or reasoning (it is bound
to the prefix that produced it), the round cap was hit, policy refused the
follow-up, the follow-up failed, or the format is a stream we do not splice
(Responses). The call then goes to the client as above.

**What the client stores, and what the provider sees next turn.** The client
records the merged message it was shown. The gateway files the real sequence
(assistant call, tool result, assistant answer) under the conversation, the
credential and the exact history before it, on disk, and puts it back in place
on the next request — so a reply that happens to look the same elsewhere is
never expanded.

**Usage.** The ledger records every round, because every round is billed. The
response the client sees keeps the final round's input figures — what the
context now holds, which is what clients use to decide when to compact — and
the output tokens of all rounds together; ``X-Sensei-Retrieve-Rounds`` and the
``sensei.retrieve`` block say how many hidden rounds there were.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import anyio
import httpx

from sensei.config import settings
from sensei.gateway import ccr
from sensei.gateway.session import THINKING_TYPES, digest
from sensei.gateway.state import state
from sensei.usage import Usage, UsageSniffer, from_response

logger = logging.getLogger(__name__)

Send = Callable[[dict[str, Any]], Awaitable[httpx.Response | None]]
# (payload) -> (payload as it may be sent, reason it may not)
Policy = Callable[[dict[str, Any]], tuple[dict[str, Any], str | None]]
THINKING = THINKING_TYPES


def add_usage(total: Usage, part: Usage) -> None:
    total.prompt += part.prompt
    total.output += part.output
    total.cache_read += part.cache_read
    total.cache_write += part.cache_write


# ── Fingerprints of what the client will send back ──────────────────────────


def fingerprint(api: str, message: Any) -> str | None:
    """A key for an assistant message that survives client re-serialisation.

    Clients rebuild the message from the response and may drop null fields or
    reorder keys, so this keys on what identifies it: text, thinking
    signatures, tool-call ids.
    """
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    if api == "anthropic":
        content = message.get("content")
        if not isinstance(content, list):
            return None
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                parts.append(("text", block.get("text", "")))
            elif kind in THINKING:
                parts.append((kind, block.get("signature") or block.get("data") or ""))
            elif kind in ("tool_use", "server_tool_use"):
                parts.append((kind, block.get("id", "")))
            else:
                parts.append((str(kind), ""))
        return digest(["a", parts]) if parts else None
    if api == "openai":
        ids = [c.get("id", "") for c in message.get("tool_calls") or [] if isinstance(c, dict)]
        return digest(["o", message.get("content") or "", ids])
    return None


def expansion_key(prefix: str, fp: str) -> str:
    """Where an expansion is filed: the history before it, plus the message.

    The history digest makes it positional: the same "Done." at two places in
    one conversation, or in two conversations, are different keys.
    """
    return digest([prefix, fp])


# ── SSE plumbing ────────────────────────────────────────────────────────────


class SSEParser:
    """Split a byte stream into complete events, without altering them."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        events = []
        while True:
            cut = -1
            size = 0
            for sep in (b"\n\n", b"\r\n\r\n"):
                at = self._buf.find(sep)
                if at >= 0 and (cut < 0 or at < cut):
                    cut, size = at, len(sep)
            if cut < 0:
                return events
            events.append(self._buf[: cut + size])
            self._buf = self._buf[cut + size :]

    def close(self) -> bytes:
        rest, self._buf = self._buf, b""
        return rest


def parse_event(raw: bytes) -> tuple[str, Any]:
    name = ""
    data_lines = []
    for line in raw.splitlines():
        if line.startswith(b"event:"):
            name = line[6:].strip().decode("utf-8", "replace")
        elif line.startswith(b"data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return name, None
    data = b"\n".join(data_lines)
    if data == b"[DONE]":
        return name, "[DONE]"
    try:
        return name, json.loads(data)
    except ValueError:
        return name, None


def build_event(name: str, data: Any) -> bytes:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    head = f"event: {name}\n" if name else ""
    return f"{head}data: {body}\n\n".encode()


# ── Anthropic block reconstruction from stream deltas ───────────────────────


def _apply_delta(block: dict[str, Any], event: dict[str, Any]) -> None:
    if event.get("type") == "content_block_stop":
        if "_json" in block:
            raw = block.pop("_json")
            try:
                block["input"] = json.loads(raw) if raw else {}
            except ValueError:
                block["input"] = {}
        return
    delta = event.get("delta") or {}
    kind = delta.get("type")
    if kind == "text_delta":
        block["text"] = block.get("text", "") + delta.get("text", "")
    elif kind == "thinking_delta":
        block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
    elif kind == "signature_delta":
        block["signature"] = delta.get("signature", "")
    elif kind == "input_json_delta":
        block["_json"] = block.get("_json", "") + delta.get("partial_json", "")
    elif kind == "citations_delta":
        block.setdefault("citations", []).append(delta.get("citation"))


def _final(block: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in block.items() if k != "_json"}
    if "_json" in block:
        try:
            out["input"] = json.loads(block["_json"]) if block["_json"] else {}
        except ValueError:
            out["input"] = {}
    return out


def _remap(raw: bytes, name: str, data: dict[str, Any], index: int) -> bytes:
    """The event with its content-block index changed; untouched if unchanged."""
    if data.get("index") == index:
        return raw
    return build_event(name, {**data, "index": index})


def _same_id(raw: bytes, data: Any, first_id: str | None) -> bytes:
    """A follow-up round's chunk under the first round's completion id."""
    if first_id and isinstance(data, dict) and data.get("id") != first_id:
        return build_event("", {**data, "id": first_id})
    return raw


class Retriever:
    """One request's retrieve interception."""

    def __init__(
        self,
        api: str,
        payload: dict[str, Any],
        send: Send,
        *,
        policy: Policy | None = None,
        scope: str = "",
        prefix: str = "",
    ) -> None:
        self.api = api
        self.payload = payload
        self.send = send
        self.policy = policy
        # Expansions are only ever found again inside the same conversation,
        # for the same credential, after the same history.
        self.scope = scope
        self.prefix = prefix
        self.rounds = 0
        self.usage = Usage()
        self._live_sniff: UsageSniffer | None = None
        self._open: list[httpx.Response] = []

    async def aclose(self) -> None:
        """Close every upstream response this request opened, whatever happened."""
        for resp in self._open:
            with anyio.CancelScope(shield=True):
                try:
                    await resp.aclose()
                except Exception as exc:
                    logger.debug("follow-up response did not close cleanly: %s", exc)
        self._open.clear()

    def usage_so_far(self) -> Usage:
        total = copy.copy(self.usage)
        if self._live_sniff is not None:
            add_usage(total, self._live_sniff.close())
            self._live_sniff = None
        return total

    def _next_payload(self, hidden: list[dict[str, Any]], *, stream: bool) -> dict[str, Any]:
        key = "input" if self.api == "responses" else "messages"
        out = {**self.payload, key: [*self.payload.get(key, []), *hidden]}
        out["stream"] = stream
        if stream and self.api == "openai" and "stream_options" in self.payload:
            out["stream_options"] = self.payload["stream_options"]
        return out

    def _round(
        self, hidden: list[dict[str, Any]], *, stream: bool
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        """The follow-up request, through redaction and the block-list.

        Returns it with the hidden messages as they will actually be sent (and
        remembered), or None when policy refuses it; the call then goes to the
        client instead.
        """
        payload = self._next_payload(hidden, stream=stream)
        if self.policy is not None:
            payload, reason = self.policy(payload)
            if reason:
                logger.info("Not answering sensei_retrieve server-side: %s", reason)
                return None
        key = "input" if self.api == "responses" else "messages"
        base = len(self.payload.get(key, []))
        return payload, list(payload.get(key, []))[base:]

    async def _send_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        resp = await self.send(payload)
        if resp is None:
            return None
        try:
            if resp.status_code != 200:
                return None
            raw = await resp.aread()
        except httpx.HTTPError:
            return None
        finally:
            await resp.aclose()
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    # ---- complete (non-streaming) responses --------------------------------

    async def complete(self, data: dict[str, Any]) -> dict[str, Any]:
        self.usage = from_response(data)
        if self.api == "anthropic":
            return await self._complete_anthropic(data)
        if self.api == "openai":
            return await self._complete_chat(data)
        return await self._complete_responses(data)

    async def _complete_anthropic(self, data: dict[str, Any]) -> dict[str, Any]:
        hidden: list[dict[str, Any]] = []
        visible: list[Any] = []
        current = data
        while self.rounds < settings.gateway_retrieve_max_rounds:
            content = current.get("content") or []
            uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            ours = [b for b in uses if b.get("name") == ccr.TOOL_NAME]
            if not ours or len(ours) != len(uses) or current.get("stop_reason") != "tool_use":
                break
            if any(isinstance(b, dict) and b.get("type") in THINKING for b in content):
                break  # thinking binds the prefix that produced it: never hide one
            round_hidden = [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": b.get("id"),
                            "content": ccr.resolve(b.get("input")),
                        }
                        for b in ours
                    ],
                },
            ]
            prepared = self._round(hidden + round_hidden, stream=False)
            following = await self._send_json(prepared[0]) if prepared else None
            if following is None or prepared is None:
                break
            visible.extend(self._visible_blocks(content))
            hidden = prepared[1]
            add_usage(self.usage, from_response(following))
            current = following
            self.rounds += 1
        if not self.rounds:
            return data
        final_content = current.get("content") or []
        visible.extend(self._visible_blocks(final_content, keep_ours=True))
        merged = {**current, "content": visible}
        merged["usage"] = {**(current.get("usage") or {}), "output_tokens": self.usage.output}
        self._remember(
            {"role": "assistant", "content": visible},
            [*hidden, {"role": "assistant", "content": final_content}],
        )
        return merged

    def _visible_blocks(self, content: list[Any], keep_ours: bool = False) -> list[Any]:
        out = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if (
                block.get("type") == "tool_use"
                and block.get("name") == ccr.TOOL_NAME
                and not keep_ours
            ):
                continue
            # Thinking after the first round was produced from a prefix that
            # includes the hidden exchange; the client could not replay it.
            if self.rounds and block.get("type") in THINKING:
                continue
            out.append(block)
        return out

    async def _complete_chat(self, data: dict[str, Any]) -> dict[str, Any]:
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            return data
        hidden: list[dict[str, Any]] = []
        text = ""
        current = data
        while self.rounds < settings.gateway_retrieve_max_rounds:
            choice = (current.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            calls = [c for c in message.get("tool_calls") or [] if isinstance(c, dict)]
            ours = [c for c in calls if (c.get("function") or {}).get("name") == ccr.TOOL_NAME]
            if not ours or len(ours) != len(calls) or choice.get("finish_reason") != "tool_calls":
                break
            if message.get("reasoning_content") or message.get("reasoning"):
                break
            round_hidden = [
                {k: v for k, v in message.items() if k in ("role", "content", "tool_calls")},
                *(
                    {
                        "role": "tool",
                        "tool_call_id": c.get("id"),
                        "content": ccr.resolve((c.get("function") or {}).get("arguments")),
                    }
                    for c in ours
                ),
            ]
            prepared = self._round(hidden + round_hidden, stream=False)
            following = await self._send_json(prepared[0]) if prepared else None
            if following is None or prepared is None or not following.get("choices"):
                break
            text += message.get("content") or ""
            hidden = prepared[1]
            add_usage(self.usage, from_response(following))
            current = following
            self.rounds += 1
        if not self.rounds:
            return data
        choice = dict(current["choices"][0])
        final = dict(choice.get("message") or {})
        visible = {**final, "content": (text + (final.get("content") or "")) or None}
        choice["message"] = visible
        merged = {**current, "choices": [choice]}
        usage = dict(current.get("usage") or {})
        if usage:
            usage["completion_tokens"] = self.usage.output
            merged["usage"] = usage
        self._remember(
            {
                "role": "assistant",
                "content": visible.get("content"),
                "tool_calls": final.get("tool_calls"),
            },
            [*hidden, {k: v for k, v in final.items() if k in ("role", "content", "tool_calls")}],
        )
        return merged

    async def _complete_responses(self, data: dict[str, Any]) -> dict[str, Any]:
        hidden: list[dict[str, Any]] = []
        visible: list[Any] = []
        current = data
        while self.rounds < settings.gateway_retrieve_max_rounds:
            output = [o for o in current.get("output") or [] if isinstance(o, dict)]
            calls = [o for o in output if o.get("type", "").endswith("_call")]
            ours = [
                o
                for o in calls
                if o.get("type") == "function_call" and o.get("name") == ccr.TOOL_NAME
            ]
            if not ours or len(ours) != len(calls):
                break
            # A reasoning item belongs with the call that follows it; the
            # merged output could not keep one without the other.
            if any(o.get("type") == "reasoning" for o in output):
                break
            round_hidden = [
                *({k: v for k, v in o.items() if k != "status"} for o in output),
                *(
                    {
                        "type": "function_call_output",
                        "call_id": o.get("call_id"),
                        "output": ccr.resolve(o.get("arguments")),
                    }
                    for o in ours
                ),
            ]
            prepared = self._round(hidden + round_hidden, stream=False)
            following = await self._send_json(prepared[0]) if prepared else None
            if following is None or prepared is None:
                break
            visible.extend(o for o in output if o not in ours)
            hidden = prepared[1]
            add_usage(self.usage, from_response(following))
            current = following
            self.rounds += 1
        if not self.rounds:
            return data
        merged = {**current, "output": visible + list(current.get("output") or [])}
        usage = dict(current.get("usage") or {})
        if usage:
            usage["output_tokens"] = self.usage.output
            merged["usage"] = usage
        return merged

    def _remember(self, visible: dict[str, Any], real: list[dict[str, Any]]) -> None:
        fp = fingerprint(self.api, visible)
        if fp is not None and self.scope:
            state.put(self.scope, "expansion", expansion_key(self.prefix, fp), real)

    # ---- streams -----------------------------------------------------------

    async def _open_stream(self, payload: dict[str, Any]) -> httpx.Response | None:
        resp = await self.send(payload)
        if resp is None:
            return None
        self._open.append(resp)
        if resp.status_code != 200 or "event-stream" not in resp.headers.get("content-type", ""):
            await resp.aclose()
            return None
        return resp

    async def stream(self, first: httpx.Response) -> AsyncIterator[bytes]:
        if self.api == "anthropic":
            async for chunk in self._stream_anthropic(first):
                yield chunk
        elif self.api == "openai":
            async for chunk in self._stream_chat(first):
                yield chunk
        else:  # not spliced: the client sees the call, the next turn answers it
            sniff = self._live_sniff = UsageSniffer()
            try:
                async for chunk in first.aiter_bytes():
                    sniff.feed(chunk)
                    yield chunk
            finally:
                with anyio.CancelScope(shield=True):
                    await first.aclose()

    async def _events(self, resp: httpx.Response) -> AsyncIterator[tuple[bytes, str, Any]]:
        parser = SSEParser()
        sniff = self._live_sniff = UsageSniffer()
        try:
            async for chunk in resp.aiter_bytes():
                sniff.feed(chunk)
                for raw in parser.feed(chunk):
                    name, data = parse_event(raw)
                    yield raw, name, data
            rest = parser.close()
            if rest.strip():
                name, data = parse_event(rest)
                yield rest, name, data
        except httpx.HTTPError as err:
            logger.warning("Upstream stream broke off: %s", err)
        finally:
            add_usage(self.usage, sniff.close())
            self._live_sniff = None
            with anyio.CancelScope(shield=True):
                await resp.aclose()

    async def _stream_anthropic(self, first: httpx.Response) -> AsyncIterator[bytes]:
        resp: httpx.Response | None = first
        next_client = 0
        hidden: list[dict[str, Any]] = []
        visible: list[dict[str, Any]] = []
        last_content: list[dict[str, Any]] = []
        while resp is not None:
            blocks: dict[int, dict[str, Any]] = {}
            order: list[int] = []
            mapping: dict[int, int] = {}
            ours: set[int] = set()
            skipped: set[int] = set()
            held: list[tuple[int | None, bytes, str, Any]] = []
            tail: list[tuple[bytes, str, Any]] = []
            holding = foreign = thought = False
            stop_reason = None

            async for raw, name, data in self._events(resp):
                if not isinstance(data, dict):
                    if holding:
                        held.append((None, raw, name, data))
                    else:
                        yield raw
                    continue
                kind = data.get("type", name)
                if kind == "message_start":
                    if not self.rounds:
                        yield raw
                    continue
                if kind == "content_block_start":
                    idx = data.get("index")
                    block = data.get("content_block") or {}
                    if not isinstance(idx, int):
                        yield raw
                        continue
                    blocks[idx] = copy.deepcopy(block)
                    order.append(idx)
                    btype = block.get("type")
                    if btype in THINKING:
                        thought = True
                    elif btype in ("tool_use", "server_tool_use") and (
                        block.get("name") != ccr.TOOL_NAME
                    ):
                        foreign = True  # a client tool, before or after ours
                    if btype == "tool_use" and block.get("name") == ccr.TOOL_NAME:
                        ours.add(idx)
                        holding = True
                        held.append((idx, raw, name, data))
                        continue
                    if self.rounds and btype in THINKING:
                        skipped.add(idx)
                        continue
                    if holding:
                        held.append((idx, raw, name, data))
                        continue
                    mapping[idx] = next_client
                    next_client += 1
                    yield _remap(raw, name, data, mapping[idx])
                    continue
                if kind in ("content_block_delta", "content_block_stop"):
                    idx = data.get("index")
                    if isinstance(idx, int) and idx in blocks:
                        _apply_delta(blocks[idx], data)
                    if idx in skipped:
                        continue
                    if idx in mapping:
                        yield _remap(raw, name, data, mapping[idx])
                    elif holding:
                        held.append((idx, raw, name, data))
                    else:
                        yield raw
                    continue
                if kind == "message_delta":
                    stop_reason = (data.get("delta") or {}).get("stop_reason")
                    tail.append((raw, name, data))
                    continue
                if kind == "message_stop":
                    tail.append((raw, name, data))
                    continue
                if holding:
                    held.append((None, raw, name, data))
                else:
                    yield raw

            content = [_final(blocks[i]) for i in order]
            following = None
            if (
                ours
                and not foreign
                and not thought
                and stop_reason == "tool_use"
                and self.rounds < settings.gateway_retrieve_max_rounds
            ):
                round_hidden = [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": blocks[i].get("id"),
                                "content": ccr.resolve(_final(blocks[i]).get("input")),
                            }
                            for i in order
                            if i in ours
                        ],
                    },
                ]
                prepared = self._round(hidden + round_hidden, stream=True)
                if prepared is not None:
                    following = await self._open_stream(prepared[0])
                    if following is not None:
                        hidden = prepared[1]

            for idx, raw, name, data in held:
                if idx is None:
                    yield raw
                    continue
                if following is not None and idx in ours:
                    continue
                if idx not in mapping:
                    mapping[idx] = next_client
                    next_client += 1
                yield _remap(raw, name, data, mapping[idx])
            visible.extend(_final(blocks[i]) for i in order if i in mapping)
            last_content = content

            if following is not None:
                self.rounds += 1
                resp = following
                continue

            for raw, name, data in tail:
                if self.rounds and data.get("type") == "message_delta":
                    usage = {
                        **(data.get("usage") or {}),
                        "output_tokens": self.usage_so_far().output,
                    }
                    yield build_event(name, {**data, "usage": usage})
                else:
                    yield raw
            resp = None

        if self.rounds:
            self._remember(
                {"role": "assistant", "content": visible},
                [*hidden, {"role": "assistant", "content": last_content}],
            )

    async def _stream_chat(self, first: httpx.Response) -> AsyncIterator[bytes]:
        resp: httpx.Response | None = first
        hidden: list[dict[str, Any]] = []
        first_id: str | None = None
        text_all = ""
        last_message: dict[str, Any] = {}
        while resp is not None:
            calls: dict[int, dict[str, Any]] = {}
            ours: set[int] = set()
            client_tools = holding = thought = False
            held: list[tuple[bytes, Any]] = []
            tail: list[tuple[bytes, Any]] = []
            text = ""
            finish = None

            async for raw, _name, data in self._events(resp):
                if data == "[DONE]" or not isinstance(data, dict):
                    tail.append((raw, data))
                    continue
                if first_id is None:
                    first_id = data.get("id")
                choices = data.get("choices") or []
                if not choices:  # the usage chunk
                    tail.append((raw, data))
                    continue
                choice = choices[0] if isinstance(choices[0], dict) else {}
                delta = choice.get("delta") or {}
                chunk_calls = [c for c in delta.get("tool_calls") or [] if isinstance(c, dict)]
                for call in chunk_calls:
                    idx = call.get("index", 0)
                    entry = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    fn = call.get("function") or {}
                    entry["id"] = call.get("id") or entry["id"]
                    entry["name"] = fn.get("name") or entry["name"]
                    entry["arguments"] += fn.get("arguments") or ""
                    if entry["name"] == ccr.TOOL_NAME:
                        ours.add(idx)
                        holding = True
                    elif entry["name"]:
                        client_tools = True
                text += delta.get("content") or ""
                if delta.get("reasoning_content") or delta.get("reasoning"):
                    thought = True
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                    tail.append((raw, data))
                    continue
                if holding:
                    held.append((raw, data))
                else:
                    yield _same_id(raw, data, first_id if self.rounds else None)

            following = None
            if (
                ours
                and not client_tools
                and not thought
                and finish == "tool_calls"
                and self.rounds < settings.gateway_retrieve_max_rounds
            ):
                ours_calls = [calls[i] for i in sorted(ours)]
                round_hidden = [
                    {
                        "role": "assistant",
                        "content": text or None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {"name": c["name"], "arguments": c["arguments"]},
                            }
                            for c in ours_calls
                        ],
                    },
                    *(
                        {
                            "role": "tool",
                            "tool_call_id": c["id"],
                            "content": ccr.resolve(c["arguments"]),
                        }
                        for c in ours_calls
                    ),
                ]
                prepared = self._round(hidden + round_hidden, stream=True)
                if prepared is not None:
                    following = await self._open_stream(prepared[0])
                    if following is not None:
                        hidden = prepared[1]

            for raw, data in held:
                delta = ((data.get("choices") or [{}])[0] or {}).get("delta") or {}
                only_ours = delta.get("tool_calls") and all(
                    c.get("index", 0) in ours for c in delta["tool_calls"] if isinstance(c, dict)
                )
                if following is not None and only_ours and not delta.get("content"):
                    continue
                yield _same_id(raw, data, first_id if self.rounds else None)
            text_all += text

            if following is not None:
                self.rounds += 1
                resp = following
                continue

            for raw, data in tail:
                if self.rounds and isinstance(data, dict) and isinstance(data.get("usage"), dict):
                    usage = {**data["usage"], "completion_tokens": self.usage_so_far().output}
                    yield build_event(
                        "", {**data, "id": first_id or data.get("id"), "usage": usage}
                    )
                else:
                    yield _same_id(raw, data, first_id if self.rounds else None)
            last_message = {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for _, c in sorted(calls.items())
                ]
                or None,
            }
            resp = None

        if self.rounds:
            visible = {
                "role": "assistant",
                "content": text_all or None,
                "tool_calls": last_message.get("tool_calls"),
            }
            real_last = {k: v for k, v in last_message.items() if v is not None}
            self._remember(visible, [*hidden, real_last])
