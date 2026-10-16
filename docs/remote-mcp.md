# Remote MCP: ChatGPT, claude.ai connectors and Devin cloud

These clients call MCP servers **from the vendor's cloud**. They cannot reach
`127.0.0.1` on your machine and cannot spawn `sensei mcp` locally. To use Sensei
from them, you serve MCP over HTTP and expose **that port, and only that port**
through a tunnel.

> **Warning:** never tunnel the gateway port (7000). The gateway forwards your
> credentials upstream. Claude subscription passthrough means anyone with the
> URL could spend your plan.

## 1. Serve MCP over HTTP, with a token

```bash
sensei mcp --transport streamable-http --port 7001 --allow-host <your-tunnel-hostname>
```

- **Bearer token, always.** Every request must send
  `Authorization: Bearer <token>`. The token is generated on first use and
  stored in `~/.sensei/mcp-token`, readable only by you. You can set your own
  with `SENSEI_MCP_HTTP_TOKEN` instead. Print it with
  `sensei mcp --show-token`. A random tunnel hostname is not a secret: it shows
  up in certificate-transparency logs within minutes.
- **Host allowlist.** Only loopback hosts and the hostnames you pass with
  `--allow-host` are accepted. This is the MCP spec's defence against DNS
  rebinding: a web page whose domain now resolves to `127.0.0.1` still sends
  its own `Host`.
- **No foreign web pages.** A request that carries an `Origin` header must come
  from loopback or from an origin you passed with `--allow-origin`.
- **Read-only by default when exposed.** With `--allow-host`, the proxy tools
  (`sensei_find_tools` / `sensei_call_tool`) are switched off. A remote agent
  hit by prompt injection could otherwise drive every local MCP server you
  listed in `~/.sensei/mcp-servers.json`. Pass `--proxy-tools` only if you mean
  it.
- `--no-auth` is accepted only on loopback, and only without `--allow-host`.

The server binds to `127.0.0.1`. The tunnel connects to it locally.

## 2. Pick a tunnel

| Tunnel | Command | Notes |
|---|---|---|
| **Tailscale Funnel** | `tailscale funnel 7001` | Stable `https://<device>.<tailnet>.ts.net`. TLS ends on your device, so the relay cannot read the traffic. Needs the `funnel` node attribute. |
| **Cloudflare quick tunnel** | `cloudflared tunnel --url http://127.0.0.1:7001` | No account needed. TLS ends at Cloudflare. The quick tunnel has no SSE, so clients that need a stream may fail. Named tunnels add Cloudflare Access. |
| **ngrok** | `ngrok http 7001` | Free tier: 1 dev domain. TLS ends at ngrok. Supports OAuth/IP policies at the edge. |
| **OpenAI Secure MCP Tunnel** (ChatGPT only) | `tunnel-client --mcp-command "sensei mcp"` | Outbound-only, no public URL at all. Needs an OpenAI Platform API key and a tunnel id. Payloads pass through OpenAI. |

Pass the tunnel's hostname to `--allow-host`, for example
`--allow-host mybox.tail1234.ts.net`.

## 3. Add it to the client

- **claude.ai** (Settings → Connectors → Add custom connector): URL
  `https://<tunnel-host>/mcp`, with the header `Authorization: Bearer <token>`.
- **Devin cloud** (MCP marketplace → Add your own → HTTP): the same URL and
  header.
- **ChatGPT** (developer mode connectors): ChatGPT supports OAuth or no auth,
  not a static header. Use the OpenAI Secure MCP Tunnel, which needs no public
  URL. Do not use a public URL with `--no-auth`; Sensei refuses that anyway.

## What a remote client can see

- `sensei_compress` / `sensei_stats`: what was sent to them, and totals.
- `sensei_retrieve`: any stored original whose id the client knows. Ids are
  random UUIDs and expire after `SENSEI_CCR_TTL_HOURS` (default 24).
- Every call goes through the tunnel provider's network. With Cloudflare and
  ngrok they can read it; with Tailscale Funnel they cannot.

Stop the tunnel when you are done.
