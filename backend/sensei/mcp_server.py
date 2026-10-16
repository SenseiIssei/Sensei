"""MCP server — Sensei's compression as tools any MCP client can call.

The gateway only helps tools that let you point a base URL somewhere else.
Plenty don't, and an agent frequently wants to compress a specific blob rather
than route its whole conversation. This exposes the pipeline directly:

    sensei_compress   shrink a piece of text, get an id back
    sensei_retrieve   get the original back by that id
    sensei_stats      what compression has saved so far

`sensei_retrieve` is what makes the whole thing safe to use. Compression is
never a one-way door: if a model decides it needs the untouched text, it asks
for it. An agent that cannot recover the original is an agent that has to
guess, which is worse than sending more tokens.

Requires the optional MCP extra (bundled in the release binaries; from a
checkout: pip install -e "backend[mcp]").
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from sensei import __version__
from sensei.compression.ccr import CCRStore
from sensei.compression.router import ContentRouter, ContentType
from sensei.config import settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
Sensei compresses text before it reaches a model, typically removing 60-95% of
the tokens in JSON, logs and tool output.

Use `sensei_compress` on anything large you are about to include in context —
command output, file dumps, API responses, build logs. It returns the compressed
text plus a `ccr_id`.

If the compressed form turns out to be missing something you need, call
`sensei_retrieve` with that `ccr_id` to get the exact original back. Do that
rather than guessing or asking the user to paste it again.
"""

# Built once — ContentRouter compiles patterns and, when present, loads the
# Rust accelerator. Rebuilding it per call would dominate the cost of a small
# compression.
_router: ContentRouter | None = None
_store: CCRStore | None = None


def _pipeline() -> tuple[ContentRouter, CCRStore]:
    global _router, _store
    if _router is None or _store is None:
        _store = CCRStore()
        _router = ContentRouter(ccr_store=_store, enable_caching=True)
    return _router, _store


def _lookup(ccr_id: str, *, compressed: bool = False) -> str | None:
    """Find a stored text, including one stored after this process started.

    The store's index is read from disk once, when it is built. This process
    is spawned by an editor and lives for the whole session, while the ids it
    is asked about are minted elsewhere — by the gateway, or by the tool-output
    hook in the server process — after it started. Without a second look every
    one of those came back "no entry", and the retrieve hint attached to a
    compressed output pointed at nothing.
    """
    global _store
    router, store = _pipeline()
    text = store.retrieve_compressed(ccr_id) if compressed else store.retrieve(ccr_id)
    if text is None:
        # Re-read the index; the router keeps its compiled state.
        _store = store = CCRStore(cache_dir=store.cache_dir)
        router.ccr_store = store
        text = store.retrieve_compressed(ccr_id) if compressed else store.retrieve(ccr_id)
    return text


