import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import { sortTools, supportLabel, toolState } from "@/lib/tools";
import type { ConnectedTool, ToolOutcome, ToolsResponse } from "@/types";
import { Badge, Button, Card, CodeLine, IconButton, Notice, PageHeader } from "@/components/ui";
import { Page } from "@/components/AppShell";

/** Where the gateway answers. In development the UI runs on Vite's port. */
function gatewayOrigin(): string {
  const { origin, port } = window.location;
  return port === "5173" ? "http://localhost:7000" : origin;
}

const MCP_EXAMPLE = `{
  "mcpServers": {
    "rea":    { "command": "npx", "args": ["-y", "rea-agents", "mcp"] },
    "ghidra": { "url": "http://127.0.0.1:8089/mcp" }
  }
}`;

function StatusBadge({ tool }: { tool: ConnectedTool }) {
  const state = toolState(tool);
  if (state === "connected" && tool.needs_restart) return <Badge tone="warning">Restart to apply</Badge>;
  if (state === "connected") return <Badge tone="success">Connected</Badge>;
  if (state === "declined") return <Badge>Left alone</Badge>;
  if (state === "not-connected") return <Badge tone="warning">Not connected</Badge>;
  if (state === "unsupported") return <Badge>Not supported</Badge>;
  return <Badge>Not installed</Badge>;
}

