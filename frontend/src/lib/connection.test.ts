import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { probeBackend, watchConnection } from "./connection";

describe("probeBackend", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("is online when /health answers ok", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 200 }));
    expect(await probeBackend()).toBe(true);
  });

  it("is offline when the request throws", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    expect(await probeBackend()).toBe(false);
  });

  it("is offline on a 5xx — a crashing server is not a reachable one", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("", { status: 502 }));
    expect(await probeBackend()).toBe(false);
  });

  it("never reads a cached health response", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 200 }));
    await probeBackend();
    expect(fetch).toHaveBeenCalledWith("/health", expect.objectContaining({ cache: "no-store" }));
  });
});

describe("watchConnection", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  /** Run the scheduled callback immediately, capped so a failing test can't hang. */
  function immediateScheduler(maxTicks: number) {
    let ticks = 0;
    const setTimeoutFn = ((fn: () => void) => {
      if (ticks++ < maxTicks) queueMicrotask(fn);
      return 0 as unknown as ReturnType<typeof setTimeout>;
    }) as unknown as typeof setTimeout;
    return { setTimeoutFn, clearTimeoutFn: (() => {}) as unknown as typeof clearTimeout };
  }

  it("reports offline when the backend is down", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("down"));
    const seen: string[] = [];
    const stop = watchConnection((s) => seen.push(s), immediateScheduler(0));

    await vi.waitFor(() => expect(seen).toContain("offline"));
    stop();
  });

  it("only reports transitions, not every poll", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 200 }));
    const seen: string[] = [];
    const stop = watchConnection((s) => seen.push(s), immediateScheduler(5));

    await vi.waitFor(() => expect(seen.length).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 20));
    stop();

    // Six successful probes, one "online" — a banner that flickers on every
    // poll would be worse than no banner.
    expect(seen).toEqual(["online"]);
  });

  it("reports recovery after the server comes back", async () => {
    vi.mocked(fetch)
      .mockRejectedValueOnce(new TypeError("down"))
      .mockResolvedValue(new Response("{}", { status: 200 }));

    const seen: string[] = [];
    const stop = watchConnection((s) => seen.push(s), immediateScheduler(3));

    await vi.waitFor(() => expect(seen).toEqual(["offline", "online"]));
    stop();
  });

  it("stops probing once unsubscribed", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 200 }));
    const stop = watchConnection(() => {}, immediateScheduler(0));
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());

    stop();
    const callsAtStop = vi.mocked(fetch).mock.calls.length;
    await new Promise((r) => setTimeout(r, 20));
    expect(vi.mocked(fetch).mock.calls.length).toBe(callsAtStop);
  });
});
