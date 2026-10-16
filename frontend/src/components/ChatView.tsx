import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Check,
  ChevronDown,
  Copy,
  FileText,
  Image as ImageIcon,
  Paperclip,
  Square,
  X,
  Zap,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import clsx from "clsx";
import type { ChatMessage, FileReference } from "@/types";
import { PROVIDERS as PROVIDER_LIST } from "@/types";
import { Logo } from "@/components/ui";

interface ChatViewProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  tokensSaved: number;
  error: string | null;
  selectedModel?: string;
  onSend: (content: string, model?: string, files?: FileReference[]) => void;
  onCancel: () => void;
  onSelectModel: (model: string) => void;
  /** Rendered at the left of the top bar — the history toggle on small screens. */
  leading?: React.ReactNode;
}

export function ChatView({
  messages,
  isStreaming,
  tokensSaved,
  error,
  selectedModel,
  onSend,
  onCancel,
  onSelectModel,
  leading,
}: ChatViewProps) {
  const [input, setInput] = useState("");
  const [files, setFiles] = useState<FileReference[]>([]);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
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
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, window.innerHeight * 0.4) + "px";
  };

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    setFiles((prev) => [
      ...prev,
      ...selected.map((f) => ({ id: `${Date.now()}-${f.name}`, name: f.name, type: f.type, size: f.size })),
    ]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const copyMessage = (content: string, idx: number) => {
    void navigator.clipboard?.writeText(content);
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
    <div className="flex h-full min-w-0 flex-1 flex-col">
      {/* Top bar */}
      <div className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line px-4">
        <div className="flex min-w-0 items-center gap-2">
          {leading}
          <div className="relative min-w-0">
            <button
              onClick={() => setShowModelPicker(!showModelPicker)}
              aria-expanded={showModelPicker}
              className="flex h-8 min-w-0 items-center gap-2 rounded-sm px-2.5 text-[13px] font-medium text-fg-secondary transition-colors hover:bg-hover hover:text-fg"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-success" />
              <span className="truncate">{currentModelName()}</span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-faint" />
            </button>
            {showModelPicker && (
              <div className="animate-fade-in absolute left-0 top-full z-50 mt-1 max-h-96 w-80 overflow-y-auto rounded-md border border-line bg-surface p-1 shadow-pop scrollbar-thin">
                <button
                  onClick={() => {
                    onSelectModel("");
                    setShowModelPicker(false);
                  }}
                  className="flex h-8 w-full items-center gap-2 rounded-xs px-2.5 text-[13px] text-fg hover:bg-hover"
                >
                  Auto-detect
                  <span className="ml-auto text-xs text-faint">Recommended</span>
                </button>
                {PROVIDER_LIST.map((provider) => (
                  <div key={provider.id} className="mt-1">
                    <div className="eyebrow flex items-center gap-2 px-2.5 py-1.5 text-faint">
                      {provider.name}
                      {provider.free && <span className="text-success">free</span>}
                    </div>
                    {provider.models.map((model) => (
                      <button
                        key={model}
                        onClick={() => {
                          onSelectModel(model);
                          setShowModelPicker(false);
                        }}
                        className={clsx(
                          "flex h-8 w-full items-center gap-2 rounded-xs px-2.5 font-mono text-[12px] transition-colors",
                          selectedModel === model ? "bg-accent-soft text-accent-soft-fg" : "text-fg-secondary hover:bg-hover",
                        )}
                      >
                        {model}
                        {selectedModel === model && <Check className="ml-auto h-3.5 w-3.5" />}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        {tokensSaved > 0 && (
          <div className="num flex shrink-0 items-center gap-1.5 text-xs font-medium text-gold-text">
            <Zap className="h-3.5 w-3.5" />
            <span>{tokensSaved.toLocaleString()} tokens saved</span>
          </div>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="mx-auto w-full max-w-[760px] space-y-6 px-4 py-8">
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
              <div className="rounded-md border border-danger/25 bg-danger/10 px-4 py-3 text-[13px] text-danger">
                {error}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="shrink-0 px-4 pb-4">
        <div className="mx-auto w-full max-w-[760px]">
          {files.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {files.map((f) => (
                <div
                  key={f.id}
                  className="flex items-center gap-2 rounded-sm border border-line bg-surface px-2.5 py-1 text-xs text-fg-secondary"
                >
                  {f.type.startsWith("image/") ? <ImageIcon className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}
                  <span className="max-w-32 truncate">{f.name}</span>
                  <button
                    aria-label={`Remove ${f.name}`}
                    onClick={() => setFiles((prev) => prev.filter((x) => x.id !== f.id))}
                    className="text-faint hover:text-danger"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <form
            onSubmit={handleSubmit}
            className="flex items-end gap-1 rounded-lg border border-line bg-surface p-1.5 shadow-pop transition-colors focus-within:border-accent dark:border-line-strong dark:shadow-none dark:focus-within:border-accent"
          >
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
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-muted transition-colors hover:bg-hover hover:text-fg"
              title="Attach files"
              aria-label="Attach files"
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              placeholder="Send a message to Sensei..."
              aria-label="Message"
              rows={1}
              className="max-h-[40vh] min-h-8 flex-1 resize-none bg-transparent px-1.5 py-1.5 text-[15px] leading-5 text-fg outline-none placeholder:text-faint scrollbar-thin"
              disabled={isStreaming}
            />
            {isStreaming ? (
              <button
                type="button"
                onClick={onCancel}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm bg-raised text-fg transition-colors hover:bg-pressed"
                title="Stop generating"
                aria-label="Stop generating"
              >
                <Square className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                aria-label="Send"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm bg-accent text-accent-fg transition-colors hover:bg-accent-hover disabled:bg-raised disabled:text-faint"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
            )}
          </form>
          <p className="mt-2 text-center text-xs text-faint">
            Enter to send · Shift+Enter for a new line · answers can be wrong, check what matters
          </p>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  isStreaming,
  onCopy,
  copied,
}: {
  message: ChatMessage;
  isStreaming: boolean;
  onCopy: () => void;
  copied: boolean;
}) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="group flex flex-col items-end">
        {message.files && message.files.length > 0 && <Attachments files={message.files} />}
        <div className="max-w-[80%] rounded-lg rounded-br-xs bg-accent-soft px-3.5 py-2.5 text-[15px] leading-6 text-fg dark:text-fg">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="group flex gap-3">
      <Logo className="mt-0.5 h-6 w-6 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="prose max-w-none">
          {message.content ? (
            <ReactMarkdown>{message.content}</ReactMarkdown>
          ) : (
            isStreaming && <span className="streaming-caret" />
          )}
        </div>
        {!isStreaming && message.content && (
          <div className="mt-1.5 flex items-center gap-2 font-mono text-[11px] text-faint opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
            <button
              onClick={onCopy}
              className="rounded-xs p-1 text-faint transition-colors hover:bg-hover hover:text-fg"
              title="Copy"
              aria-label="Copy"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
            {message.model && <span>{message.model}</span>}
            {message.tokensSaved != null && message.tokensSaved > 0 && (
              <span className="text-gold-text">{message.tokensSaved} saved</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Attachments({ files }: { files: FileReference[] }) {
  return (
    <div className="mb-2 flex flex-wrap gap-2">
      {files.map((f) => (
        <div
          key={f.id}
          className="flex items-center gap-1.5 rounded-sm border border-line bg-surface px-2.5 py-1 text-xs text-muted"
        >
          {f.type.startsWith("image/") ? <ImageIcon className="h-3 w-3" /> : <FileText className="h-3 w-3" />}
          {f.name}
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <Logo className="mb-5 h-12 w-12" />
      <h2 className="text-xl font-semibold tracking-[-0.01em] text-fg">Welcome to Sensei</h2>
      <p className="mt-2 max-w-md text-[13px] leading-5 text-muted">
        Every message is compressed before it leaves this machine. Ask anything — the saving shows
        up above and on the overview.
      </p>
      <div className="mt-8 grid w-full max-w-lg gap-3 sm:grid-cols-3">
        <FeatureCard title="Fewer tokens" desc="JSON, logs and prose, compressed" />
        <FeatureCard title="Any model" desc="Claude, GPT, Gemini, or local" />
        <FeatureCard title="Stays local" desc="No telemetry, keys encrypted" />
      </div>
    </div>
  );
}

function FeatureCard({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3 text-left">
      <p className="text-[13px] font-semibold text-fg">{title}</p>
      <p className="mt-0.5 text-xs text-muted">{desc}</p>
    </div>
  );
}
