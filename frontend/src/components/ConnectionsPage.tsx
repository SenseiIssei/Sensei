import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { ToolsResponse } from "@/types";
import { Badge, Card, CodeLine, IconButton, Notice, PageHeader } from "@/components/ui";
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

export function ConnectionsPage() {
  const [tools, setTools] = useState<ToolsResponse | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
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

  const installed = tools?.tools.filter((t) => t.installed || t.connected) ?? [];
  const others = tools?.tools.filter((t) => !t.installed && !t.connected) ?? [];

  return (
    <Page>
      <PageHeader
        title="Connections"
        description="The AI tools on this machine, and the addresses they use to reach Sensei."
        actions={
          <IconButton label="Refresh" onClick={() => void load()}>
            <RefreshCw className={clsx("h-4 w-4", busy && "animate-spin")} />
          </IconButton>
        }
      />

      <div className="space-y-4">
        <Card
          title="Tools on this machine"
          description="Connected tools send their prompts through the gateway and keep their own sign-in."
          padded={false}
          className="overflow-hidden"
        >
          {error && (
            <div className="px-5 pb-5">
              <Notice tone="danger">Could not ask the server which tools are installed.</Notice>
            </div>
          )}
          {tools && (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-header-fill">
                  <th className="eyebrow h-8 px-5 text-left text-muted">Tool</th>
                  <th className="eyebrow h-8 px-5 text-right text-muted">Status</th>
                </tr>
              </thead>
              <tbody>
                {[...installed, ...others].map((tool) => (
                  <tr
                    key={tool.id}
                    className="h-11 border-t border-line-subtle transition-colors hover:bg-hover"
                  >
                    <td className={clsx("px-5", tool.installed || tool.connected ? "text-fg" : "text-muted")}>
                      {tool.name}
                    </td>
                    <td className="px-5 text-right">
                      {tool.connected ? (
                        <Badge tone="success">Connected</Badge>
                      ) : tool.declined ? (
                        <Badge>Left alone</Badge>
                      ) : tool.installed ? (
                        <Badge tone="warning">Not connected</Badge>
                      ) : (
                        <Badge>Not installed</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="space-y-2 border-t border-line-subtle px-5 py-4 text-xs text-muted">
            <p>
              Connect everything at once — every file is backed up first and shown before it
              changes:
            </p>
            <CodeLine>sensei setup-tools</CodeLine>
            <p>
              Undo it with <code className="font-mono text-fg-secondary">sensei setup-tools --undo</code>.
              {tools?.auto_connect.enabled &&
                " Tools installed later are connected automatically while Sensei runs."}
            </p>
          </div>
        </Card>

        <Card
          title="Gateway addresses"
          description="For anything with a configurable base URL. The tool keeps using its own key."
        >
          <div className="space-y-3">
            <div>
              <p className="eyebrow mb-1.5 text-muted">OpenAI-compatible (Cursor, Aider, Continue, SDKs)</p>
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
              <code className="font-mono text-fg">sensei mcp</code>, or over HTTP:
            </p>
            <CodeLine>sensei mcp --transport streamable-http --port 7001</CodeLine>
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
