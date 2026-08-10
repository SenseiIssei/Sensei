export interface ProviderCatalogEntry {
  id: string;
  name: string;
  free: boolean;
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

export interface SavingsTotals {
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

export const PROVIDERS: ProviderOption[] = [
  { id: "ollama", name: "Ollama (Local)", models: ["glm-5.2", "llama3.3", "qwen2.5"], free: true },
  { id: "openrouter", name: "OpenRouter", models: ["zhipuai/glm-5.2", "openai/gpt-4o", "anthropic/claude-3.5-sonnet"], free: true },
  { id: "groq", name: "Groq", models: ["llama-3.3-70b-versatile", "mixtral-8x7b"], free: true },
  { id: "openai", name: "OpenAI", models: ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"], free: false },
  { id: "anthropic", name: "Anthropic", models: ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus"], free: false },
  { id: "google", name: "Google Gemini", models: ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro"], free: true },
  { id: "deepseek", name: "DeepSeek", models: ["deepseek-chat", "deepseek-reasoner"], free: false },
  { id: "mistral", name: "Mistral", models: ["mistral-large-latest", "codestral-latest"], free: false },
  { id: "together", name: "Together AI", models: ["meta-llama/Llama-3.3-70B-Instruct-Turbo"], free: false },
  { id: "huggingface", name: "HuggingFace", models: ["THUDM/glm-5.2-744b"], free: true },
  { id: "zai", name: "Z.ai", models: ["glm-5.2"], free: false },
  { id: "cohere", name: "Cohere", models: ["command-r-plus"], free: false },
  { id: "fireworks", name: "Fireworks AI", models: ["accounts/fireworks/models/llama-v3p3-70b-instruct"], free: false },
  { id: "perplexity", name: "Perplexity", models: ["sonar-pro", "sonar"], free: false },
];
