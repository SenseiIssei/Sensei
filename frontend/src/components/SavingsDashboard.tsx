import { useCallback, useEffect, useMemo, useState } from "react";
import { MessageSquare, RefreshCw, SlidersHorizontal, Trash2, TrendingDown, Zap } from "lucide-react";
import { api } from "@/lib/api";
import type { OutputEffect, SavingsDay, SavingsResponse, SavingsSlice } from "@/types";

/**
 * "How much have I actually saved?"
 *
 * Styled to match Odysync — same palette, same JetBrains Mono, same glow and
 * gradient-edge vocabulary — because they are the same person's tools and
 * should read as one family. Green keeps its meaning throughout: it is the
 * colour of a saving, never decoration. Cyan is chrome.
 *
 * The charts are hand-drawn SVG rather than a charting library: the frontend
 * has a 450 kB JavaScript budget enforced in CI, and every library worth using
 * costs more than that budget has to spare for two charts.
 */

// ── formatting ──────────────────────────────────────────────────────────────

function formatTokens(n: number): string {
  const sign = n < 0 ? "-" : "";
  const v = Math.abs(n);
  if (v >= 1_000_000_000) return `${sign}${(v / 1_000_000_000).toFixed(2)}B`;
  if (v >= 1_000_000) return `${sign}${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${sign}${(v / 1_000).toFixed(1)}k`;
  return `${sign}${v}`;
}

