import { useRef, useEffect, useState } from "react";
import { Send, Square, Zap } from "lucide-react";
import ReactMarkdown from "react-markdown";
import clsx from "clsx";
import type { ChatMessage } from "@/types";

interface ChatViewProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  tokensSaved: number;
  error: string | null;
  onSend: (content: string) => void;
}

export function ChatView({ messages, isStreaming, tokensSaved, error, onSend }: ChatViewProps) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;
    onSend(input);
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-gray-950">
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
            {messages.map((msg, i) => (
              <MessageBubble key={i} message={msg} isStreaming={isStreaming && i === messages.length - 1} />
            ))}
            {error && (
              <div className="px-4 py-3 rounded-lg bg-red-950/50 border border-red-900 text-red-400 text-sm">
                {error}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-gray-800 bg-gray-900/50 backdrop-blur-sm">
        <div className="max-w-3xl mx-auto px-4 py-4">
          {tokensSaved > 0 && (
            <div className="flex items-center gap-1.5 mb-2 text-xs text-sensei-500">
              <Zap className="w-3 h-3" />
              <span>{tokensSaved.toLocaleString()} tokens saved via compression</span>
            </div>
          )}
          <form onSubmit={handleSubmit} className="flex items-end gap-2">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                placeholder="Send a message..."
                rows={1}
                className="w-full bg-gray-800 text-white text-sm rounded-xl px-4 py-3 border border-gray-700 focus:border-sensei-600 focus:outline-none resize-none scrollbar-thin"
                style={{ minHeight: "44px", maxHeight: "200px" }}
                disabled={isStreaming}
              />
            </div>
            <button
              type="submit"
              disabled={!input.trim() || isStreaming}
              className={clsx(
                "p-3 rounded-xl transition-colors",
                isStreaming
                  ? "bg-gray-700 text-gray-500"
                  : "bg-sensei-600 hover:bg-sensei-700 text-white"
              )}
            >
              {isStreaming ? <Square className="w-4 h-4" /> : <Send className="w-4 h-4" />}
            </button>
          </form>
          <p className="text-xs text-gray-600 mt-2 text-center">
            Sensei can make mistakes. Verify important information.
          </p>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message, isStreaming }: { message: ChatMessage; isStreaming: boolean }) {
  const isUser = message.role === "user";

  return (
    <div className={clsx("flex gap-3", isUser ? "flex-row-reverse" : "flex-row")}>
      <div
        className={clsx(
          "w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center text-sm font-bold",
          isUser ? "bg-blue-600 text-white" : "bg-sensei-600 text-white"
        )}
      >
        {isUser ? "U" : "S"}
      </div>
      <div
        className={clsx(
          "flex-1 max-w-[85%] rounded-xl px-4 py-3",
          isUser
            ? "bg-blue-950/40 border border-blue-900/50"
            : "bg-gray-900 border border-gray-800"
        )}
      >
        {isUser ? (
          <p className="text-sm text-gray-200 whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none text-gray-200">
            <ReactMarkdown>{message.content || (isStreaming ? "▌" : "")}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-4">
      <div className="w-16 h-16 rounded-2xl bg-sensei-600 flex items-center justify-center mb-4">
        <span className="text-white font-bold text-3xl">S</span>
      </div>
      <h2 className="text-xl font-bold text-white mb-2">Welcome to Sensei</h2>
      <p className="text-gray-500 max-w-md">
        Self-hosted AI workspace with token compression, powered by GLM-5.2.
        Start a conversation to see the compression pipeline in action.
      </p>
      <div className="grid grid-cols-3 gap-3 mt-8 max-w-lg">
        <FeatureCard icon="Zap" title="60-95% Token Reduction" desc="Smart compression pipeline" />
        <FeatureCard icon="Cpu" title="Local + API" desc="GPU or cloud serving" />
        <FeatureCard icon="MessageSquare" title="Persistent Memory" desc="Cross-session context" />
      </div>
    </div>
  );
}

function FeatureCard({ icon, title, desc }: { icon: string; title: string; desc: string }) {
  return (
    <div className="p-3 rounded-lg bg-gray-900 border border-gray-800">
      <p className="text-sm font-semibold text-sensei-400">{title}</p>
      <p className="text-xs text-gray-600 mt-0.5">{desc}</p>
    </div>
  );
}
