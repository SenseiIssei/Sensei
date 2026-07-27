import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConnectionBanner } from "./ConnectionBanner";

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
afterEach(() => vi.unstubAllGlobals());

describe("ConnectionBanner", () => {
  it("stays out of the way while the backend is reachable", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 200 }));
    render(<ConnectionBanner />);

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says what to run when the backend is down", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    render(<ConnectionBanner />);

    const banner = await screen.findByRole("status");
    // The point of the banner is the fix, not the diagnosis.
    expect(banner).toHaveTextContent("sensei up");
    expect(banner).toHaveTextContent("sensei doctor");
  });

  it("renders nothing before the first probe resolves", () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {}));
    render(<ConnectionBanner />);
    // "checking" must not flash an alarming banner on every page load.
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
