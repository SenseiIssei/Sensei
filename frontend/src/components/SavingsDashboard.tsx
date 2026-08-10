import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, RefreshCw, Trash2, TrendingDown } from "lucide-react";
import { api } from "@/lib/api";
import type { SavingsDay, SavingsResponse, SavingsSlice } from "@/types";

/**
 * "How much have I actually saved?"
 *
 * The chart is hand-drawn SVG rather than a charting library on purpose: the
 * frontend has a 450 kB JavaScript budget enforced in CI, and every library
 * worth using costs more than that budget has to spare for one bar chart.
 */

// ── formatting ──────────────────────────────────────────────────────────────

function formatTokens(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatMoney(usd: number): string {
  // Below a cent, a rounded "$0.00" reads as "this does nothing". Show the
  // real number instead and let it be small.
  if (usd > 0 && usd < 0.01) return `$${usd.toFixed(4)}`;
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
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div className="glass rounded-xl border border-gray-800/50 p-4">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p
        className={
          "mt-1 text-2xl font-bold tabular-nums " +
          (accent ? "text-sensei-400" : "text-white")
        }
      >
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-gray-500">{sub}</p>}
    </div>
  );
}

function DailyChart({ days }: { days: SavingsDay[] }) {
  const peak = Math.max(...days.map((d) => d.tokens_saved), 1);
  const width = 720;
  const height = 160;
  const gap = 2;
  const barWidth = Math.max(1, width / days.length - gap);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height + 22}`}
        className="h-48 w-full min-w-[560px]"
        role="img"
        aria-label={`Tokens saved per day over the last ${days.length} days`}
      >
        {days.map((day, i) => {
          const barHeight = (day.tokens_saved / peak) * height;
          const x = i * (barWidth + gap);
          return (
            <g key={day.date}>
              {/* A zero day still gets a hairline, so idle days read as
                  "nothing happened" rather than as missing data. */}
              <rect
                x={x}
                y={height - Math.max(barHeight, day.tokens_saved > 0 ? 2 : 1)}
                width={barWidth}
                height={Math.max(barHeight, day.tokens_saved > 0 ? 2 : 1)}
                rx={1}
                className={day.tokens_saved > 0 ? "fill-sensei-500" : "fill-gray-800"}
              >
                <title>
                  {day.date}: {formatTokens(day.tokens_saved)} tokens saved over{" "}
                  {day.requests} request{day.requests === 1 ? "" : "s"} (
                  {formatMoney(day.estimated_cost_saved_usd)})
                </title>
              </rect>
              {/* Label every seventh day; more than that overlaps at this width. */}
              {i % 7 === 0 && (
                <text
                  x={x + barWidth / 2}
                  y={height + 16}
                  textAnchor="middle"
                  className="fill-gray-600 text-[10px]"
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
    <div className="glass rounded-xl border border-gray-800/50 p-4">
      <h3 className="text-sm font-semibold text-gray-300">{title}</h3>
      {rows.length === 0 ? (
        <p className="mt-3 text-xs text-gray-600">Nothing recorded yet.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {rows.map((row) => (
            <li key={row.key}>
              <div className="flex items-baseline justify-between gap-2 text-xs">
                <span className="truncate text-gray-300">{row.key}</span>
                <span className="shrink-0 tabular-nums text-gray-500">
                  {formatTokens(row.tokens_saved)} · {row.percent_saved}%
                </span>
              </div>
              <div className="mt-1 h-1.5 w-full rounded-full bg-gray-800">
                <div
                  className="h-1.5 rounded-full bg-sensei-500"
                  style={{ width: `${(row.tokens_saved / peak) * 100}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── page ────────────────────────────────────────────────────────────────────

export function SavingsDashboard({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<SavingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
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

  useEffect(() => {
    load();
    // Cheap enough to poll: one indexed SQLite query per tick.
    const timer = setInterval(load, 15_000);
    return () => clearInterval(timer);
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
    <div className="flex h-dvh w-full flex-col overflow-y-auto bg-gray-950">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-gray-800/50 glass px-4 py-3">
        <button
          onClick={onClose}
          aria-label="Back to chat"
          className="rounded-lg p-2 text-gray-400 transition-colors hover:text-white"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1">
          <h1 className="font-bold text-white">Savings</h1>
          <p className="text-xs text-gray-500">
            Measured on this machine. Nothing here has been sent anywhere.
          </p>
        </div>
        <button
          onClick={load}
          aria-label="Refresh"
          className="rounded-lg p-2 text-gray-400 transition-colors hover:text-white"
        >
          <RefreshCw className={"h-4 w-4 " + (busy ? "animate-spin" : "")} />
        </button>
      </header>

      <div className="mx-auto w-full max-w-5xl space-y-4 p-4">
        {error && (
          <div className="rounded-xl border border-red-900/50 bg-red-950/30 p-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {lifetime && session && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat
                label="Tokens saved"
                value={formatTokens(lifetime.tokens_saved)}
                sub={`of ${formatTokens(lifetime.tokens_before)} sent`}
                accent
              />
              <Stat
                label="Estimated cost saved"
                value={formatMoney(lifetime.estimated_cost_saved_usd)}
                sub={`at $${lifetime.price_per_million_usd}/M input tokens`}
                accent
              />
              <Stat
                label="Compression"
                value={`${lifetime.percent_saved}%`}
                sub={`${lifetime.requests.toLocaleString()} requests`}
              />
              <Stat
                label="This session"
                value={formatTokens(session.tokens_saved)}
                sub={`${session.requests.toLocaleString()} requests since start`}
              />
            </div>

            {/* The cost figure is an estimate built on one assumed price. Saying
                so on the page is cheaper than being disbelieved later. */}
            <p className="flex items-start gap-2 text-xs text-gray-600">
              <TrendingDown className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Cost is an estimate: tokens saved × your configured input price (
                <code className="text-gray-500">SENSEI_USD_PER_MILLION_TOKENS</code>). It counts
                input tokens only, so it is a floor rather than a guess upward.
                {perDay > 0 && ` About ${formatMoney(perDay)} on a day you actually work.`}
                {!data?.persisted &&
                  " History is turned off (SENSEI_SAVINGS_PERSIST=false), so these totals reset when the server restarts."}
              </span>
            </p>

            <div className="glass rounded-xl border border-gray-800/50 p-4">
              <div className="mb-3 flex items-baseline justify-between">
                <h2 className="text-sm font-semibold text-gray-300">Last 30 days</h2>
                <span className="text-xs text-gray-600">tokens saved per day</span>
              </div>
              <DailyChart days={data.daily} />
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              <Breakdown title="By tool" rows={data.by_tool} />
              <Breakdown title="By provider" rows={data.by_provider} />
              <Breakdown title="By model" rows={data.by_model} />
            </div>

            {lifetime.requests === 0 && (
              <div className="glass rounded-xl border border-gray-800/50 p-6 text-center">
                <p className="text-sm text-gray-400">No requests have gone through yet.</p>
                <p className="mt-2 text-xs text-gray-600">
                  Point a tool at Sensei with{" "}
                  <code className="text-gray-400">sensei setup-tools</code>, or run{" "}
                  <code className="text-gray-400">sensei wrap claude</code>, and this page fills
                  up.
                </p>
              </div>
            )}

            <div className="flex justify-end pt-2">
              <button
                onClick={handleForget}
                className={
                  "flex items-center gap-2 rounded-lg px-3 py-2 text-xs transition-colors " +
                  (confirmingForget
                    ? "bg-red-900/40 text-red-300"
                    : "text-gray-600 hover:text-gray-400")
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
