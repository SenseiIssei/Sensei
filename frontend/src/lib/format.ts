/** Number formatting shared by every screen, so "4.00M" means the same everywhere. */

export function formatTokens(n: number): string {
  const sign = n < 0 ? "-" : "";
  const v = Math.abs(n);
  if (v >= 1_000_000_000) return `${sign}${(v / 1_000_000_000).toFixed(2)}B`;
  if (v >= 1_000_000) return `${sign}${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${sign}${(v / 1_000).toFixed(1)}k`;
  return `${sign}${v}`;
}

export function formatMoney(usd: number): string {
  // Below a cent, a rounded "$0.00" reads as "this does nothing". Show the
  // real number instead and let it be small.
  if (Math.abs(usd) > 0 && Math.abs(usd) < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function formatDay(iso: string): string {
  const [, month, day] = iso.split("-");
  return `${day}.${month}.`;
}

export function formatPercent(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined) return "—";
  return `${Math.round(fraction * 1000) / 10}%`;
}