def _page(text: str, offset: int, limit: int) -> tuple[str, int | None]:
    """One page of ``text`` from ``offset``, cut at a line break when possible.

    Returns the page and the offset of the next one (None at the end).
    """
    offset = max(0, offset)
    limit = max(1, limit)
    end = offset + limit
    if end >= len(text):
        return text[offset:], None
    # Prefer a line break in the second half of the page; the next offset is
    # always past this one, so paging can never stand still.
    cut = text.rfind("\n", offset + limit // 2, end)
    if cut >= offset:
        end = cut + 1
    return text[offset:end], end


PROXY_INSTRUCTIONS = """

Other MCP servers are available through Sensei: call `sensei_find_tools` with a
few keywords to find a tool and its input schema, then `sensei_call_tool` to run
it. Results come back compressed; when one is too long it arrives as a first
page with a ccr_id. Page on with `sensei_retrieve(ccr_id, offset=…,
view="compressed")`, or fetch the exact original with `view="original"`.
"""


def build_server(hub: Any | None = None) -> Any:
    """Construct the MCP server. Imported lazily so `mcp` stays optional.

    ``hub`` is a :class:`sensei.mcp_proxy.ProxyHub`; when it is omitted the
    configured servers file is read, and with no servers configured the proxy
    tools are simply not offered.
    """
    # The MCP Python SDK renamed FastMCP to MCPServer and moved it from
    # `mcp.server.fastmcp` to `mcp.server.mcpserver` in 2.0. The constructor and
    # the `.tool()` decorator are unchanged, so supporting both is two imports
    # rather than two code paths. Try the current name first: on an SDK that has
    # both, the new one is the one being maintained.
    server_class = None
    try:
        from mcp.server.mcpserver import MCPServer as server_class
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as server_class
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise RuntimeError(
                "The MCP server needs the optional 'mcp' extra:\n    pip install -e \"backend[mcp]\"   (the release binaries include it)"
            ) from exc

    if hub is None:
        from sensei.mcp_proxy import ProxyHub

        hub = ProxyHub.from_config()
    proxying = bool(hub.servers)

    mcp = server_class(
        name="sensei", instructions=INSTRUCTIONS + (PROXY_INSTRUCTIONS if proxying else "")
    )

    @mcp.tool(
        name="sensei_compress",
        description=(
            "Compress text before putting it in context. Best on JSON, logs and "
            "tool output, where it typically removes 60-95% of tokens without "
            "losing information. Returns the compressed text and a ccr_id that "
            "sensei_retrieve can exchange for the exact original."
        ),
    )
    def sensei_compress(text: str, content_type: str | None = None) -> str:
        """Compress a block of text.

        Args:
            text: the content to compress.
            content_type: force a compressor instead of detecting one —
                json, code, logs or text. Leave unset unless detection is wrong.
        """
        if not text:
            return json.dumps({"error": "nothing to compress"})

        router, _ = _pipeline()

        forced: ContentType | None = None
        if content_type:
            try:
                forced = ContentType(content_type.lower())
            except ValueError:
                valid = ", ".join(t.value for t in ContentType)
                return json.dumps(
                    {"error": f"unknown content_type {content_type!r}; use one of: {valid}"}
                )

        result = router.compress(text, force_type=forced)

        # Record it, exactly as the gateway does for a proxied request.
        #
        # This did not happen, and the omission was invisible in the worst way:
        # compression worked, the caller got its shorter text, and the dashboard
        # kept showing the number from before. For a tool the user cannot route
        # through the gateway — Claude Code's desktop app pins its own endpoint,
        # so MCP is the only path there is — that meant every token saved went
        # unreported, in the one product whose promise is showing you the total.
        from sensei.savings import get_savings_tracker

        get_savings_tracker().record(
            {
                "prompt_tokens_before": result.original_tokens,
                "prompt_tokens_after": result.compressed_tokens,
                "tokens_saved": result.tokens_saved,
                "blocks_compressed": 1,
            },
            tool="MCP",
        )

        return json.dumps(
            {
                "compressed": result.compressed,
                "ccr_id": result.ccr_id,
                "content_type": result.content_type.value,
                "original_tokens": result.original_tokens,
                "compressed_tokens": result.compressed_tokens,
                "tokens_saved": result.tokens_saved,
                "percent_saved": round((1 - result.ratio) * 100, 1),
            }
        )

    @mcp.tool(
        name="sensei_retrieve",
        description=(
            "Get back the exact original text for a ccr_id returned by "
            "sensei_compress or sensei_call_tool. Use this whenever the "
            "compressed form seems to be missing something you need — never "
            "guess at what was removed. Long texts can be read in pages with "
            "offset and max_chars."
        ),
    )
    def sensei_retrieve(
        ccr_id: str,
        offset: int = 0,
        max_chars: int | None = None,
        view: str = "original",
    ) -> str:
        """Retrieve a stored text by its CCR id.

        Args:
            ccr_id: the id from sensei_compress or sensei_call_tool.
            offset: character offset to start from (for paging).
            max_chars: page size; omit to get everything from offset on.
            view: "original" (exact bytes) or "compressed" (the shorter form).
        """
        text = _lookup(ccr_id, compressed=view == "compressed")
        if text is None:
            return json.dumps(
                {
                    "error": f"no entry for {ccr_id!r}",
                    "hint": (
                        "Entries expire after SENSEI_CCR_TTL_HOURS (default 24) "
                        "and are dropped when the cache is purged."
                    ),
                }
            )
        if max_chars is not None and max_chars <= 0:
            return json.dumps({"error": "max_chars must be a positive number"})
        if not offset and max_chars is None:
            return text
        page, next_offset = _page(text, offset, max_chars or len(text))
        if next_offset is None:
            return page
        return (
            f"{page}\n[sensei: {next_offset:,} of {len(text):,} chars shown. Continue with "
            f'sensei_retrieve(ccr_id="{ccr_id}", offset={next_offset}, view="{view}")]'
        )

    @mcp.tool(
        name="sensei_stats",
        description="How many tokens Sensei has saved, and the estimated cost avoided.",
    )
    def sensei_stats() -> str:
        """Current compression totals."""
        from sensei.savings import get_savings_tracker

        _, store = _pipeline()
        return json.dumps(
            {
                "version": __version__,
                "savings": get_savings_tracker().snapshot(),
                "ccr_cache": store.stats(),
            }
        )

    if proxying:
        _add_proxy_tools(mcp, hub)

    return mcp


def _add_proxy_tools(mcp: Any, hub: Any) -> None:
    from sensei.mcp_proxy import result_text

    @mcp.tool(
        name="sensei_find_tools",
        description=(
            "Search the tools of the MCP servers connected through Sensei. Give a "
            "few keywords (e.g. 'decompile function', 'list strings'); get back "
            "the matching tools with their input schemas. With no query, lists "
            "every server and tool name."
        ),
    )
    async def sensei_find_tools(query: str = "", server: str = "", limit: int = 8) -> str:
        """Find tools by keyword.

        Args:
            query: keywords describing what you want to do.
            server: restrict to one server name.
            limit: how many matches to return.
        """
        found = await hub.find(query, server or None, limit)
        return json.dumps(found, ensure_ascii=False)

    @mcp.tool(
        name="sensei_call_tool",
        description=(
            "Call a tool on one of the MCP servers connected through Sensei (find "
            "it first with sensei_find_tools). The result is compressed; a long "
            "one arrives as a first page plus a ccr_id for sensei_retrieve."
        ),
    )
    async def sensei_call_tool(
        server: str, tool: str, arguments: dict[str, Any] | None = None
    ) -> str:
        """Call a proxied tool.

        Args:
            server: the server name, as listed by sensei_find_tools.
            tool: the tool name on that server.
            arguments: the tool's arguments, matching its input schema.
        """
        try:
            result = await hub.call(server, tool, arguments or {})
        except KeyError:
            return json.dumps(
                {"error": f"unknown server {server!r}", "servers": sorted(hub.servers)}
            )
        except Exception as exc:
            return json.dumps({"error": f"{server}.{tool} failed: {exc}"})
        return _shrink_result(hub, server, *result_text(result))


def _shrink_result(hub: Any, server: str, text: str, is_error: bool) -> str:
    """Compress a proxied tool result and page it if it is still too long."""
    if is_error or len(text) < 100:
        return text

    router, store = _pipeline()
    # Code from a filesystem-style server may be edited next by exact match,
    # so it stays byte-exact unless the server opts in with "compressCode".
    spec = hub.servers.get(server)
    edit_safe = not (isinstance(spec, dict) and spec.get("compressCode"))
    result = router.compress(text, edit_target=edit_safe)

    from sensei.savings import get_savings_tracker

    get_savings_tracker().record(
        {
            "prompt_tokens_before": result.original_tokens,
            "prompt_tokens_after": result.compressed_tokens,
            "tokens_saved": result.tokens_saved,
            "blocks_compressed": 1,
        },
        tool=f"MCP:{server}"[:64],
    )

    view = result.compressed
    page_size = max(1000, settings.mcp_page_chars)
    ccr_id = result.ccr_id
    if len(view) <= page_size:
        if ccr_id:
            view += (
                f"\n[sensei: {result.original_tokens:,} → {result.compressed_tokens:,} tokens. "
                f'Exact original: sensei_retrieve(ccr_id="{ccr_id}")]'
            )
        return view
    if ccr_id is None:
        ccr_id = store.store(text, view, result.content_type.value)
    page, next_offset = _page(view, 0, page_size)
    return (
        f"{page}\n[sensei: {next_offset:,} of {len(view):,} chars shown "
        f"(compressed from {len(text):,}). Next page: "
        f'sensei_retrieve(ccr_id="{ccr_id}", offset={next_offset}, view="compressed"). '
        f'Exact original: sensei_retrieve(ccr_id="{ccr_id}", view="original")]'
    )


# ── HTTP transports: who may connect ────────────────────────────────────────

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _token_path() -> Any:
    from sensei.config import SENSEI_HOME

    return SENSEI_HOME / "mcp-token"


def http_token(*, create: bool = True) -> str | None:
    """The bearer token remote MCP clients must send.

    From SENSEI_MCP_HTTP_TOKEN when set, otherwise generated once and kept in
    ~/.sensei/mcp-token, readable only by its owner. A random tunnel hostname
    is not a secret — it shows up in certificate-transparency logs within
    minutes — so the token is what actually keeps strangers out.
    """
    import os
    import secrets

    if settings.mcp_http_token:
        return settings.mcp_http_token
    path = _token_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing or not create:
        return existing or None
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")
    return token


def _host_only(value: str) -> str:
    """`example.com:443` → `example.com`; `[::1]:7001` → `[::1]`."""
    value = value.strip().lower()
    if value.startswith("["):
        return value.split("]", 1)[0] + "]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class Guard:
    """ASGI wrapper: bearer token, Host allowlist, no foreign web pages.

    * **Token** — every HTTP request needs ``Authorization: Bearer <token>``,
      compared in constant time. ``--no-auth`` is accepted only on loopback.
    * **Host** — the Host header must be loopback or a hostname the user named
      with ``--allow-host`` (the tunnel's). That is the MCP spec's defence
      against DNS rebinding: a page on evil.example that re-resolves its own
      name to 127.0.0.1 still sends ``Host: evil.example``.
    * **Origin** — when a browser sends one, it must be loopback or allowed.
      Non-browser clients send none and are judged by the token alone.
    """

    def __init__(
        self,
        app: Any,
        *,
        token: str | None,
        allow_hosts: tuple[str, ...] = (),
        allow_origins: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.token = token
        self.hosts = {*_LOOPBACK_HOSTS, *(_host_only(h) for h in allow_hosts)}
        self.origins = {o.rstrip("/").lower() for o in allow_origins}

    def _origin_ok(self, origin: str) -> bool:
        from urllib.parse import urlparse

        if origin.rstrip("/").lower() in self.origins:
            return True
        host = (urlparse(origin).hostname or "").lower()
        return host in ("127.0.0.1", "localhost", "::1")

    def _problem(self, headers: dict[str, str]) -> tuple[int, str] | None:
        import hmac

        if _host_only(headers.get("host", "")) not in self.hosts:
            return 421, "unknown Host — add it with --allow-host"
        if headers.get("origin") and not self._origin_ok(headers["origin"]):
            return 403, "cross-origin requests are not allowed"
        if self.token is not None:
            scheme, _, value = headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(
                value.strip().encode(), self.token.encode()
            ):
                return 401, "missing or wrong bearer token"
        return None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        problem = self._problem(headers)
        if problem is None:
            await self.app(scope, receive, send)
            return
        status, detail = problem
        body = json.dumps({"error": detail}).encode()
        extra = [(b"www-authenticate", b'Bearer realm="sensei"')] if status == 401 else []
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    *extra,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _is_loopback_bind(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def http_app(
    transport: str = "streamable-http",
    host: str = "127.0.0.1",
    *,
    token: str | None,
    allow_hosts: tuple[str, ...] = (),
    allow_origins: tuple[str, ...] = (),
    proxy_tools: bool = True,
) -> Any:
    """The guarded ASGI app for an HTTP transport. Separate from run() for tests."""
    hub = None
    if not proxy_tools:
        from sensei.mcp_proxy import ProxyHub

        hub = ProxyHub(servers={})
    server = build_server(hub)

    from mcp.server.transport_security import TransportSecuritySettings

    # Guard checks Host and Origin first; the SDK's own check would reject
    # every tunnel hostname, so it is told about the same allowlist.
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            *(_host_only(h) for h in allow_hosts),
            *(f"{_host_only(h)}:*" for h in allow_hosts),
        ],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", *allow_origins],
    )
    if transport == "sse":
        inner = server.sse_app(transport_security=security, host=host)
    else:
        inner = server.streamable_http_app(transport_security=security, host=host)
    return Guard(inner, token=token, allow_hosts=allow_hosts, allow_origins=allow_origins)


def run(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 7001,
    *,
    no_auth: bool = False,
    allow_hosts: tuple[str, ...] = (),
    allow_origins: tuple[str, ...] = (),
    proxy_tools: bool | None = None,
    show_token: bool = False,
) -> int:
    """Run the MCP server. Blocks until the client disconnects (stdio) or ^C."""
    # stdio is the transport MCP clients spawn a server with, so anything
    # written to stdout that isn't a protocol message corrupts the stream.
    logging.basicConfig(level=logging.WARNING)
    if show_token:
        print(http_token() or "")
        return 0
    if transport == "stdio":
        build_server().run(transport="stdio")
        return 0

    exposed = bool(allow_hosts) or not _is_loopback_bind(host)
    if no_auth and exposed:
        print(
            "Refusing --no-auth on anything reachable from another machine. Drop "
            "--no-auth and give the client the token (sensei mcp --show-token).",
            file=sys.stderr,
        )
        return 2

    # Exposed through a tunnel, the proxy tools would let a remote agent drive
    # every local MCP server in mcp-servers.json — a filesystem server included.
    # Off for remote use unless asked for by name.
    with_proxy = proxy_tools if proxy_tools is not None else not exposed
    token = None if no_auth else http_token()
    app = http_app(
        transport,
        host,
        token=token,
        allow_hosts=allow_hosts,
        allow_origins=allow_origins,
        proxy_tools=with_proxy,
    )

    import uvicorn

    path = "/sse" if transport == "sse" else "/mcp"
    print(f"Sensei MCP ({transport}) on http://{host}:{port}{path}", file=sys.stderr)
    if token:
        where = "SENSEI_MCP_HTTP_TOKEN" if settings.mcp_http_token else str(_token_path())
        print(
            f"Clients must send 'Authorization: Bearer <token>' (token in {where}; "
            "print it with: sensei mcp --show-token)",
            file=sys.stderr,
        )
    if not with_proxy:
        print("Proxy tools (sensei_find_tools / sensei_call_tool) are off.", file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
