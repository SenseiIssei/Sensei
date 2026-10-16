import type {
  Conversation,
  ConversationDetail,
  ModelsResponse,
  ProviderModels,
  SavingsResponse,
  SetupStatus,
  StatsResponse,
  ToolOutcome,
  ToolsResponse,
  UpdateStatus,
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

  async getTools(): Promise<ToolsResponse> {
    return fetchJSON(`${API_BASE}/setup/tools`);
  },

  /** Every detected tool now, and new ones as they appear. */
  async connectAllTools(): Promise<{ outcomes: ToolOutcome[] }> {
    return fetchJSON(`${API_BASE}/setup/tools/connect`, { method: "POST", body: "{}" });
  },

  /** Put every file back, and stop connecting new tools. */
  async disconnectAllTools(): Promise<{ outcomes: ToolOutcome[] }> {
    return fetchJSON(`${API_BASE}/setup/tools/disconnect`, { method: "POST", body: "{}" });
  },

  async connectTool(id: string): Promise<{ outcomes: ToolOutcome[] }> {
    return fetchJSON(`${API_BASE}/setup/tools/${encodeURIComponent(id)}/connect`, {
      method: "POST",
    });
  },

  async disconnectTool(id: string): Promise<{ outcomes: ToolOutcome[] }> {
    return fetchJSON(`${API_BASE}/setup/tools/${encodeURIComponent(id)}/disconnect`, {
      method: "POST",
    });
  },

  async setToolRoute(id: string, enabled: boolean): Promise<{ outcomes: ToolOutcome[] }> {
    return fetchJSON(`${API_BASE}/setup/tools/${encodeURIComponent(id)}/route`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    });
  },

  async setAutoConnect(enabled: boolean): Promise<{ enabled: boolean }> {
    return fetchJSON(`${API_BASE}/setup/tools/auto-connect`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    });
  },

  /** `force` asks GitHub now; without it the server only answers from its
   *  daily check, and makes no request at all unless SENSEI_UPDATE_CHECK is on. */
  async getUpdateStatus(force = false): Promise<UpdateStatus> {
    return fetchJSON(`${API_BASE}/maintenance/update${force ? "?force=true" : ""}`);
  },

  async getStats(): Promise<StatsResponse> {
    return fetchJSON(`${API_BASE}/stats`);
  },

  async getSavings(): Promise<SavingsResponse> {
    return fetchJSON(`${API_BASE}/stats/savings`);
  },

  async forgetSavings(): Promise<{ ok: boolean; message: string }> {
    return fetchJSON(`${API_BASE}/stats/savings/forget`, { method: "POST" });
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
