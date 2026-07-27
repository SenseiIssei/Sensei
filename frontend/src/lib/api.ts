import type {
  Conversation,
  ConversationDetail,
  ModelsResponse,
  ProviderModels,
  SetupStatus,
  StatsResponse,
} from "@/types";

const API_BASE = "/api";

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!resp.ok) {
    throw new Error(`API error ${resp.status}: ${await resp.text()}`);
  }
  return resp.json();
}

export const api = {
  async getModels(): Promise<ModelsResponse> {
    return fetchJSON(`${API_BASE}/models`);
  },

  async getSetupStatus(): Promise<SetupStatus> {
    return fetchJSON(`${API_BASE}/setup/status`);
  },

  async getProviderModels(provider: string): Promise<ProviderModels> {
    return fetchJSON(`${API_BASE}/setup/provider-models/${provider}`);
  },

  async applySettings(update: {
    provider?: string;
    model?: string;
    api_key?: string;
    compression_enabled?: boolean;
  }): Promise<unknown> {
    return fetchJSON(`${API_BASE}/settings`, {
      method: "PUT",
      body: JSON.stringify(update),
    });
  },

  async getStats(): Promise<StatsResponse> {
    return fetchJSON(`${API_BASE}/stats`);
  },

  async listConversations(): Promise<Conversation[]> {
    return fetchJSON(`${API_BASE}/conversations`);
  },

  async getConversation(id: string): Promise<ConversationDetail> {
    return fetchJSON(`${API_BASE}/conversations/${id}`);
  },

  async deleteConversation(id: string): Promise<{ deleted: boolean }> {
    return fetchJSON(`${API_BASE}/conversations/${id}`, { method: "DELETE" });
  },

  async chat(message: string, conversationId?: string, model?: string): Promise<{
    conversation_id: string;
    message: string;
    model: string;
    tokens_saved: number;
    compression_ratio: number;
  }> {
    return fetchJSON(`${API_BASE}/chat`, {
      method: "POST",
      body: JSON.stringify({ message, conversation_id: conversationId, model }),
    });
  },
};
