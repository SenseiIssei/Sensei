import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SavingsDashboard } from "./SavingsDashboard";
import type { SavingsResponse } from "@/types";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function totals(over: Partial<SavingsResponse["lifetime"]> = {}) {
  return {
    requests: 0,
    tokens_before: 0,
    tokens_after: 0,
    tokens_saved: 0,
    blocks_compressed: 0,
    compression_ratio: 1,
    percent_saved: 0,
    estimated_cost_saved_usd: 0,
    price_per_million_usd: 3,
    since: 0,
    ...over,
  };
}

function response(over: Partial<SavingsResponse> = {}): SavingsResponse {
  return {
    session: totals(),
    lifetime: totals(),
    daily: [],
    by_tool: [],
    by_provider: [],
    by_model: [],
    persisted: true,
    price_per_million_usd: 3,
    ...over,
  };
}

function reply(body: SavingsResponse) {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
}

describe("SavingsDashboard", () => {
  it("shows the lifetime total, not just this session", async () => {
    reply(
      response({
        lifetime: totals({
          requests: 412,
          tokens_before: 5_000_000,
          tokens_saved: 4_000_000,
          percent_saved: 80,
          estimated_cost_saved_usd: 12,
        }),
        session: totals({ requests: 3, tokens_saved: 1000 }),
      })
    );

    render(<SavingsDashboard onOpenChat={() => {}} onOpenSettings={() => {}} />);

    expect(await screen.findByText("4.00M")).toBeInTheDocument();
    expect(screen.getByText("$12.00")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    // The session number is present too, but as the smaller of the two.
    expect(screen.getByText("1.0k")).toBeInTheDocument();
  });

  it("tells you what to run when nothing has gone through yet", async () => {
    reply(response());
    render(<SavingsDashboard onOpenChat={() => {}} onOpenSettings={() => {}} />);

    expect(await screen.findByText(/No requests have gone through yet/)).toBeInTheDocument();
    expect(screen.getByText("sensei setup-tools")).toBeInTheDocument();
  });

  it("shows a real sub-cent figure rather than rounding it to nothing", async () => {
    // "$0.00" reads as "this feature does nothing"; the honest number is small.
    reply(
      response({
        lifetime: totals({ requests: 1, tokens_saved: 900, estimated_cost_saved_usd: 0.0027 }),
      })
    );
    render(<SavingsDashboard onOpenChat={() => {}} onOpenSettings={() => {}} />);

    expect(await screen.findByText("$0.0027")).toBeInTheDocument();
  });

  it("says so when history is turned off, instead of silently under-reporting", async () => {
    reply(response({ persisted: false, lifetime: totals({ requests: 5 }) }));
    render(<SavingsDashboard onOpenChat={() => {}} onOpenSettings={() => {}} />);

    expect(await screen.findByText(/SENSEI_SAVINGS_PERSIST=false/)).toBeInTheDocument();
  });

  it("requires a second click before deleting history", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    reply(response({ lifetime: totals({ requests: 9 }) }));
    render(<SavingsDashboard onOpenChat={() => {}} onOpenSettings={() => {}} />);

    const button = await screen.findByRole("button", { name: /Delete history/ });
    const callsBefore = vi.mocked(fetch).mock.calls.length;

    await user.click(button);
    // First click only arms it — nothing has been sent.
    expect(vi.mocked(fetch).mock.calls.length).toBe(callsBefore);
    expect(screen.getByRole("button", { name: /cannot be undone/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /cannot be undone/ }));
    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("savings/forget"))
      ).toBe(true)
    );
  });

  it("shows the interval, not just the headline percentage", async () => {
    reply(
      response({
        lifetime: totals({ requests: 400 }),
        output_effect: {
          enabled: true,
          holdout: 0.1,
          verdict: "shorter answers",
          shaped: { requests: 360, mean_output_tokens: 280 },
          control: { requests: 40, mean_output_tokens: 400 },
          difference_tokens: 120,
          percent: 30,
          confidence_interval_95: [90, 150],
          percent_interval_95: [22.5, 37.5],
        },
      })
    );
    render(<SavingsDashboard onOpenChat={() => {}} onOpenSettings={() => {}} />);

    expect(await screen.findByText(/22.5%/)).toBeInTheDocument();
    expect(screen.getByText(/37.5%/)).toBeInTheDocument();
    expect(screen.getByText(/shorter answers/)).toBeInTheDocument();
  });

  it("refuses to show a percentage it cannot support", async () => {
    // The failure this prevents: a confident-looking number computed from
    // eleven requests, which is what gets screenshotted and quoted.
    reply(
      response({
        lifetime: totals({ requests: 22 }),
        output_effect: {
          enabled: true,
          holdout: 0.1,
          verdict: "not enough data yet",
          detail: "19 more request(s) needed in the smaller arm.",
          shaped: { requests: 11, mean_output_tokens: 280 },
          control: { requests: 11, mean_output_tokens: 400 },
        },
      })
    );
    render(<SavingsDashboard onOpenChat={() => {}} onOpenSettings={() => {}} />);

    expect(await screen.findByText("Not enough data yet.")).toBeInTheDocument();
    expect(screen.getByText(/19 more request/)).toBeInTheDocument();
    expect(screen.queryByText(/95% confident/)).not.toBeInTheDocument();
  });

  it("hides the panel entirely when shaping is off", async () => {
    reply(response({ lifetime: totals({ requests: 9 }) }));
    render(<SavingsDashboard onOpenChat={() => {}} onOpenSettings={() => {}} />);

    await screen.findByText("Tokens saved");
    expect(screen.queryByText("Output shaping")).not.toBeInTheDocument();
  });

  it("reports an unreachable backend instead of showing zeroes", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    render(<SavingsDashboard onOpenChat={() => {}} onOpenSettings={() => {}} />);

    expect(await screen.findByText(/Is the server running/)).toBeInTheDocument();
    // Zeroes would be a lie — they would read as "you have saved nothing".
    expect(screen.queryByText("Tokens saved")).not.toBeInTheDocument();
  });
});
