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

Requires the optional MCP extra:  pip install "sensei-gateway[mcp]"
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sensei import __version__
from sensei.compression.ccr import CCRStore
from sensei.compression.router import ContentRouter, ContentType

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


def build_server() -> Any:
    """Construct the MCP server. Imported lazily so `mcp` stays optional."""
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
                "The MCP server needs the optional 'mcp' extra:\n    pip install \"sensei-gateway[mcp]\""
            ) from exc

    mcp = server_class(name="sensei", instructions=INSTRUCTIONS)

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
            "sensei_compress. Use this whenever the compressed form seems to be "
            "missing something you need — never guess at what was removed."
        ),
    )
    def sensei_retrieve(ccr_id: str) -> str:
        """Retrieve an original by its CCR id."""
        _, store = _pipeline()
        original = store.retrieve(ccr_id)
        if original is None:
            return json.dumps(
                {
                    "error": f"no entry for {ccr_id!r}",
                    "hint": (
                        "Entries expire after SENSEI_CCR_TTL_HOURS (default 24) "
                        "and are dropped when the cache is purged."
                    ),
                }
            )
        return original

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

    return mcp


def run(transport: str = "stdio") -> int:
    """Run the MCP server. Blocks until the client disconnects."""
    # stdio is the transport MCP clients spawn a server with, so anything
    # written to stdout that isn't a protocol message corrupts the stream.
    logging.basicConfig(level=logging.WARNING)
    build_server().run(transport=transport)  # type: ignore[arg-type]
    return 0
