import { useState, useEffect, useCallback } from "react";
import { Menu } from "lucide-react";
import { Sidebar, StatsPanel, SettingsPanel } from "@/components/Sidebar";
import { ChatView } from "@/components/ChatView";
import { SetupWizard } from "@/components/SetupWizard";
import { SavingsDashboard } from "@/components/SavingsDashboard";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { useChat } from "@/hooks/useChat";
import { api } from "@/lib/api";
import type { Conversation, SetupStatus } from "@/types";

export default function App({ initialView = "savings" }: { initialView?: "savings" | "chat" } = {}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [showStats, setShowStats] = useState(false);
  const [showSavings, setShowSavings] = useState(initialView === "savings");
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

  // The wizard belongs in front of the chat, not in front of the dashboard.
  //
  // It used to preempt everything as soon as the setup probe came back, which
  // on this machine took 2.7 seconds: you landed on your savings, read them,
  // and then the wizard dropped on top. Two separate faults in one behaviour.
  //
  // The flash is the smaller one. The real error is the premise — `needs_setup`
  // means "no provider of Sensei's own", and the gateway does not need one. It
  // forwards whatever credential the calling tool sent, so a Claude Code or
  // Copilot subscription routes through it with nothing configured here. The
  // parts that originate a request rather than relay one — the chat, RAG, the
  // agent — are the ones that need a key, so that is where the wizard goes.
  const needsSetup = Boolean(setup?.needs_setup) && !setupDismissed;
  if (needsSetup && !showSavings) {
    return <SetupWizard status={setup!} onDone={handleSetupDone} />;
  }

  // Savings is the landing view, not something you click through the chat to
  // find. It is the reason the product exists and the only screen that changes
  // on its own; the chat is a feature of it rather than the other way round.
  if (showSavings) {
    return (
      <SavingsDashboard
        needsSetup={needsSetup}
        onOpenChat={() => setShowSavings(false)}
        onOpenSettings={() => {
          setShowSavings(false);
          setShowSettings(true);
        }}
      />
    );
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
          onOpenSavings={() => {
            setSidebarOpen(false);
            setShowSavings(true);
          }}
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
