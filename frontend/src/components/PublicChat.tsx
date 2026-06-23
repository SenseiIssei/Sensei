import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Square, Zap, Paperclip, Copy, Check, ChevronDown, X, FileText, Image as ImageIcon, LogOut, MessageSquarePlus, Menu } from "lucide-react";
import ReactMarkdown from "react-markdown";
import clsx from "clsx";
import { authApi } from "@/lib/auth";
import { api } from "@/lib/api";
import { useChat } from "@/hooks/useChat";
import type { ChatMessage, FileReference, Conversation } from "@/types";
import { PROVIDERS as PROVIDER_LIST } from "@/types";

const WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/chat/ws`;

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
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const user = authApi.getUser();

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

  const handleLogout = () => {
    authApi.logout();
    window.location.reload();
  };

  const handleNewChat = () => {
    clearMessages();
    setSidebarOpen(false);
  };

  const handleSelectConversation = async (id: string) => {
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
      setSidebarOpen(false);
    } catch {
      // Error loading
    }
  };

  const handleDeleteConversation = async (id: string) => {
    try {
      await api.deleteConversation(id);
      if (conversationId === id) clearMessages();
      refreshConversations();
    } catch {
      // Error
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden surreal-bg">
      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/50 z-30 md:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <div className={clsx(
        "fixed md:relative z-40 w-72 glass border-r border-gray-800/50 flex flex-col h-full transition-transform",
        sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
      )}>
        <div className="px-4 py-4 border-b border-gray-800/50 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-sensei-600 flex items-center justify-center glow-text">
              <span className="text-white font-bold text-lg">S</span>
            </div>
            <div>
              <h1 className="font-bold text-lg text-white">Sensei</h1>
              <p className="text-xs text-gray-500">{user?.name || "User"}</p>
            </div>
          </div>
          <button onClick={() => setSidebarOpen(false)} className="md:hidden text-gray-500">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-3">
          <button
            onClick={handleNewChat}
            className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg bg-sensei-600 hover:bg-sensei-700 text-white font-medium transition-colors"
          >
            <MessageSquarePlus className="w-4 h-4" />
            New Chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin px-2">
          <div className="space-y-1">
            {conversations.length === 0 && (
              <p className="text-xs text-gray-600 px-3 py-4 text-center">No conversations yet</p>
            )}
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={clsx(
                  "group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors",
                  conversationId === conv.id ? "glass text-white" : "text-gray-400 hover:bg-white/5"
                )}
                onClick={() => handleSelectConversation(conv.id)}
              >
                <span className="text-sm truncate flex-1">{conv.title}</span>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDeleteConversation(conv.id); }}
                  className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>

        {tokensSaved > 0 && (
          <div className="px-3 py-2 border-t border-gray-800/50">
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg glass">
              <Zap className="w-4 h-4 text-sensei-400" />
              <div className="flex-1">
                <p className="text-xs text-gray-500">Tokens Saved</p>
                <p className="text-sm font-semibold text-sensei-400">{tokensSaved.toLocaleString()}</p>
              </div>
            </div>
          </div>
        )}

        <div className="p-3 border-t border-gray-800/50">
          <button
            onClick={handleLogout}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg glass glass-hover text-gray-400 hover:text-white transition-colors text-sm"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </div>

      {/* Main chat area */}
      <ChatArea
        messages={messages}
        isStreaming={isStreaming}
        tokensSaved={tokensSaved}
        error={error}
        selectedModel={selectedModel}
        onSend={sendMessage}
        onCancel={cancelStreaming}
        onSelectModel={setSelectedModel}
        showModelPicker={showModelPicker}
        setShowModelPicker={setShowModelPicker}
        onMenuClick={() => setSidebarOpen(true)}
      />
    </div>
  );
}

interface ChatAreaProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  tokensSaved: number;
  error: string | null;
  selectedModel?: string;
  onSend: (content: string, model?: string, files?: FileReference[]) => void;
  onCancel: () => void;
  onSelectModel: (model: string) => void;
  showModelPicker: boolean;
  setShowModelPicker: (v: boolean) => void;
  onMenuClick: () => void;
}

function ChatArea({
  messages, isStreaming, tokensSaved, error, selectedModel,
  onSend, onCancel, onSelectModel, showModelPicker, setShowModelPicker, onMenuClick
}: ChatAreaProps) {
  const [input, setInput] = useState("");
  const [files, setFiles] = useState<FileReference[]>([]);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;
    onSend(input, selectedModel, files.length > 0 ? files : undefined);
    setInput("");
    setFiles([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(e); }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    setFiles(prev => [...prev, ...selected.map(f => ({
      id: `${Date.now()}-${f.name}`, name: f.name, type: f.type, size: f.size,
    }))]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const removeFile = (id: string) => setFiles(prev => prev.filter(f => f.id !== id));

  const copyMessage = (content: string, idx: number) => {
    navigator.clipboard.writeText(content);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  const currentModelName = () => {
    if (!selectedModel) return "Auto-detect";
    for (const p of PROVIDER_LIST) {
      if (p.models.includes(selectedModel)) return `${p.name} · ${selectedModel}`;
    }
    return selectedModel;
  };

  return (
    <div className="flex-1 flex flex-col h-full">
      {/* Top bar */}
      <div className="border-b border-gray-800/50 glass px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onMenuClick} className="md:hidden text-gray-400">
            <Menu className="w-5 h-5" />
          </button>
          <div className="relative">
            <button
              onClick={() => setShowModelPicker(!showModelPicker)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg glass glass-hover text-sm text-gray-300 transition-colors"
            >
              <span className="w-2 h-2 rounded-full bg-sensei-500" />
              {currentModelName()}
              <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
            </button>
            {showModelPicker && (
              <div className="absolute top-full left-0 mt-2 w-80 max-h-96 overflow-y-auto scrollbar-thin glass rounded-xl border border-gray-700/50 shadow-2xl z-50">
                <div className="p-2">
                  <button
                    onClick={() => { onSelectModel(""); setShowModelPicker(false); }}
                    className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-white/5 text-sm text-gray-300"
                  >
                    <span className="w-2 h-2 rounded-full bg-sensei-500" />
                    Auto-detect
                    <span className="text-xs text-gray-600 ml-auto">Recommended</span>
                  </button>
                  {PROVIDER_LIST.map(provider => (
                    <div key={provider.id} className="mt-1">
                      <div className="px-3 py-1 text-xs text-gray-500 font-semibold flex items-center gap-2">
                        {provider.name}
                        {provider.free && <span className="text-sensei-500">FREE</span>}
                      </div>
                      {provider.models.map(model => (
                        <button
                          key={model}
                          onClick={() => { onSelectModel(model); setShowModelPicker(false); }}
                          className={clsx(
                            "w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors",
                            selectedModel === model ? "bg-sensei-600/20 text-sensei-400" : "text-gray-400 hover:bg-white/5"
                          )}
                        >
                          {model}
                          {selectedModel === model && <Check className="w-3 h-3 ml-auto" />}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        {tokensSaved > 0 && (
          <div className="flex items-center gap-1.5 text-xs text-sensei-500">
            <Zap className="w-3 h-3" />
            <span>{tokensSaved.toLocaleString()} tokens saved</span>
          </div>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin">
        {messages.length === 0 ? <EmptyState /> : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
            {messages.map((msg, i) => (
              <MessageBubble
                key={i}
                message={msg}
                isStreaming={isStreaming && i === messages.length - 1}
                onCopy={() => copyMessage(msg.content, i)}
                copied={copiedIdx === i}
              />
            ))}
            {error && (
              <div className="px-4 py-3 rounded-lg bg-red-950/30 border border-red-900/50 text-red-400 text-sm">
                {error}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-gray-800/50 glass">
        <div className="max-w-3xl mx-auto px-4 py-4">
          {files.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {files.map(f => (
                <div key={f.id} className="flex items-center gap-2 px-3 py-1.5 rounded-lg glass text-xs text-gray-300">
                  {f.type.startsWith("image/") ? <ImageIcon className="w-3.5 h-3.5" /> : <FileText className="w-3.5 h-3.5" />}
                  <span className="truncate max-w-32">{f.name}</span>
                  <button onClick={() => removeFile(f.id)} className="text-gray-500 hover:text-red-400">
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <form onSubmit={handleSubmit} className="flex items-end gap-2">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={handleFileSelect}
              className="hidden"
              accept="image/*,.pdf,.txt,.md,.py,.js,.ts,.tsx,.jsx,.json,.yaml,.yml,.toml,.cfg,.ini,.sh,.bash,.go,.rs,.java,.c,.cpp,.h,.rb,.php,.sql,.html,.css,.xml"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="p-3 rounded-xl glass glass-hover text-gray-400 transition-colors"
            >
              <Paperclip className="w-4 h-4" />
            </button>
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                placeholder="Send a message to Sensei..."
                rows={1}
                className="w-full glass text-white text-sm rounded-xl px-4 py-3 border border-gray-700/50 focus:border-sensei-600/50 focus:outline-none resize-none scrollbar-thin"
                style={{ minHeight: "44px", maxHeight: "200px" }}
                disabled={isStreaming}
              />
            </div>
            {isStreaming ? (
              <button type="button" onClick={onCancel} className="p-3 rounded-xl bg-gray-700 hover:bg-gray-600 text-white">
                <Square className="w-4 h-4" />
              </button>
            ) : (
              <button type="submit" disabled={!input.trim()} className={clsx(
                "p-3 rounded-xl transition-colors",
                input.trim() ? "bg-sensei-600 hover:bg-sensei-700 text-white" : "bg-gray-800 text-gray-600"
              )}>
                <Send className="w-4 h-4" />
              </button>
            )}
          </form>
          <p className="text-xs text-gray-600 mt-2 text-center">
            Sensei can make mistakes. Verify important information. · Enter to send, Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message, isStreaming, onCopy, copied }: { message: ChatMessage; isStreaming: boolean; onCopy: () => void; copied: boolean }) {
  const isUser = message.role === "user";
  return (
    <div className={clsx("group flex gap-3", isUser ? "flex-row-reverse" : "flex-row")}>
      <div className={clsx(
        "w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center text-sm font-bold",
        isUser ? "bg-blue-600 text-white" : "bg-sensei-600 text-white"
      )}>
        {isUser ? "U" : "S"}
      </div>
      <div className={clsx("flex-1 max-w-[85%]", isUser ? "flex flex-col items-end" : "flex flex-col items-start")}>
        {message.model && !isUser && <div className="text-xs text-gray-600 mb-1 px-1">{message.model}</div>}
        {message.files && message.files.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-2">
            {message.files.map(f => (
              <div key={f.id} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg glass text-xs text-gray-400">
                {f.type.startsWith("image/") ? <ImageIcon className="w-3 h-3" /> : <FileText className="w-3 h-3" />}
                {f.name}
              </div>
            ))}
          </div>
        )}
        <div className={clsx("rounded-xl px-4 py-3", isUser ? "bg-blue-950/30 border border-blue-900/30" : "glass")}>
          {isUser ? (
            <p className="text-sm text-gray-200 whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose prose-sm max-w-none text-gray-200">
              <ReactMarkdown>{message.content || (isStreaming ? "▌" : "")}</ReactMarkdown>
            </div>
          )}
        </div>
        {!isStreaming && message.content && (
          <div className={clsx("flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity", isUser ? "flex-row-reverse" : "flex-row")}>
            <button onClick={onCopy} className="p-1.5 rounded-lg hover:bg-white/5 text-gray-500 hover:text-gray-300">
              {copied ? <Check className="w-3.5 h-3.5 text-sensei-500" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
            {message.tokensSaved != null && message.tokensSaved > 0 && (
              <span className="text-xs text-sensei-600 px-1.5 flex items-center gap-1">
                <Zap className="w-3 h-3" />{message.tokensSaved} saved
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-4">
      <div className="w-16 h-16 rounded-2xl bg-sensei-600 flex items-center justify-center mb-4 glow-text">
        <span className="text-white font-bold text-3xl">S</span>
      </div>
      <h2 className="text-xl font-bold text-white mb-2">Welcome to Sensei</h2>
      <p className="text-gray-500 max-w-md">
        AI workspace with token compression. 14+ providers, privacy-first, zero telemetry.
        Your data stays encrypted and yours. 💚
      </p>
      <div className="grid grid-cols-3 gap-3 mt-8 max-w-lg">
        <div className="p-3 rounded-lg glass">
          <p className="text-sm font-semibold text-sensei-400">64% Token Reduction</p>
          <p className="text-xs text-gray-600 mt-0.5">Smart compression</p>
        </div>
        <div className="p-3 rounded-lg glass">
          <p className="text-sm font-semibold text-sensei-400">14+ Providers</p>
          <p className="text-xs text-gray-600 mt-0.5">OpenAI, Claude, Gemini</p>
        </div>
        <div className="p-3 rounded-lg glass">
          <p className="text-sm font-semibold text-sensei-400">Privacy-First</p>
          <p className="text-xs text-gray-600 mt-0.5">Encrypted, local, private</p>
        </div>
      </div>
    </div>
  );
}
