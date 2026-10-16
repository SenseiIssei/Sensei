import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ConnectionsPage } from "./ConnectionsPage";
import { sortTools, supportLabel, toolState } from "@/lib/tools";
import type { ConnectedTool, ToolsResponse } from "@/types";

const TOOLS: ToolsResponse = {
  tools: [
    {
      id: "chatgpt",
      name: "ChatGPT (web and desktop)",
      installed: false,
      connected: false,
      declined: false,
      support: "none",
      why: "remote MCP only — needs a tunnel and a token",
      options: [],
      enabled_options: [],
      needs_restart: false,
      state: "unsupported",
    },
    {
      id: "claude-code",
      name: "Claude Code",
      installed: true,
      connected: true,
      declined: false,
      support: "hook+mcp",
      why: "",
      options: ["route"],
      enabled_options: [],
      needs_restart: false,
      state: "connected",
    },
    {
      id: "claude-desktop",
      name: "Claude Desktop",
      installed: true,
      connected: true,
      declined: false,
      support: "mcp",
      why: "chat traffic goes to Anthropic directly",
      options: [],
      enabled_options: [],
      needs_restart: true,
      state: "connected",
    },
    {
      id: "cursor",
      name: "Cursor",
      installed: true,
      connected: false,
      declined: false,
      support: "mcp",
      options: [],
      enabled_options: [],
      state: "not-connected",
    },
  ],
  auto_connect: {
    enabled: true,
    choice: null,
    setting: true,
    running: true,
    interval_seconds: 30,
    scans: 3,
    connected_since_start: [],
    last_error: null,
  },
};

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/setup/tools") && !init?.method) return json(TOOLS);
    return json({
      outcomes: [
        { id: "cursor", name: "Cursor", status: "applied", detail: "", path: "/x", manual_snippet: "" },
      ],
    });
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("ConnectionsPage", () => {
  it("shows every tool, how it is connected, and what to restart", async () => {
    render(<ConnectionsPage />);
    expect(await screen.findByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText("Compression hook + MCP")).toBeInTheDocument();
    expect(screen.getByText("Not supported")).toBeInTheDocument();
    expect(screen.getByText("Restart to apply")).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 tools on this machine connected/)).toBeInTheDocument();
    expect(screen.getByText(/Restart Claude Desktop/)).toBeInTheDocument();
  });

  it("connects everything with one click and reports what changed", async () => {
    render(<ConnectionsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect everything" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/setup/tools/connect",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText(/Changed: Cursor/)).toBeInTheDocument();
  });

  it("offers routing only where the tool has the option", async () => {
    render(<ConnectionsPage />);
    await screen.findByText("Claude Code");
    const route = screen.getAllByRole("button", { name: "Route" });
    expect(route).toHaveLength(1);
    fireEvent.click(route[0]);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/setup/tools/claude-code/route",
        expect.objectContaining({ method: "PUT", body: JSON.stringify({ enabled: true }) }),
      ),
    );
  });
});

describe("tool helpers", () => {
  it("puts tools you have first and unsupported ones last", () => {
    const ids = sortTools(TOOLS.tools).map((t) => t.id);
    expect(ids[ids.length - 1]).toBe("chatgpt");
    expect(ids.slice(0, 3).sort()).toEqual(["claude-code", "claude-desktop", "cursor"]);
  });

  it("derives a state from an older server's rows", () => {
    const old: ConnectedTool = { id: "x", name: "X", installed: true, connected: false, declined: true };
    expect(toolState(old)).toBe("declined");
    expect(supportLabel("hook+mcp")).toBe("Compression hook + MCP");
  });
});
