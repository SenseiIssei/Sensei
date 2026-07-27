import { useState, useEffect, useCallback } from "react";
import {
  Check,
  Cpu,
  Download,
  ExternalLink,
  Loader2,
  Lock,
  Server,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { SetupStatus, ProviderModels } from "@/types";

/**
 * First-run setup.
 *
 * The point is that a new user never opens a text editor. Two paths, both
 * finishing in one screen: run a model locally for free, or paste a key for a
 * hosted provider. Model lists come from the provider at the moment you need
 * them rather than from a hardcoded array that goes stale.
 */

function gb(mb: number | null | undefined): string {
  return mb ? `${(mb / 1024).toFixed(1)} GB` : "unknown";
}

type Path = "local" | "api";

export function SetupWizard({ status, onDone }: { status: SetupStatus; onDone: () => void }) {
  const suggestion = status.recommended_local_model;
  // Ollama already running means local is a real option; otherwise lead with
  // the path that can actually finish right now.
  const [path, setPath] = useState<Path>(status.ollama.running ? "local" : "api");

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto surreal-bg">
      <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col justify-center px-4 py-10 sm:px-6">
        <header className="mb-8 text-center">
          <div className="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-2xl glass">
            <Sparkles className="h-7 w-7 text-sensei-400" />
          </div>
          <h1 className="text-2xl font-semibold text-white sm:text-3xl">Welcome to Sensei</h1>
          <p className="mt-2 text-sm text-gray-400">
            One thing left: pick something for Sensei to talk to.
          </p>
        </header>

        <div
          className="mb-6 grid gap-3 sm:grid-cols-2"
          role="tablist"
          aria-label="Setup method"
        >
          <PathCard
            active={path === "local"}
            onClick={() => setPath("local")}
            icon={<Cpu className="h-5 w-5" />}
            title="Run a model locally"
            subtitle="Free, private, no account. Needs Ollama."
          />
          <PathCard
            active={path === "api"}
            onClick={() => setPath("api")}
            icon={<Server className="h-5 w-5" />}
            title="Use a hosted provider"
            subtitle="Paste an API key. Several have free tiers."
          />
        </div>

        {path === "local" ? (
          <LocalPath status={status} onDone={onDone} />
        ) : (
          <ApiPath status={status} onDone={onDone} />
        )}

        <footer className="mt-8 space-y-3 text-center">
          <p className="text-xs text-gray-500">
            {status.hardware.cpu_count} cores · {gb(status.hardware.ram_mb)} RAM ·{" "}
            {status.hardware.gpus[0]?.name ?? "no GPU detected"} ·{" "}
            {gb(status.hardware.usable_vram_mb)} usable for a model
            {suggestion ? ` · best local fit: ${suggestion.name}` : ""}
          </p>
          <button
            onClick={onDone}
            className="text-xs text-gray-500 underline underline-offset-4 hover:text-gray-300"
          >
            Skip for now — I'll configure this later
          </button>
        </footer>
      </div>
    </div>
  );
}

function PathCard({
  active,
  onClick,
  icon,
  title,
  subtitle,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  subtitle: string;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={clsx(
        "rounded-xl border p-4 text-left transition-colors",
        active
          ? "border-sensei-600/60 bg-sensei-950/40"
          : "border-gray-700/50 glass glass-hover",
      )}
    >
      <div className="mb-1 flex items-center gap-2 text-white">
        <span className={active ? "text-sensei-400" : "text-gray-400"}>{icon}</span>
        <span className="font-medium">{title}</span>
      </div>
      <p className="text-xs text-gray-400">{subtitle}</p>
    </button>
  );
}

function LocalPath({ status, onDone }: { status: SetupStatus; onDone: () => void }) {
  const [model, setModel] = useState(status.ollama.models[0] ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const suggestion = status.recommended_local_model;

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      await api.applySettings({ provider: "ollama", model });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that.");
    } finally {
      setSaving(false);
    }
  }, [model, onDone]);

  if (!status.ollama.running) {
    return (
      <Panel>
        <div className="flex items-start gap-3">
          <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
          <div className="min-w-0">
            <p className="text-sm text-white">Ollama isn't running</p>
            <p className="mt-1 text-xs text-gray-400">
              Sensei looked at <code className="text-gray-300">{status.ollama.host}</code> and got
              no answer. Install it, then pull a model — Sensei will pick it up automatically.
            </p>
          </div>
        </div>

        <a
          href="https://ollama.com"
          target="_blank"
          rel="noreferrer noopener"
          className="mt-4 inline-flex items-center gap-1.5 text-sm text-sensei-400 hover:text-sensei-300"
        >
          Get Ollama <ExternalLink className="h-3.5 w-3.5" />
        </a>

        {suggestion && (
          <div className="mt-4 rounded-lg border border-gray-700/50 bg-black/20 p-3">
            <p className="text-xs text-gray-400">
              For {gb(status.hardware.usable_vram_mb)} of usable memory, start with:
            </p>
            <code className="mt-2 block overflow-x-auto whitespace-pre text-sm text-sensei-300">
              ollama pull {suggestion.id}
            </code>
            <p className="mt-2 text-xs text-gray-500">
              {suggestion.name} · {suggestion.params} · {gb(suggestion.size_mb)} — {suggestion.good_for}
            </p>
          </div>
        )}
      </Panel>
    );
  }

  return (
    <Panel>
      <label htmlFor="local-model" className="block text-sm text-white">
        Installed models
      </label>
      <p className="mb-3 mt-1 text-xs text-gray-400">
        Found {status.ollama.models.length} on {status.ollama.host}.
      </p>
      <select
        id="local-model"
        value={model}
        onChange={(e) => setModel(e.target.value)}
        className="w-full rounded-lg border border-gray-700/50 bg-gray-900 px-3 py-2 text-sm text-white focus:border-sensei-600/50 focus:outline-hidden"
      >
        {status.ollama.models.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>

      {suggestion && !status.ollama.models.some((m) => m.split(":")[0] === suggestion.id.split(":")[0]) && (
        <p className="mt-3 flex items-start gap-1.5 text-xs text-gray-500">
          <Download className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            For this hardware, <code className="text-gray-400">ollama pull {suggestion.id}</code>{" "}
            would fit comfortably.
          </span>
        </p>
      )}

      <Actions error={error} saving={saving} disabled={!model} onSave={save} />
    </Panel>
  );
}