function OutcomeList({ outcomes }: { outcomes: ToolOutcome[] }) {
  const changed = outcomes.filter((o) => o.status === "applied");
  const manual = outcomes.filter((o) => o.status === "manual");
  const failed = outcomes.filter((o) => o.status === "failed");
  if (!changed.length && !manual.length && !failed.length) {
    return <p className="text-xs text-muted">Nothing changed — everything already was that way.</p>;
  }
  return (
    <div className="space-y-2 text-xs text-fg-secondary">
      {changed.length > 0 && (
        <p>
          Changed: {[...new Set(changed.map((o) => o.name))].join(", ")}. Restart those tools if
          they are open.
        </p>
      )}
      {failed.map((o, i) => (
        <p key={`f${i}`} className="text-danger">
          {o.name}: {o.detail}
        </p>
      ))}
      {manual.map((o, i) => (
        <div key={`m${i}`} className="space-y-1">
          <p>
            <span className="font-semibold text-fg">{o.name}</span> needs a manual step: {o.detail}
            {o.path && <span className="font-mono"> ({o.path})</span>}
          </p>
          {o.manual_snippet && (
            <pre className="overflow-x-auto rounded-md border border-line bg-code-bg px-3 py-2 font-mono text-[11px] leading-4 text-fg scrollbar-thin">
              {o.manual_snippet}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

export function ConnectionsPage() {
  const [tools, setTools] = useState<ToolsResponse | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<ToolOutcome[] | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const origin = gatewayOrigin();

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setTools(await api.getTools());
      setError(false);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = useCallback(
    async (key: string, run: () => Promise<{ outcomes: ToolOutcome[] } | unknown>) => {
      setWorking(key);
      setActionError(null);
      try {
        const result = await run();
        const list = (result as { outcomes?: ToolOutcome[] } | undefined)?.outcomes;
        setOutcomes(list ?? null);
      } catch (e) {
        setActionError(e instanceof Error ? e.message : String(e));
      } finally {
        setWorking(null);
        await load();
      }
    },
    [load],
  );

  const rows = sortTools(tools?.tools ?? []);
  const wirable = rows.filter((t) => toolState(t) !== "unsupported");
  const present = wirable.filter((t) => t.installed || t.connected);
  const connected = present.filter((t) => t.connected);
  const restart = connected.filter((t) => t.needs_restart);
  const auto = tools?.auto_connect;

  return (
    <Page>
      <PageHeader
        title="Connections"
        description="The AI tools on this machine, and how each one reaches Sensei."
        actions={
          <IconButton label="Refresh" onClick={() => void load()}>
            <RefreshCw className={clsx("h-4 w-4", busy && "animate-spin")} />
          </IconButton>
        }
      />

      <div className="space-y-4">
        <Card
          title="One switch"
          description="Connect every tool Sensei finds — now, and as you install new ones. Every file is backed up first; disconnecting puts them all back."
        >
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                disabled={working !== null}
                onClick={() => void act("all", () => api.connectAllTools())}
              >
                {working === "all" ? "Connecting…" : "Connect everything"}
              </Button>
              <Button
                variant="danger"
                disabled={working !== null}
                onClick={() => {
                  if (window.confirm("Put every tool's configuration back as it was before Sensei?")) {
                    void act("none", () => api.disconnectAllTools());
                  }
                }}
              >
                {working === "none" ? "Disconnecting…" : "Disconnect everything"}
              </Button>
              {tools && (
                <span className="text-xs text-muted">
                  {connected.length} of {present.length} tools on this machine connected
                </span>
              )}
            </div>

            {auto && (
              <label className="flex items-center gap-2 text-[13px] text-fg-secondary">
                <input
                  type="checkbox"
                  checked={auto.enabled}
                  disabled={auto.setting === false || working !== null}
                  onChange={(e) => void act("auto", () => api.setAutoConnect(e.target.checked))}
                />
                Connect newly installed tools automatically
                {auto.setting === false && <span className="text-xs text-muted">(off in settings: SENSEI_AUTO_CONNECT)</span>}
              </label>
            )}

            {restart.length > 0 && (
              <Notice tone="warning">
                Restart {restart.map((t) => t.name).join(", ")} — {restart.length === 1 ? "it was" : "they were"}{" "}
                running when Sensei changed {restart.length === 1 ? "its" : "their"} configuration.
              </Notice>
            )}
            {actionError && <Notice tone="danger">{actionError}</Notice>}
            {outcomes && <OutcomeList outcomes={outcomes} />}
          </div>
        </Card>

        <Card
          title="Tools on this machine"
          description="Claude Code keeps its own sign-in and Remote Control: Sensei compresses tool output through a hook. Routing its traffic is opt-in."
          padded={false}
          className="overflow-hidden"
        >
          {error && (
            <div className="px-5 pb-5">
              <Notice tone="danger">Could not ask the server which tools are installed.</Notice>
            </div>
          )}
          {tools && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-header-fill">
                    <th className="eyebrow h-8 px-5 text-left text-muted">Tool</th>
                    <th className="eyebrow h-8 px-3 text-left text-muted">How</th>
                    <th className="eyebrow h-8 px-3 text-right text-muted">Status</th>
                    <th className="eyebrow h-8 px-5 text-right text-muted">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((tool) => {
                    const here = tool.installed || tool.connected;
                    const routable = tool.options?.includes("route");
                    const routed = tool.enabled_options?.includes("route") ?? false;
                    return (
                      <tr key={tool.id} className="border-t border-line-subtle align-top transition-colors hover:bg-hover">
                        <td className="px-5 py-2.5">
                          <div className={clsx(here ? "text-fg" : "text-muted")}>
                            {tool.name}
                            {tool.verified === false && tool.state !== "unsupported" && (
                              <span className="ml-1.5 text-[11px] text-muted" title="Format documented, not yet verified end to end">
                                best-effort
                              </span>
                            )}
                          </div>
                          {tool.why && (here || tool.state === "unsupported") && (
                            <div className="mt-0.5 max-w-md text-xs text-muted">
                              {tool.state === "unsupported" ? "" : "No routing: "}
                              {tool.why}
                            </div>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-xs text-fg-secondary">
                          {supportLabel(tool.support)}
                          {routed && " · routed"}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-right">
                          <StatusBadge tool={tool} />
                        </td>
                        <td className="whitespace-nowrap px-5 py-2 text-right">
                          {tool.state !== "unsupported" && here && (
                            <div className="inline-flex gap-1.5">
                              {routable && tool.connected && (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  disabled={working !== null}
                                  title={
                                    tool.id === "claude-code"
                                      ? "Send Claude Code's requests through Sensei. Claude Code turns Remote Control off while routed."
                                      : "Send this tool's model requests through Sensei."
                                  }
                                  onClick={() => void act(`route:${tool.id}`, () => api.setToolRoute(tool.id, !routed))}
                                >
                                  {routed ? "Stop routing" : "Route"}
                                </Button>
                              )}
                              {tool.connected ? (
                                <Button
                                  size="sm"
                                  disabled={working !== null}
                                  onClick={() => void act(`off:${tool.id}`, () => api.disconnectTool(tool.id))}
                                >
                                  Disconnect
                                </Button>
                              ) : (
                                <Button
                                  size="sm"
                                  disabled={working !== null}
                                  onClick={() => void act(`on:${tool.id}`, () => api.connectTool(tool.id))}
                                >
                                  Connect
                                </Button>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="space-y-2 border-t border-line-subtle px-5 py-4 text-xs text-muted">
            <p>The same from a terminal:</p>
            <CodeLine>sensei connect</CodeLine>
            <p>
              <code className="font-mono text-fg-secondary">sensei setup-tools --status</code> explains
              every row; <code className="font-mono text-fg-secondary">sensei disconnect</code> undoes it all.
            </p>
          </div>
        </Card>

        <Card
          title="Gateway addresses"
          description="For anything with a configurable base URL. The tool keeps using its own key."
        >
          <div className="space-y-3">
            <div>
              <p className="eyebrow mb-1.5 text-muted">OpenAI-compatible (Aider, Continue, SDKs)</p>
              <CodeLine>{`${origin}/v1`}</CodeLine>
            </div>
            <div>
              <p className="eyebrow mb-1.5 text-muted">Anthropic (Claude Code, Anthropic SDK)</p>
              <CodeLine>{origin}</CodeLine>
            </div>
            <div>
              <p className="eyebrow mb-1.5 text-muted">Responses API (Codex)</p>
              <CodeLine>{`${origin}/v1  ·  wire_api = "responses"`}</CodeLine>
            </div>
            <div>
              <p className="eyebrow mb-1.5 text-muted">Run one tool through Sensei, no config</p>
              <CodeLine>sensei wrap claude</CodeLine>
            </div>
          </div>
        </Card>

        <Card
          title="MCP"
          description="Sensei is an MCP server — and a proxy for your other MCP servers."
        >
          <div className="space-y-4 text-[13px] leading-5 text-fg-secondary">
            <p>
              Any MCP client can call <code className="font-mono">sensei_compress</code>,{" "}
              <code className="font-mono">sensei_retrieve</code> and{" "}
              <code className="font-mono">sensei_stats</code>. Register it with the command{" "}
              <code className="font-mono text-fg">sensei mcp</code>, or over HTTP (clients must send
              the token from <code className="font-mono">sensei mcp --show-token</code>):
            </p>
            <CodeLine>sensei mcp --transport streamable-http --port 7001</CodeLine>
            <p className="text-xs text-muted">
              ChatGPT, claude.ai connectors and Devin cloud reach it only through a tunnel to port
              7001 — never the gateway port. See docs/remote-mcp.md.
            </p>
            <p>
              List other servers in <code className="font-mono text-fg">~/.sensei/mcp-servers.json</code>{" "}
              (Claude Desktop&rsquo;s format) and the agent sees two tools instead of all of theirs:{" "}
              <code className="font-mono">sensei_find_tools</code> and{" "}
              <code className="font-mono">sensei_call_tool</code>. Results come back compressed, long
              ones in pages — useful for reverse-engineering servers like REA or GhidraMCP, whose
              disassembly listings Sensei shortens by about half.
            </p>
            <pre className="overflow-x-auto rounded-md border border-line bg-code-bg px-4 py-3 font-mono text-[12px] leading-5 text-fg scrollbar-thin">
              {MCP_EXAMPLE}
            </pre>
            <p className="text-xs text-muted">
              Only analyse software you are entitled to: your own builds, binaries you have
              permission to inspect, malware samples in a defensive lab, CTF challenges.
            </p>
          </div>
        </Card>
      </div>
    </Page>
  );
}
