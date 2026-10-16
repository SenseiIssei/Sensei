import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, History, LogOut, X } from "lucide-react";
import { authApi } from "@/lib/auth";
import { api } from "@/lib/api";
import { useChat } from "@/hooks/useChat";
import type { Conversation } from "@/types";
import { ChatView } from "@/components/ChatView";
import { ConversationList } from "@/components/ConversationList";
import { IconButton, Logo } from "@/components/ui";

/**
 * The signed-in chat for a shared Sensei — several people on one server, each
 * with their own history (see SENSEI_AUTH_ENABLED, RBAC and OIDC). Same chat
 * as the workspace, with who you are and a way to sign out.
 */
export function PublicChat() {
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

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const user = authApi.getUser();

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations());
    } catch {
      // Backend not running.
    }
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations, conversationId, tokensSaved]);

  const select = async (id: string) => {
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
      // Gone or unreadable.
    }
  };

  const remove = async (id: string) => {
    try {
      await api.deleteConversation(id);
      if (conversationId === id) clearMessages();
      refreshConversations();
    } catch {
      // The list refreshes on the next change anyway.
    }
  };

  const logout = () => {
    authApi.logout();
    window.location.reload();
  };

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
      footer={
        <div className="flex items-center gap-2 border-t border-line p-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-raised text-xs font-semibold text-fg">
            {(user?.name || "?").slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium text-fg">{user?.name || "Signed in"}</p>
            <p className="truncate text-xs text-muted">{user?.email}</p>
          </div>
          <IconButton label="Sign out" onClick={logout}>
            <LogOut className="h-4 w-4" />
          </IconButton>
        </div>
      }
    />
  );

  return (
    <div className="relative flex h-dvh w-full overflow-hidden bg-canvas">
      <aside className="hidden w-72 shrink-0 flex-col border-r border-line bg-canvas-deep md:flex">
        <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
          <Link to="/" aria-label="Back to Sensei" className="text-muted hover:text-fg">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <Logo className="h-6 w-6" />
          <span className="text-[15px] font-semibold text-fg">Shared chat</span>
        </div>
        <div className="min-h-0 flex-1">{list}</div>
      </aside>

      {historyOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            aria-label="Close history"
            onClick={() => setHistoryOpen(false)}
            className="absolute inset-0 bg-[var(--scrim)]"
          />
          <aside className="animate-fade-in absolute inset-y-0 left-0 w-72 border-r border-line bg-canvas-deep shadow-pop">
            <IconButton label="Close history" onClick={() => setHistoryOpen(false)} className="absolute right-2 top-2 z-10">
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
