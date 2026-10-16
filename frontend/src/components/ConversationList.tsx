import { useState } from "react";
import { MessageSquarePlus, Search, Trash2 } from "lucide-react";
import clsx from "clsx";
import type { Conversation } from "@/types";
import { Button } from "@/components/ui";

/** Chat history: new chat, search, and the list. Shared by both chat screens. */
export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  footer,
}: {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  footer?: React.ReactNode;
}) {
  const [search, setSearch] = useState("");
  const shown = conversations.filter((c) => c.title.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 p-3">
        <Button variant="primary" className="w-full" onClick={onNew}>
          <MessageSquarePlus className="h-4 w-4" />
          New chat
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search conversations"
            aria-label="Search conversations"
            className="h-8 w-full rounded-full border border-line bg-surface pl-8 pr-3 text-[13px] text-fg outline-none transition-shadow placeholder:text-faint focus:border-accent focus:shadow-[var(--glow-accent)]"
          />
        </div>
      </div>

      <p className="eyebrow px-5 pb-1 text-faint">History</p>
      <div className="flex-1 overflow-y-auto px-2 pb-2 scrollbar-thin">
        {shown.length === 0 && (
          <p className="px-3 py-4 text-center text-xs text-faint">
            {search ? "No matches" : "No conversations yet"}
          </p>
        )}
        {shown.map((conv) => (
          <div
            key={conv.id}
            className={clsx(
              "group flex h-9 cursor-pointer items-center gap-2 rounded-sm px-3 transition-colors",
              activeId === conv.id ? "bg-raised text-fg" : "text-muted hover:bg-hover hover:text-fg",
            )}
            onClick={() => onSelect(conv.id)}
          >
            <span className="flex-1 truncate text-[13px]">{conv.title}</span>
            <button
              aria-label={`Delete ${conv.title}`}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(conv.id);
              }}
              className="shrink-0 text-faint opacity-0 transition-opacity hover:text-danger group-hover:opacity-100 focus:opacity-100"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
      {footer}
    </div>
  );
}
