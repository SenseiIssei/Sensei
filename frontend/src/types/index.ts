export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
  timestamp?: number;
}

export interface Conversation {
  id: string;
  title: string;
  updated_at: number;
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

export interface StatsResponse {
  compression_enabled: boolean;
  ccr: CCRStats;
  evicted_entries: number;
  cache_ttl_hours: number;
}

export interface WSMeta {
  type: "meta";
  conversation_id: string;
  tokens_saved: number;
  compression_enabled: boolean;
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