function formatMoney(usd: number): string {
  // Below a cent, a rounded "$0.00" reads as "this does nothing". Show the
  // real number instead and let it be small.
  if (Math.abs(usd) > 0 && Math.abs(usd) < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function formatDay(iso: string): string {
  const [, month, day] = iso.split("-");
  return `${day}.${month}.`;
}

// ── pieces ──────────────────────────────────────────────────────────────────

function Stat({
  label,
  value,
  sub,
  tone = "plain",
  delay = 0,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "plain" | "saving" | "cyan";
  delay?: number;
}) {
  const valueClass =
    tone === "saving"
      ? "text-sensei-400 text-glow-green"
      : tone === "cyan"
        ? "text-[--color-accent] text-glow-cyan"
        : "text-cyber-text";

  return (
    <div
      className="gradient-border animate-in-up p-4"
      style={{ animationDelay: `${delay}ms` }}
    >
      <p className="text-[0.65rem] uppercase tracking-[0.14em] text-cyber-faint">{label}</p>
      <p className={`mt-1.5 text-3xl font-bold tabular-nums leading-none ${valueClass}`}>
        {value}
      </p>
      {sub && <p className="mt-2 text-xs text-cyber-dim">{sub}</p>}
    </div>
  );
}

function Panel({
  title,
  aside,
  children,
  className = "",
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`cyber-panel animate-in-up p-4 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium tracking-wide text-cyber-text">{title}</h2>
        {aside && <span className="text-xs text-cyber-faint">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

function DailyChart({ days }: { days: SavingsDay[] }) {
  const peak = Math.max(...days.map((d) => d.tokens_saved), 1);
  const width = 760;
  const height = 170;
  const gap = 3;
  const barWidth = Math.max(1, width / days.length - gap);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height + 24}`}
        className="h-52 w-full min-w-[560px]"
        role="img"
        aria-label={`Tokens saved per day over the last ${days.length} days`}
      >
        <defs>
          <linearGradient id="barFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.95" />
            <stop offset="100%" stopColor="#00f0ff" stopOpacity="0.35" />
          </linearGradient>
        </defs>

        {/* Four gridlines, matching the 24px grid of the page background. */}
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line
            key={f}
            x1={0}
            x2={width}
            y1={height - height * f}
            y2={height - height * f}
            stroke="#1e1e2a"
            strokeWidth="1"
          />
        ))}

        {days.map((day, i) => {
          const barHeight = (day.tokens_saved / peak) * height;
          const x = i * (barWidth + gap);
          const active = day.tokens_saved > 0;
          // A zero day still gets a hairline, so idle days read as "nothing
          // happened" rather than as missing data.
          const h = active ? Math.max(barHeight, 3) : 1;
          return (
            <g key={day.date}>
              <rect
                x={x}
                y={height - h}
                width={barWidth}
                height={h}
                rx={2}
                fill={active ? "url(#barFill)" : "#1e1e2a"}
              >
                <title>
                  {day.date}: {formatTokens(day.tokens_saved)} tokens saved over {day.requests}{" "}
                  request{day.requests === 1 ? "" : "s"} ({formatMoney(day.estimated_cost_saved_usd)}
                  )
                </title>
              </rect>
              {i % 7 === 0 && (
                <text
                  x={x + barWidth / 2}
                  y={height + 17}
                  textAnchor="middle"
                  className="fill-cyber-faint text-[10px]"
                >
                  {formatDay(day.date)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: SavingsSlice[] }) {
  const peak = Math.max(...rows.map((r) => r.tokens_saved), 1);
  return (
    <Panel title={title}>
      {rows.length === 0 ? (
        <p className="text-xs text-cyber-faint">Nothing recorded yet.</p>
      ) : (
        <ul className="space-y-2.5">
          {rows.map((row) => (
            <li key={row.key}>
              <div className="flex items-baseline justify-between gap-2 text-xs">
                <span className="truncate text-cyber-text">{row.key}</span>
                <span className="shrink-0 tabular-nums text-cyber-dim">
                  {formatTokens(row.tokens_saved)} · {row.percent_saved}%
                </span>
              </div>
              <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-cyber-border">
                <div
                  className="h-1 rounded-full bg-gradient-to-r from-sensei-500 to-[--color-accent]"
                  style={{ width: `${(row.tokens_saved / peak) * 100}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/**
 * The output-shaping experiment.
 *
 * Renders the interval before the number, and renders "not enough data yet" as
 * the whole panel rather than showing a zero next to it. A dashboard that puts
 * a confident-looking percentage on eleven samples is worse than one that
 * shows nothing, because the percentage gets screenshotted.
 */
function OutputShaping({ effect }: { effect: OutputEffect }) {
  const interval = effect.percent_interval_95;
  const inconclusive = !interval;

  return (
    <Panel
      title="Output shaping"
      aside={`${Math.round(effect.holdout * 100)}% held back as a control`}
    >
      {inconclusive ? (
        <>
          <p className="text-sm text-cyber-text">Not enough data yet.</p>
          <p className="mt-1 text-xs text-cyber-faint">{effect.detail}</p>
        </>
      ) : (
        <>
          <p className="text-xs text-cyber-faint">95% confident the change is between</p>
          <p className="mt-1 font-bold tabular-nums leading-none">
            <span className="text-2xl text-[--color-accent] text-glow-cyan">{interval[0]}%</span>
            <span className="mx-2 text-sm font-normal text-cyber-faint">and</span>
            <span className="text-2xl text-[--color-accent] text-glow-cyan">{interval[1]}%</span>
          </p>
          <p className="mt-2 text-xs text-cyber-dim">
            Best estimate {effect.percent}% ({effect.difference_tokens} tokens per answer) ·{" "}
            <span
              className={
                effect.verdict === "shorter answers"
                  ? "text-sensei-400"
                  : effect.verdict === "longer answers"
                    ? "text-red-400"
                    : "text-cyber-faint"
              }
            >
              {effect.verdict}
            </span>
          </p>
        </>
      )}

      <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-cyber-border pt-3 text-xs">
        <div>
          <dt className="text-cyber-faint">Shaped</dt>
          <dd className="tabular-nums text-cyber-text">
            {effect.shaped.requests.toLocaleString()} · {effect.shaped.mean_output_tokens} tok/answer
          </dd>
        </div>
        <div>
          <dt className="text-cyber-faint">Control</dt>
          <dd className="tabular-nums text-cyber-text">
            {effect.control.requests.toLocaleString()} · {effect.control.mean_output_tokens}{" "}
            tok/answer
          </dd>
        </div>
      </dl>

      <p className="mt-3 text-xs text-cyber-faint">
        Non-streaming responses only — a streamed reply reports no usage block, so it cannot be
        counted without parsing the stream.
      </p>
    </Panel>
  );
}

// ── page ────────────────────────────────────────────────────────────────────

export function SavingsDashboard({
  needsSetup = false,
  onOpenChat,
  onOpenSettings,
}: {
  needsSetup?: boolean;
  onOpenChat: () => void;
  onOpenSettings: () => void;
}) {
  const [data, setData] = useState<SavingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(false);
  const [confirmingForget, setConfirmingForget] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api.getSavings());
      setError(null);
    } catch {
      setError("Sensei isn't answering. Is the server running?");
    } finally {
      setBusy(false);
    }
  }, []);

  // Live, over Server-Sent Events. The page used to poll every fifteen
  // seconds, so a number whose whole job is to show what is happening could be
  // a quarter of a minute out of date.
  //
  // The one-shot fetch still runs first: EventSource gives no data until the
  // server sends its first event, and an empty dashboard while the stream
  // connects looks like a broken one.
  useEffect(() => {
    load();

    let source: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;

    try {
      source = new EventSource("/api/stats/savings/stream");
      source.addEventListener("savings", (event) => {
        try {
          setData(JSON.parse((event as MessageEvent).data));
          setError(null);
          setLive(true);
        } catch {
          // A malformed frame is not worth tearing the stream down for.
        }
      });
      source.addEventListener("open", () => setLive(true));
      source.addEventListener("error", () => {
        // EventSource reconnects on its own, so this is "not connected right
        // now" rather than "give up". Poll while it is down so the page keeps
        // moving, and stop once it comes back.
        setLive(false);
        if (!poll) poll = setInterval(load, 15_000);
      });
    } catch {
      // No EventSource at all — fall back to what the page did before.
      poll = setInterval(load, 15_000);
    }

    return () => {
      source?.close();
      if (poll) clearInterval(poll);
    };
  }, [load]);

  const handleForget = useCallback(async () => {
    if (!confirmingForget) {
      setConfirmingForget(true);
      return;
    }
    await api.forgetSavings().catch(() => undefined);
    setConfirmingForget(false);
    load();
  }, [confirmingForget, load]);

  const lifetime = data?.lifetime;
  const session = data?.session;

  const perDay = useMemo(() => {
    if (!data) return 0;
    const active = data.daily.filter((d) => d.requests > 0).length;
    return active ? data.lifetime.estimated_cost_saved_usd / active : 0;
  }, [data]);

  return (
    <div className="grid-bg flex h-dvh w-full flex-col overflow-y-auto bg-cyber-bg">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-cyber-border bg-cyber-bg/85 px-4 py-3 backdrop-blur">
        <div className="flex-1">
          <h1 className="flex items-center gap-2 font-bold tracking-wide text-cyber-text">
            <Zap className="h-4 w-4 text-[--color-accent]" />
            SAVINGS
            {/* Says whether the stream is actually connected, rather than
                decorating the page with a "live" badge that is always on. */}
            <span
              title={live ? "Streaming live" : "Stream not connected — polling instead"}
              className={
                "flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[0.6rem] " +
                "font-normal tracking-widest " +
                (live
                  ? "border-sensei-500/40 text-sensei-400"
                  : "border-cyber-border text-cyber-faint")
              }
            >
              <span
                className={
                  "inline-block h-1.5 w-1.5 rounded-full " +
                  (live ? "animate-pulse bg-sensei-500" : "bg-cyber-faint")
                }
              />
              {live ? "LIVE" : "POLLING"}
            </span>
          </h1>
          <p className="text-xs text-cyber-faint">
            Measured on this machine. Nothing here has been sent anywhere.
          </p>
        </div>
        {/* Savings is the landing screen, so the other views are reachable
            from here rather than the other way round. */}
        <nav className="flex items-center gap-1">
          <button
            onClick={onOpenChat}
            className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs text-cyber-dim transition-colors hover:bg-cyber-surface-2 hover:text-cyber-text"
          >
            <MessageSquare className="h-4 w-4" />
            Chat
          </button>
          <button
            onClick={onOpenSettings}
            className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs text-cyber-dim transition-colors hover:bg-cyber-surface-2 hover:text-cyber-text"
          >
            <SlidersHorizontal className="h-4 w-4" />
            Models
          </button>
          <button
            onClick={load}
            aria-label="Refresh"
            className="rounded-lg p-2 text-cyber-dim transition-colors hover:text-[--color-accent]"
          >
            <RefreshCw className={"h-4 w-4 " + (busy ? "animate-spin" : "")} />
          </button>
        </nav>
      </header>

      <div className="mx-auto w-full max-w-6xl space-y-4 p-4">
        {error && (
          <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* A note, not an interstitial. No provider configured is a normal
            state for someone routing a subscription through the gateway — it
            only limits the parts of Sensei that originate a request.

            It used to lead with "No model provider configured.", and reading
            that while Claude Code was working perfectly through the gateway is
            alarming for no reason: it looks like the thing in front of you is
            broken. The sentence that is true of the whole system goes first,
            and the one about the optional part goes second. */}
        {needsSetup && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-cyber-border bg-cyber-surface px-4 py-3 text-xs">
            <span className="text-cyber-text">
              Your tools are connected and being compressed.
            </span>
            <span className="text-cyber-faint">
              They sign in with their own credentials, so Sensei needs no key of its own. One is
              only needed for Sensei&rsquo;s built-in chat, RAG and agent.
            </span>
            <button
              onClick={onOpenSettings}
              className="ml-auto rounded-md border border-cyber-border-bright px-3 py-1.5 text-cyber-dim transition-colors hover:text-[--color-accent]"
            >
              Set one up
            </button>
          </div>
        )}

        {lifetime && session && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat
                label="Tokens saved"
                value={formatTokens(lifetime.tokens_saved)}
                sub={`of ${formatTokens(lifetime.tokens_before)} sent`}
                tone="saving"
                delay={0}
              />
              <Stat
                label="Estimated cost saved"
                value={formatMoney(lifetime.estimated_cost_saved_usd)}
                sub={`at $${lifetime.price_per_million_usd}/M input tokens`}
                tone="saving"
                delay={40}
              />
              <Stat
                label="Compression"
                value={`${lifetime.percent_saved}%`}
                sub={`${lifetime.requests.toLocaleString()} requests`}
                tone="cyan"
                delay={80}
              />
              <Stat
                label="This session"
                value={formatTokens(session.tokens_saved)}
                sub={`${session.requests.toLocaleString()} requests since start`}
                delay={120}
              />
            </div>

            {/* The cost figure is an estimate built on one assumed price. Saying
                so on the page is cheaper than being disbelieved later. */}
            <p className="flex items-start gap-2 text-xs leading-relaxed text-cyber-faint">
              <TrendingDown className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Cost is an estimate: tokens saved × your configured input price (
                <code className="text-cyber-dim">SENSEI_USD_PER_MILLION_TOKENS</code>). It counts
                input tokens only, so it is a floor rather than a guess upward.
                {perDay > 0 && ` About ${formatMoney(perDay)} on a day you actually work.`}
                {!data?.persisted &&
                  " History is turned off (SENSEI_SAVINGS_PERSIST=false), so these totals reset when the server restarts."}
              </span>
            </p>

            <Panel title="Last 30 days" aside="tokens saved per day">
              <DailyChart days={data.daily} />
            </Panel>

            {data.output_effect?.enabled && <OutputShaping effect={data.output_effect} />}

            <div className="grid gap-3 md:grid-cols-3">
              <Breakdown title="By tool" rows={data.by_tool} />
              <Breakdown title="By provider" rows={data.by_provider} />
              <Breakdown title="By model" rows={data.by_model} />
            </div>

            {lifetime.requests === 0 && (
              <div className="gradient-border scan-overlay p-6 text-center">
                <p className="text-sm text-cyber-text">No requests have gone through yet.</p>
                <p className="mt-2 text-xs text-cyber-dim">
                  Point a tool at Sensei with{" "}
                  <code className="text-[--color-accent]">sensei setup-tools</code>, or run{" "}
                  <code className="text-[--color-accent]">sensei wrap claude</code>, and this page
                  fills up.
                </p>
              </div>
            )}

            <div className="flex justify-end pt-2">
              <button
                onClick={handleForget}
                className={
                  "flex items-center gap-2 rounded-lg px-3 py-2 text-xs transition-colors " +
                  (confirmingForget
                    ? "border border-red-900/60 bg-red-950/40 text-red-300"
                    : "text-cyber-faint hover:text-cyber-dim")
                }
              >
                <Trash2 className="h-3.5 w-3.5" />
                {confirmingForget ? "Delete history — this cannot be undone" : "Delete history"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
