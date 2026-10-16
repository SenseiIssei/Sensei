export interface ProviderCatalogEntry {
  id: string;
  name: string;
  free: boolean;
  /** Runs on the user's own machine: no account, no key, nothing leaves it.
   *  Distinct from `free`, which is a price on someone else's service. */
  local?: boolean;
  models: string[];
}

export interface HardwareInfo {
  os: string;
  arch: string;
  cpu_count: number;
  ram_mb: number | null;
  usable_vram_mb: number | null;
  unified_memory: boolean;
  gpus: { name: string; vram_mb: number | null; vendor: string }[];
}

export interface LocalModelSuggestion {
  id: string;
  name: string;
  params: string;
  size_mb: number;
  good_for: string;
  fit: "comfortable" | "tight" | "too_large" | "unknown";
}

export interface SetupStatus {
  ready: boolean;
  needs_setup: boolean;
  configured_providers: string[];
  active_provider: string;
  model_provider: string;
  ollama: {
    running: boolean;
    host: string;
    models: string[];
    active_model: string;
  };
  hardware: HardwareInfo;
  recommended_local_model: LocalModelSuggestion | null;
  catalog: ProviderCatalogEntry[];
  compression_enabled: boolean;
}

export interface ProviderModels {
  provider: string;
  models: string[];
  /** "live" came from the provider just now; "catalog" is a static fallback. */
  source: "live" | "catalog";
  detail: string;
}

export interface FileReference {
  id: string;
  name: string;
  type: string;
  size: number;
  dataUrl?: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: number;
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
  timestamp?: number;
  files?: FileReference[];
  model?: string;
  tokensSaved?: number;
}

export interface Conversation {
  id: string;
  title: string;
  updated_at: number;
  pinned?: boolean;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
  created_at: number;
}

export interface ModelInfo {
  id: string;
  name: string;
  provider: "local" | "api";
  backend: string;
  context_window: number;
  status: "available" | "unavailable" | "loading" | "unknown";
  description: string;
  quantization: string | null;
}

export interface ModelsResponse {
  models: ModelInfo[];
  gpu_detected: boolean;
}

export interface CCRStats {
  total_entries: number;
  active_entries: number;
  total_original_bytes: number;
  total_compressed_bytes: number;
  space_saved_bytes: number;
}

export interface SavingsStats {
  requests: number;
  tokens_before: number;
  tokens_after: number;
  tokens_saved: number;
  blocks_compressed: number;
  compression_ratio: number;
  percent_saved: number;
  estimated_cost_saved_usd: number;
  price_per_million_usd: number;
  since: number;
}

export interface StatsResponse {
  compression_enabled: boolean;
  ccr: CCRStats;
  evicted_entries: number;
  cache_ttl_hours: number;
  savings?: SavingsStats;
}

/** One day's bucket in the savings history. Days with no traffic are present
 *  with zeroes rather than absent — see the backend's `daily()`. */
export interface SavingsDay {
  date: string;
  tokens_before: number;
  tokens_after: number;
  tokens_saved: number;
  requests: number;
  estimated_cost_saved_usd: number;
}

/** Savings grouped by tool, provider or model. */
export interface SavingsSlice {
  key: string;
  tokens_before: number;
  tokens_after: number;
  tokens_saved: number;
  requests: number;
  percent_saved: number;
  estimated_cost_saved_usd: number;
}

/** What the provider reported billing, including its prompt cache. */
export interface CacheTotals {
  requests_reporting_usage: number;
  prompt_tokens_billed: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  /** Share of billed prompt tokens read from cache; null until reported. */
  hit_rate: number | null;
}

export interface UpdateStatus {
  current: string;
  enabled: boolean;
  latest?: string;
  update_available?: boolean;
  url?: string;
  install_kind?: string;
  error?: string;
}

export type ToolState =
  | "connected"
  | "declined"
  | "not-connected"
  | "not-installed"
  | "unsupported";