function ApiPath({ status, onDone }: { status: SetupStatus; onDone: () => void }) {
  const providers = status.catalog.filter((p) => p.id !== "ollama");
  const [provider, setProvider] = useState(providers[0]?.id ?? "openrouter");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [list, setList] = useState<ProviderModels | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadModels = useCallback(async (p: string) => {
    setLoadingModels(true);
    try {
      const res = await api.getProviderModels(p);
      setList(res);
      setModel((current) => (res.models.includes(current) ? current : (res.models[0] ?? "")));
    } catch {
      setList(null);
    } finally {
      setLoadingModels(false);
    }
  }, []);

  useEffect(() => {
    void loadModels(provider);
  }, [provider, loadModels]);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      // Send the key first so the server can store it in the vault, then let it
      // re-read the live model list on the next visit.
      await api.applySettings({ provider, api_key: apiKey || undefined, model: model || undefined });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that.");
    } finally {
      setSaving(false);
    }
  }, [provider, apiKey, model, onDone]);

  const selected = providers.find((p) => p.id === provider);

  return (
    <Panel>
      <label htmlFor="provider" className="block text-sm text-white">
        Provider
      </label>
      <select
        id="provider"
        value={provider}
        onChange={(e) => setProvider(e.target.value)}
        className="mt-2 w-full rounded-lg border border-gray-700/50 bg-gray-900 px-3 py-2 text-sm text-white focus:border-sensei-600/50 focus:outline-hidden"
      >
        {providers.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
            {p.free ? " — has a free tier" : ""}
          </option>
        ))}
      </select>

      <label htmlFor="api-key" className="mt-5 block text-sm text-white">
        API key
      </label>
      <div className="relative mt-2">
        <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
        <input
          id="api-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          onBlur={() => apiKey && void loadModels(provider)}
          placeholder={
            status.configured_providers.includes(provider)
              ? "already set — leave blank to keep it"
              : "paste it here"
          }
          className="w-full rounded-lg border border-gray-700/50 bg-gray-900 py-2 pl-9 pr-3 text-sm text-white focus:border-sensei-600/50 focus:outline-hidden"
        />
      </div>
      <p className="mt-2 text-xs text-gray-500">
        Stored encrypted on this machine, never in plain text. Sensei forwards it to{" "}
        {selected?.name ?? "the provider"} and nowhere else.
      </p>

      <label htmlFor="model" className="mt-5 block text-sm text-white">
        Model
        {loadingModels && <Loader2 className="ml-2 inline h-3.5 w-3.5 animate-spin text-gray-500" />}
      </label>
      <select
        id="model"
        value={model}
        onChange={(e) => setModel(e.target.value)}
        disabled={!list?.models.length}
        className="mt-2 w-full rounded-lg border border-gray-700/50 bg-gray-900 px-3 py-2 text-sm text-white focus:border-sensei-600/50 focus:outline-hidden disabled:opacity-50"
      >
        {(list?.models ?? []).map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
      {list && (
        <p className="mt-2 text-xs text-gray-500">
          {list.source === "live"
            ? `${list.models.length} models, fetched from ${selected?.name ?? provider} just now.`
            : list.detail}
        </p>
      )}

      <Actions error={error} saving={saving} disabled={!apiKey && !status.configured_providers.includes(provider)} onSave={save} />
    </Panel>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return <div className="glass-card p-5 sm:p-6">{children}</div>;
}

function Actions({
  error,
  saving,
  disabled,
  onSave,
}: {
  error: string | null;
  saving: boolean;
  disabled: boolean;
  onSave: () => void;
}) {
  return (
    <>
      {error && (
        <p role="alert" className="mt-4 text-xs text-red-400">
          {error}
        </p>
      )}
      <button
        onClick={onSave}
        disabled={saving || disabled}
        className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-sensei-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sensei-500 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {saving ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" /> Saving
          </>
        ) : (
          <>
            <Check className="h-4 w-4" /> Start using Sensei
          </>
        )}
      </button>
    </>
  );
}
