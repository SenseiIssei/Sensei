import { useState, useEffect, useCallback } from "react";
import { Menu } from "lucide-react";
import { Sidebar, StatsPanel, SettingsPanel } from "@/components/Sidebar";
import { ChatView } from "@/components/ChatView";
import { SetupWizard } from "@/components/SetupWizard";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { useChat } from "@/hooks/useChat";
import { api } from "@/lib/api";
import type { Conversation, SetupStatus } from "@/types";

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [showStats, setShowStats] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [setup, setSetup] = useState<SetupStatus | null>(null);
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
      const convs = await api.listConversations();
      setConversations(convs);
    } catch {
      // Backend might not be running
    }
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations, conversationId, tokensSaved]);

  // Ask once on load whether there is anything to talk to. A failure here means
  // the backend isn't up, which the chat view already reports — don't stack a
  // second error screen on top of it.
  useEffect(() => {
    api
      .getSetupStatus()
      .then(setSetup)
      .catch(() => setSetup(null));
  }, []);

  const handleSetupDone = useCallback(() => {
    setSetupDismissed(true);
    api.getSetupStatus().then(setSetup).catch(() => undefined);
  }, []);

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

  if (setup?.needs_setup && !setupDismissed) {
    return <SetupWizard status={setup} onDone={handleSetupDone} />;
  }

  return (
    <div className="relative flex h-dvh w-full overflow-hidden">
      <ConnectionBanner />
      {/* Below `md` the sidebar is a drawer; the backdrop closes it. */}
      {sidebarOpen && (
        <button
          aria-label="Close menu"
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
        />
      )}
      <div
        className={
          "fixed inset-y-0 left-0 z-40 transition-transform md:static md:translate-x-0 " +
          (sidebarOpen ? "translate-x-0" : "-translate-x-full")
        }
      >
        <Sidebar
          conversations={conversations}
          activeConversationId={conversationId}
          onSelectConversation={(id) => {
            setSidebarOpen(false);
            return handleSelectConversation(id);
          }}
          onNewChat={() => {
            setSidebarOpen(false);
            handleNewChat();
          }}
          onDeleteConversation={handleDeleteConversation}
          onOpenSettings={() => setShowSettings(true)}
          onOpenStats={() => setShowStats(true)}
          tokensSaved={tokensSaved}
        />
      </div>

      <button
        onClick={() => setSidebarOpen(true)}
        aria-label="Open menu"
        className="fixed left-3 top-3 z-20 rounded-lg glass p-2 text-gray-300 md:hidden"
      >
        <Menu className="h-5 w-5" />
      </button>

      <ChatView
        messages={messages}
        isStreaming={isStreaming}
        tokensSaved={tokensSaved}
        error={error}
        selectedModel={selectedModel}
        onSend={sendMessage}
        onCancel={cancelStreaming}
        onSelectModel={setSelectedModel}
      />
      <StatsPanel open={showStats} onClose={() => setShowStats(false)} />
      <SettingsPanel open={showSettings} onClose={() => setShowSettings(false)} />
    </div>
  );
}