export interface ConnectedTool {
  id: string;
  name: string;
  installed: boolean;
  connected: boolean;
  declined: boolean;
  /** What connecting does: "hook+mcp", "route", "mcp", … or "none". */
  support?: string;
  /** Why something is missing — e.g. why routing is impossible. */
  why?: string;
  note?: string;
  verified?: boolean;
  /** Opt-in features this tool offers, e.g. ["route"]. */
  options?: string[];
  enabled_options?: string[];
  needs_restart?: boolean;
  state?: ToolState;
}

export interface ToolOutcome {
  id: string;
  name: string;
  status: "applied" | "unchanged" | "manual" | "failed";
  detail: string;
  path: string | null;
  manual_snippet: string;
}

export interface ToolsResponse {
  tools: ConnectedTool[];
  auto_connect: {
    enabled: boolean;
    /** What the user chose: true, false, or null (never asked → on). */
    choice?: boolean | null;
    /** SENSEI_AUTO_CONNECT; when false nothing is connected automatically. */
    setting?: boolean;
    running: boolean;
    interval_seconds: number;
    scans: number;
    connected_since_start: string[];
    last_error: string | null;
  };
}

export interface SavingsTotals {
  cache?: CacheTotals;
  requests: number;
  tokens_before: number;
  tokens_after: number;
  tokens_saved: number;
  blocks_compressed: number;
  compression_ratio: number;
  percent_saved: number;
  estimated_cost_saved_usd: number;
  price_per_million_usd: number;
  since: number;
}

/** The output-shaping holdout comparison.
 *
 *  `confidence_interval_95` is absent until both arms have enough samples —
 *  the backend refuses to report a difference it cannot support, and the UI
 *  must show that refusal rather than rendering a zero. */
export interface OutputEffect {
  enabled: boolean;
  holdout: number;
  verdict: string;
  detail?: string;
  shaped: { requests: number; mean_output_tokens: number };
  control: { requests: number; mean_output_tokens: number };
  difference_tokens?: number;
  percent?: number;
  confidence_interval_95?: [number, number];
  percent_interval_95?: [number, number];
}

export interface SavingsResponse {
  /** Since this server process started. */
  session: SavingsTotals;
  /** Everything in the local ledger, across every run. */
  lifetime: SavingsTotals;
  daily: SavingsDay[];
  by_tool: SavingsSlice[];
  by_provider: SavingsSlice[];
  by_model: SavingsSlice[];
  /** False when SENSEI_SAVINGS_PERSIST is off — lifetime then equals session. */
  persisted: boolean;
  price_per_million_usd: number;
  output_effect?: OutputEffect;
}

export interface WSMeta {
  type: "meta";
  conversation_id: string;
  tokens_saved: number;
  compression_enabled: boolean;
  model?: string;
}

export interface WSToken {
  type: "token";
  content: string;
}

export interface WSDone {
  type: "done";
}

export interface WSError {
  type: "error";
  content: string;
}

export type WSMessage = WSMeta | WSToken | WSDone | WSError;

export interface ProviderOption {
  id: string;
  name: string;
  models: string[];
  free: boolean;
}

/** Fallback list for the chat's model picker when the server cannot be asked.
 *  The setup wizard always asks the provider itself. */
export const PROVIDERS: ProviderOption[] = [
  { id: "ollama", name: "Ollama (local)", models: ["qwen3.5:9b", "gemma4:e4b", "qwen3.8:27b", "gpt-oss:20b"], free: true },
  { id: "anthropic", name: "Anthropic", models: ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"], free: false },
  { id: "openai", name: "OpenAI", models: ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna"], free: false },
  { id: "google", name: "Google Gemini", models: ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-4-argon"], free: true },
  { id: "openrouter", name: "OpenRouter", models: ["~anthropic/claude-sonnet-latest", "~openai/gpt-sol-latest", "z-ai/glm-5.3"], free: true },
  { id: "groq", name: "Groq", models: ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"], free: true },
  { id: "deepseek", name: "DeepSeek", models: ["deepseek-flash", "deepseek-v4-pro"], free: false },
  { id: "mistral", name: "Mistral", models: ["mistral-large-latest", "codestral-latest"], free: false },
  { id: "zai", name: "Z.ai", models: ["glm-5.3"], free: false },
];
