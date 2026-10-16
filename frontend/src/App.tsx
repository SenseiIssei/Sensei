import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { History, X } from "lucide-react";
import { ChatView } from "@/components/ChatView";
import { ConversationList } from "@/components/ConversationList";
import { SavingsDashboard } from "@/components/SavingsDashboard";
import { SetupWizard } from "@/components/SetupWizard";
import { IconButton } from "@/components/ui";
import { useChat } from "@/hooks/useChat";
import { api } from "@/lib/api";
import type { Conversation, SetupStatus } from "@/types";

/**
 * Whether Sensei has a provider of its own.
 *
 * Asked once per page load and shared. `null` while unknown — which is also
 * what a backend that is not running looks like, and in that case the
 * connection banner already says so; nothing here stacks a second error on it.
 */
let setupCache: SetupStatus | null = null;

function useSetupStatus(): [SetupStatus | null, () => void] {
  const [status, setStatus] = useState<SetupStatus | null>(setupCache);
  const refresh = useCallback(() => {
    api
      .getSetupStatus()
      .then((s) => {
        setupCache = s;
        setStatus(s);
      })
      .catch(() => setStatus(null));
  }, []);
  useEffect(() => {
    if (!setupCache) refresh();
  }, [refresh]);
  return [status, refresh];
}

/** The landing screen. */
export function OverviewPage() {
  const navigate = useNavigate();
  const [setup] = useSetupStatus();
  return (
    <SavingsDashboard
      needsSetup={Boolean(setup?.needs_setup)}
      onOpenChat={() => navigate("/workspace")}
      onOpenSettings={() => navigate("/settings")}
    />
  );
}

/** Sensei's own chat — the one part that needs a provider of its own. */
export function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [setup, refreshSetup] = useSetupStatus();
  const [setupDismissed, setSetupDismissed] = useState(false);

  const {
    messages,
    isStreaming,
    conversationId,
    tokensSaved,
    error,
    selectedModel,
    sendMessage,
    cancelStreaming,
    clearMessages,
    loadConversation,
    setSelectedModel,
  } = useChat();

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations());
    } catch {
      // Backend not running — the connection banner says so.
    }
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations, conversationId, tokensSaved]);

  const select = useCallback(
    async (id: string) => {
      setHistoryOpen(false);
      try {
        const conv = await api.getConversation(id);
        loadConversation(
          conv.messages.map((m) => ({
            role: m.role as "user" | "assistant" | "system",
            content: m.content,
            timestamp: m.timestamp,
          })),
          id,
        );
      } catch {
        // Gone or unreadable — leave the current view as it is.
      }
    },
    [loadConversation],
  );

  const remove = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        if (conversationId === id) clearMessages();
        refreshConversations();
      } catch {
        // Ignore: the list refreshes on the next change anyway.
      }
    },
    [conversationId, clearMessages, refreshConversations],
  );

  // The wizard belongs in front of the chat, not in front of the dashboard:
  // the gateway forwards whatever credential the calling tool sends and needs
  // no provider of its own, but this chat originates requests and does.
  if (setup?.needs_setup && !setupDismissed) {
    return (
      <SetupWizard
        status={setup}
        onDone={() => {
          setSetupDismissed(true);
          refreshSetup();
        }}
      />
    );
  }

  const list = (
    <ConversationList
      conversations={conversations}
      activeId={conversationId}
      onSelect={select}
      onNew={() => {
        setHistoryOpen(false);
        clearMessages();
      }}
      onDelete={remove}
    />
  );

  return (
    <div className="relative flex h-full">
      <aside className="hidden w-64 shrink-0 border-r border-line md:block">{list}</aside>

      {historyOpen && (
        <div className="absolute inset-0 z-30 md:hidden">
          <button
            aria-label="Close history"
            onClick={() => setHistoryOpen(false)}
            className="absolute inset-0 bg-[var(--scrim)]"
          />
          <aside className="animate-fade-in absolute inset-y-0 left-0 w-72 border-r border-line bg-canvas shadow-pop">
            <IconButton
              label="Close history"
              onClick={() => setHistoryOpen(false)}
              className="absolute right-2 top-2 z-10"
            >
              <X className="h-4 w-4" />
            </IconButton>
            <div className="h-full pt-10">{list}</div>
          </aside>
        </div>
      )}

      <ChatView
        messages={messages}
        isStreaming={isStreaming}
        tokensSaved={tokensSaved}
        error={error}
        selectedModel={selectedModel}
        onSend={sendMessage}
        onCancel={cancelStreaming}
        onSelectModel={setSelectedModel}
        leading={
          <IconButton label="History" className="md:hidden" onClick={() => setHistoryOpen(true)}>
            <History className="h-4 w-4" />
          </IconButton>
        }
      />
    </div>
  );
}
