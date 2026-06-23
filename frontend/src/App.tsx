import { useState, useEffect, useCallback } from "react";
import { Sidebar, StatsPanel, SettingsPanel } from "@/components/Sidebar";
import { ChatView } from "@/components/ChatView";
import { useChat } from "@/hooks/useChat";
import { api } from "@/lib/api";
import type { Conversation } from "@/types";

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [showStats, setShowStats] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const {
    messages,
    isStreaming,
    conversationId,
    tokensSaved,
    error,
    sendMessage,
    clearMessages,
    loadConversation,
  } = useChat();

  const refreshConversations = useCallback(async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch {
      // Backend might not be running
    }
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations, conversationId, tokensSaved]);

  const handleNewChat = useCallback(() => {
    clearMessages();
  }, [clearMessages]);

  const handleSelectConversation = useCallback(
    async (id: string) => {
      try {
        const conv = await api.getConversation(id);
        loadConversation(
          conv.messages.map((m) => ({
            role: m.role as "user" | "assistant" | "system",
            content: m.content,
            timestamp: m.timestamp,
          })),
          id
        );
      } catch {
        // Error loading conversation
      }
    },
    [loadConversation]
  );

  const handleDeleteConversation = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        if (conversationId === id) {
          clearMessages();
        }
        refreshConversations();
      } catch {
        // Error deleting
      }
    },
    [conversationId, clearMessages, refreshConversations]
  );

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar
        conversations={conversations}
        activeConversationId={conversationId}
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        onDeleteConversation={handleDeleteConversation}
        onOpenSettings={() => setShowSettings(true)}
        onOpenStats={() => setShowStats(true)}
        tokensSaved={tokensSaved}
      />
      <ChatView
        messages={messages}
        isStreaming={isStreaming}
        tokensSaved={tokensSaved}
        error={error}
        onSend={sendMessage}
      />
      <StatsPanel open={showStats} onClose={() => setShowStats(false)} />
      <SettingsPanel open={showSettings} onClose={() => setShowSettings(false)} />
    </div>
  );
}
