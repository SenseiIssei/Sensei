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
