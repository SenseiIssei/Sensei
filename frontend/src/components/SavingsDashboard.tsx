import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpCircle, Info, RefreshCw, Trash2 } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import { formatDay, formatMoney, formatPercent, formatTokens } from "@/lib/format";
import type { CacheTotals, OutputEffect, SavingsDay, SavingsResponse, SavingsSlice, UpdateStatus } from "@/types";
import { Badge, Button, Card, IconButton, Notice, PageHeader, StatTile } from "@/components/ui";

/**
 * "How much have I actually saved?"
 *
 * The landing screen. One number in gold — tokens saved — because that is
 * what the product is for; everything else is quieter context around it.
 *
 * The charts are hand-drawn SVG rather than a charting library: the frontend
 * has a 450 kB JavaScript budget enforced in CI, and every library worth using
 * costs more than that budget has to spare for two charts.
 */

function DailyChart({ days }: { days: SavingsDay[] }) {
  const peak = Math.max(...days.map((d) => d.tokens_saved), 1);
  const width = 760;
  const height = 160;
  const gap = 4;
  const barWidth = Math.max(1, width / Math.max(days.length, 1) - gap);

  return (
    <div className="overflow-x-auto scrollbar-thin">
      <svg
        viewBox={`0 0 ${width} ${height + 24}`}
        className="h-48 w-full min-w-[520px]"
        role="img"
        aria-label={`Tokens saved per day over the last ${days.length} days`}
      >
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line
            key={f}
            x1={0}
            x2={width}
            y1={height - height * f}
            y2={height - height * f}
            style={{ stroke: "var(--line-subtle)" }}
            strokeWidth="1"
          />
        ))}
        {days.map((day, i) => {
          const active = day.tokens_saved > 0;
          // A zero day still gets a hairline, so idle days read as "nothing
          // happened" rather than as missing data.
          const h = active ? Math.max((day.tokens_saved / peak) * height, 3) : 1;
          const x = i * (barWidth + gap);
          return (
            <g key={day.date}>
              <rect
                x={x}
                y={height - h}
                width={barWidth}
                height={h}
                rx={2}
                style={{ fill: active ? "var(--chart-1)" : "var(--line)" }}
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
                  style={{ fill: "var(--faint)", fontSize: 10 }}
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
    <Card title={title} padded={false} className="overflow-hidden">
      {rows.length === 0 ? (
        <p className="px-5 pb-5 text-xs text-muted">Nothing recorded yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-header-fill">
              <th className="eyebrow h-8 px-5 text-left text-muted">Name</th>
              <th className="eyebrow h-8 px-5 text-right text-muted">Saved</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-t border-line-subtle transition-colors hover:bg-hover">
                <td className="max-w-0 px-5 py-2.5">
                  <p className="truncate text-fg">{row.key}</p>
                  <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-line-subtle">
                    <div
                      className="h-1 rounded-full bg-accent"
                      style={{ width: `${(row.tokens_saved / peak) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="whitespace-nowrap px-5 py-2.5 text-right">
                  <p className="num font-semibold text-fg">{formatTokens(row.tokens_saved)}</p>
                  <p className="num text-xs text-muted">{row.percent_saved}%</p>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

/**
 * What the provider served from its prompt cache.
 *
 * Compression only saves money if it leaves caching intact — a cached token
 * costs a tenth of a fresh one or less — so this sits next to the savings
 * rather than in a debug view. "No data" is shown as such, never as 0%.
 */
function PromptCache({ cache }: { cache: CacheTotals }) {
  const reported = cache.requests_reporting_usage > 0;
  return (
    <Card
      title="Prompt cache"
      description="As reported by the provider, per request"
      actions={reported ? <Badge tone="success">measured</Badge> : <Badge>no data yet</Badge>}
    >
      {reported ? (
        <>
          <p className="num text-[28px] font-bold leading-9 tracking-[-0.02em] text-fg">
            {formatPercent(cache.hit_rate)}
          </p>
          <p className="text-xs text-muted">of billed prompt tokens were cache reads</p>
          <dl className="mt-4 grid grid-cols-3 gap-3 border-t border-line-subtle pt-3 text-xs">
            <div>
              <dt className="text-muted">Billed</dt>
              <dd className="num font-semibold text-fg">{formatTokens(cache.prompt_tokens_billed)}</dd>
            </div>
            <div>
              <dt className="text-muted">Cache reads</dt>
              <dd className="num font-semibold text-fg">{formatTokens(cache.cache_read_tokens)}</dd>
            </div>
            <div>
              <dt className="text-muted">Cache writes</dt>
              <dd className="num font-semibold text-fg">{formatTokens(cache.cache_write_tokens)}</dd>
            </div>
          </dl>
        </>
      ) : (
        <p className="text-[13px] text-muted">
          Appears once a provider reports usage through the gateway. Sensei compresses
          deterministically, so the same prefix produces the same bytes and keeps hitting the
          cache.
        </p>
      )}
    </Card>
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

  return (
    <Card
      title="Output shaping"
      description={`${Math.round(effect.holdout * 100)}% held back as a control`}
    >
      {!interval ? (
        <>
          <p className="text-[13px] text-fg">Not enough data yet.</p>
          <p className="mt-1 text-xs text-muted">{effect.detail}</p>
        </>
      ) : (
        <>
          <p className="text-xs text-muted">95% confident the change is between</p>
          <p className="num mt-1 font-bold leading-none">
            <span className="text-2xl text-fg">{interval[0]}%</span>
            <span className="mx-2 text-sm font-normal text-muted">and</span>
            <span className="text-2xl text-fg">{interval[1]}%</span>
          </p>
          <p className="mt-2 text-xs text-muted">
            Best estimate {effect.percent}% ({effect.difference_tokens} tokens per answer) ·{" "}
            <span
              className={clsx(
                effect.verdict === "shorter answers" && "text-success",
                effect.verdict === "longer answers" && "text-danger",
              )}
            >
              {effect.verdict}
            </span>
          </p>
        </>
      )}

      <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-line-subtle pt-3 text-xs">
        <div>
          <dt className="text-muted">Shaped</dt>
          <dd className="num text-fg">
            {effect.shaped.requests.toLocaleString()} · {effect.shaped.mean_output_tokens} tok/answer
          </dd>
        </div>
        <div>
          <dt className="text-muted">Control</dt>
          <dd className="num text-fg">
            {effect.control.requests.toLocaleString()} · {effect.control.mean_output_tokens}{" "}
            tok/answer
          </dd>
        </div>
      </dl>
    </Card>
  );
}

export function SavingsDashboard({
  needsSetup = false,
  onOpenChat,
  onOpenSettings,
}: {
  needsSetup?: boolean;
  onOpenChat?: () => void;
  onOpenSettings?: () => void;
}) {
  const [data, setData] = useState<SavingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(false);
  const [confirmingForget, setConfirmingForget] = useState(false);
  const [update, setUpdate] = useState<UpdateStatus | null>(null);

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

  // Live, over Server-Sent Events, with the one-shot fetch first: EventSource
  // gives nothing until the server's first event, and an empty dashboard while
  // the stream connects looks like a broken one.
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
        // EventSource reconnects by itself; poll while it is down.
        setLive(false);
        if (!poll) poll = setInterval(load, 15_000);
      });
    } catch {
      poll = setInterval(load, 15_000);
    }

    return () => {
      source?.close();
      if (poll) clearInterval(poll);
    };
  }, [load]);

  // Only answers with a release when SENSEI_UPDATE_CHECK is on; otherwise the
  // server returns immediately without asking GitHub anything.
  useEffect(() => {
    api
      .getUpdateStatus()
      .then((u) => setUpdate(u?.update_available ? u : null))
      .catch(() => undefined);
  }, []);

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
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
        <PageHeader
          title={
            <>
              Overview
              {/* Says whether the stream is actually connected, rather than a
                  "live" badge that is always on. */}
              <span title={live ? "Streaming live" : "Stream not connected — polling instead"}>
                <Badge tone={live ? "success" : "neutral"}>
                  <span
                    className={clsx(
                      "inline-block h-1.5 w-1.5 rounded-full",
                      live ? "bg-success" : "bg-faint",
                    )}
                  />
                  {live ? "Live" : "Polling"}
                </Badge>
              </span>
            </>
          }
          description="Measured on this machine. Nothing here has been sent anywhere."
          actions={
            <>
              {onOpenChat && (
                <Button variant="ghost" onClick={onOpenChat}>
                  Chat
                </Button>
              )}
              <IconButton label="Refresh" onClick={load}>
                <RefreshCw className={clsx("h-4 w-4", busy && "animate-spin")} />
              </IconButton>
            </>
          }
        />

        <div className="space-y-4">
          {error && <Notice tone="danger">{error}</Notice>}

          {update && (
            <Notice
              tone="accent"
              icon={<ArrowUpCircle className="h-4 w-4" />}
              action={
                <a
                  href={update.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex h-7 items-center rounded-sm bg-accent px-2.5 text-xs font-semibold text-accent-fg hover:bg-accent-hover"
                >
                  What&rsquo;s new
                </a>
              }
            >
              Sensei {update.latest} is available — you have {update.current}. Run{" "}
              <code className="font-mono text-fg">sensei update</code> or use the tray menu.
            </Notice>
          )}

          {/* A note, not an interstitial. No provider configured is a normal
              state for someone routing a subscription through the gateway —
              it only limits the parts of Sensei that originate a request. */}
          {needsSetup && (
            <Notice
              tone="neutral"
              icon={<Info className="h-4 w-4 text-muted" />}
              action={
                onOpenSettings && (
                  <Button size="sm" onClick={onOpenSettings}>
                    Set one up
                  </Button>
                )
              }
            >
              <span className="text-fg">Your tools are connected and being compressed.</span>{" "}
              They sign in with their own credentials, so Sensei needs no key of its own. One is
              only needed for Sensei&rsquo;s built-in chat, RAG and agent.
            </Notice>
          )}

          {lifetime && session && (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile
                  label="Tokens saved"
                  value={formatTokens(lifetime.tokens_saved)}
                  sub={`of ${formatTokens(lifetime.tokens_before)} sent`}
                  highlight
                />
                <StatTile
                  label="Estimated cost saved"
                  value={formatMoney(lifetime.estimated_cost_saved_usd)}
                  sub={`at $${lifetime.price_per_million_usd}/M input tokens`}
                />
                <StatTile
                  label="Compression"
                  value={`${lifetime.percent_saved}%`}
                  sub={`${lifetime.requests.toLocaleString()} requests`}
                />
                <StatTile
                  label="This session"
                  value={formatTokens(session.tokens_saved)}
                  sub={`${session.requests.toLocaleString()} requests since start`}
                />
              </div>

              {/* The cost figure is an estimate built on one assumed price.
                  Saying so on the page is cheaper than being disbelieved. */}
              <p className="flex items-start gap-2 text-xs leading-5 text-muted">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Cost is an estimate: tokens saved × your configured input price (
                  <code className="font-mono text-fg-secondary">SENSEI_USD_PER_MILLION_TOKENS</code>
                  ). It counts input tokens only, so it is a floor rather than a guess upward.
                  {perDay > 0 && ` About ${formatMoney(perDay)} on a day you actually work.`}
                  {!data?.persisted &&
                    " History is turned off (SENSEI_SAVINGS_PERSIST=false), so these totals reset when the server restarts."}
                </span>
              </p>

              <div className="grid gap-4 lg:grid-cols-3">
                <Card
                  title="Last 30 days"
                  description="Tokens saved per day"
                  className={lifetime.cache ? "lg:col-span-2" : "lg:col-span-3"}
                >
                  <DailyChart days={data.daily} />
                </Card>
                {lifetime.cache && <PromptCache cache={lifetime.cache} />}
              </div>

              {data.output_effect?.enabled && <OutputShaping effect={data.output_effect} />}

              <div className="grid gap-4 md:grid-cols-3">
                <Breakdown title="By tool" rows={data.by_tool} />
                <Breakdown title="By provider" rows={data.by_provider} />
                <Breakdown title="By model" rows={data.by_model} />
              </div>

              {lifetime.requests === 0 && (
                <Card className="text-center">
                  <p className="text-[15px] font-semibold text-fg">
                    No requests have gone through yet.
                  </p>
                  <p className="mt-2 text-[13px] text-muted">
                    Point a tool at Sensei with{" "}
                    <code className="font-mono text-accent">sensei setup-tools</code>, or run{" "}
                    <code className="font-mono text-accent">sensei wrap claude</code>, and this page
                    fills up.
                  </p>
                </Card>
              )}

              <div className="flex justify-end pt-2">
                <Button
                  variant={confirmingForget ? "danger" : "ghost"}
                  size="sm"
                  onClick={handleForget}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {confirmingForget ? "Delete history — this cannot be undone" : "Delete history"}
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
