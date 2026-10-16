import type { ConnectedTool, ToolState } from "@/types";

/** What connecting a tool does, in words. */
const SUPPORT: Record<string, string> = {
  "hook+mcp": "Compression hook + MCP",
  "route+mcp": "Routed + MCP",
  route: "Routed",
  mcp: "MCP tools",
  none: "—",
};

export function supportLabel(support?: string): string {
  return SUPPORT[support ?? ""] ?? support ?? "";
}

/** The row's state, for servers older than the `state` field. */
export function toolState(tool: ConnectedTool): ToolState {
  if (tool.state) return tool.state;
  if (tool.connected) return "connected";
  if (tool.declined) return "declined";
  return tool.installed ? "not-connected" : "not-installed";
}

/** Rows the user can act on first, then the rest, then what cannot be wired. */
export function sortTools(tools: ConnectedTool[]): ConnectedTool[] {
  const rank = (t: ConnectedTool) => {
    const state = toolState(t);
    if (state === "unsupported") return t.installed ? 3 : 4;
    return t.installed || t.connected ? 0 : 2;
  };
  return [...tools].sort((a, b) => rank(a) - rank(b));
}
