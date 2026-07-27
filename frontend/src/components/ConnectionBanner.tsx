import { useEffect, useState } from "react";
import { PlugZap } from "lucide-react";
import { watchConnection, type ConnectionState } from "@/lib/connection";

/**
 * Tells the user the backend is unreachable, and what to do about it.
 *
 * The failure this addresses is specific to self-hosted software: the server
 * is on your own machine and it isn't running. Without this the UI loads fine
 * from the service-worker cache and then every action fails silently, which
 * looks like Sensei being broken rather than Sensei not being started.
 */
export function ConnectionBanner() {
  const [state, setState] = useState<ConnectionState>("checking");

  useEffect(() => watchConnection(setState), []);

  if (state !== "offline") return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="absolute inset-x-0 top-0 z-30 flex items-center justify-center gap-2 border-b border-amber-500/30 bg-amber-950/80 px-4 py-2 text-xs text-amber-200 backdrop-blur-sm"
    >
      <PlugZap className="h-3.5 w-3.5 shrink-0" />
      <span>
        Can't reach the Sensei backend. Start it with{" "}
        <code className="rounded bg-black/30 px-1 py-0.5 text-amber-100">sensei up</code>, or run{" "}
        <code className="rounded bg-black/30 px-1 py-0.5 text-amber-100">sensei doctor</code> to
        find out why.
      </span>
    </div>
  );
}
