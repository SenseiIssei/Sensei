/**
 * Is the Sensei backend actually reachable?
 *
 * `navigator.onLine` is not the question. For a self-hosted tool the common
 * failure is not "no internet" — it's that the server on your own machine
 * stopped, crashed, or was never started. `navigator.onLine` reports `true`
 * throughout, so relying on it would tell the user everything is fine while
 * every request fails.
 */

export type ConnectionState = "online" | "offline" | "checking";

const HEALTH_URL = "/health";

export async function probeBackend(signal?: AbortSignal): Promise<boolean> {
  try {
    const resp = await fetch(HEALTH_URL, { cache: "no-store", signal });
    return resp.ok;
  } catch {
    return false;
  }
}

/**
 * Poll the backend and report changes.
 *
 * Backs off while the server is up (a healthy server needs checking rarely)
 * and polls quickly while it's down, so the UI recovers promptly once the user
 * restarts it. Returns an unsubscribe function.
 */
export function watchConnection(
  onChange: (state: ConnectionState) => void,
  {
    upIntervalMs = 30_000,
    downIntervalMs = 3_000,
    setTimeoutFn = setTimeout,
    clearTimeoutFn = clearTimeout,
  }: {
    upIntervalMs?: number;
    downIntervalMs?: number;
    setTimeoutFn?: typeof setTimeout;
    clearTimeoutFn?: typeof clearTimeout;
  } = {},
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let last: ConnectionState | null = null;
  const controller = new AbortController();

  const emit = (state: ConnectionState) => {
    if (state !== last) {
      last = state;
      onChange(state);
    }
  };

  const tick = async () => {
    if (stopped) return;
    const ok = await probeBackend(controller.signal);
    if (stopped) return;
    emit(ok ? "online" : "offline");
    timer = setTimeoutFn(tick, ok ? upIntervalMs : downIntervalMs);
  };

  void tick();

  return () => {
    stopped = true;
    controller.abort();
    if (timer !== undefined) clearTimeoutFn(timer);
  };
}
