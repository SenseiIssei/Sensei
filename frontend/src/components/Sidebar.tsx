import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  MessageSquarePlus,
  Trash2,
  MessageSquare,
  Settings,
  BarChart3,
  Cpu,
  Zap,
  X,
  Search,
  MessageCircle,
  FolderClosed,
  ChevronDown,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Conversation } from "@/types";
import clsx from "clsx";

interface SidebarProps {
  conversations: Conversation[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewChat: () => void;
  onDeleteConversation: (id: string) => void;
  onOpenSettings: () => void;
  onOpenStats: () => void;
  tokensSaved: number;
}

export function Sidebar({
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  onOpenSettings,
  onOpenStats,
  tokensSaved,
}: SidebarProps) {
  const [models, setModels] = useState<{ id: string; name: string; status: string }[]>([]);
  const [search, setSearch] = useState("");
  const [jakobsOpen, setJakobsOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api.getModels().then((data) => {
      setModels(data.models.map((m) => ({ id: m.id, name: m.name, status: m.status })));
    }).catch(() => {});
  }, []);

  const filteredConversations = conversations.filter(c =>
    c.title.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="w-72 glass border-r border-gray-800/50 flex flex-col h-full">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-gray-800/50">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-sensei-600 flex items-center justify-center glow-text">
            <span className="text-white font-bold text-lg">S</span>
          </div>
          <div>
            <h1 className="font-bold text-lg text-white">Sensei</h1>
            <p className="text-xs text-gray-500">14+ providers · Self-hosted</p>
          </div>
        </div>
      </div>

      {/* Jakobs Stuff */}
      <div className="p-3 border-b border-gray-800/50">
        <button
          onClick={() => setJakobsOpen(!jakobsOpen)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg glass glass-hover text-gray-300 hover:text-white transition-colors text-sm font-medium"
        >
          <FolderClosed className="w-4 h-4" />
          Jakobs Stuff
          <ChevronDown className={clsx("w-3.5 h-3.5 ml-auto transition-transform", jakobsOpen && "rotate-180")} />
        </button>
        {jakobsOpen && (
          <div className="mt-2 ml-2 space-y-1">
            <button
              onClick={() => navigate("/chat")}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-white/5 hover:text-white transition-colors text-sm"
            >
              <MessageCircle className="w-4 h-4" />
              Chat
            </button>
          </div>
        )}
      </div>

      {/* New Chat */}
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg bg-sensei-600 hover:bg-sensei-700 text-white font-medium transition-colors"
        >
          <MessageSquarePlus className="w-4 h-4" />
          New Chat
        </button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-600" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search conversations..."
            className="w-full glass text-sm text-gray-300 rounded-lg pl-8 pr-3 py-2 border border-gray-700/50 focus:border-sensei-600/50 focus:outline-none"
          />
        </div>
      </div>

      {/* Conversations */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-2">
        <div className="space-y-1">
          {filteredConversations.length === 0 && (
            <p className="text-xs text-gray-600 px-3 py-4 text-center">
              {search ? "No matches found" : "No conversations yet"}
            </p>
          )}
          {filteredConversations.map((conv) => (
            <div
              key={conv.id}
              className={clsx(
                "group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors",
                activeConversationId === conv.id
                  ? "glass text-white"
                  : "text-gray-400 hover:bg-white/5"
              )}
              onClick={() => onSelectConversation(conv.id)}
            >
              <MessageSquare className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm truncate flex-1">{conv.title}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteConversation(conv.id);
                }}
                className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition-opacity"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Token Savings Badge */}
      <div className="px-3 py-2 border-t border-gray-800/50">
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg glass">
          <Zap className="w-4 h-4 text-sensei-400" />
          <div className="flex-1">
            <p className="text-xs text-gray-500">Tokens Saved</p>
            <p className="text-sm font-semibold text-sensei-400">
              {tokensSaved.toLocaleString()}
            </p>
          </div>
        </div>
      </div>

      {/* Model Status */}
      <div className="px-3 py-2 border-t border-gray-800/50">
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg glass">
          <Cpu className="w-4 h-4 text-gray-400" />
          <div className="flex-1 min-w-0">
            <p className="text-xs text-gray-500">Model</p>
            <p className="text-sm text-gray-300 truncate">
              {models.length > 0 ? models[0].name : "Loading..."}
            </p>
          </div>
          <span
            className={clsx(
              "w-2 h-2 rounded-full",
              models.length > 0 && models[0].status === "available"
                ? "bg-sensei-500"
                : "bg-gray-600"
            )}
          />
        </div>
      </div>

      {/* Bottom Actions */}
      <div className="p-3 border-t border-gray-800/50 flex gap-2">
        <button
          onClick={onOpenStats}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg glass glass-hover text-gray-400 hover:text-white transition-colors text-sm"
        >
          <BarChart3 className="w-4 h-4" />
          Stats
        </button>
        <button
          onClick={onOpenSettings}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg glass glass-hover text-gray-400 hover:text-white transition-colors text-sm"
        >
          <Settings className="w-4 h-4" />
          Settings
        </button>
      </div>
    </div>
  );
}

// ── Stats Panel ─────────────────────────────────────────────

interface StatsPanelProps {
  open: boolean;
  onClose: () => void;
}

export function StatsPanel({ open, onClose }: StatsPanelProps) {
  const [stats, setStats] = useState<{
    compression_enabled: boolean;
    ccr: {
      total_entries: number;
      active_entries: number;
      total_original_bytes: number;
      total_compressed_bytes: number;
      space_saved_bytes: number;
    };
    evicted_entries: number;
    cache_ttl_hours: number;
  } | null>(null);

  useEffect(() => {
    if (open) {
      api.getStats().then(setStats).catch(() => {});
    }
  }, [open]);

  if (!open) return null;

  const ratio = stats?.ccr.total_original_bytes
    ? ((stats.ccr.space_saved_bytes / stats.ccr.total_original_bytes) * 100).toFixed(1)
    : "0";

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-gray-900 rounded-xl border border-gray-800 w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-sensei-400" />
            Compression Stats
          </h2>
          <button onClick={onClose} className="text-gray-500 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {stats ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50">
              <span className="text-sm text-gray-400">Compression</span>
              <span
                className={clsx(
                  "text-sm font-semibold",
                  stats.compression_enabled ? "text-sensei-400" : "text-gray-500"
                )}
              >
                {stats.compression_enabled ? "Enabled" : "Disabled"}
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50">
              <span className="text-sm text-gray-400">CCR Entries</span>
              <span className="text-sm font-semibold text-white">
                {stats.ccr.active_entries} / {stats.ccr.total_entries}
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50">
              <span className="text-sm text-gray-400">Original Size</span>
              <span className="text-sm font-semibold text-white">
                {(stats.ccr.total_original_bytes / 1024).toFixed(1)} KB
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50">
              <span className="text-sm text-gray-400">Compressed Size</span>
              <span className="text-sm font-semibold text-white">
                {(stats.ccr.total_compressed_bytes / 1024).toFixed(1)} KB
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-sensei-900/30 border border-sensei-800/50">
              <span className="text-sm text-sensei-300">Space Saved</span>
              <div className="text-right">
                <p className="text-sm font-bold text-sensei-400">
                  {(stats.ccr.space_saved_bytes / 1024).toFixed(1)} KB
                </p>
                <p className="text-xs text-sensei-500">{ratio}% reduction</p>
              </div>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50">
              <span className="text-sm text-gray-400">Cache TTL</span>
              <span className="text-sm font-semibold text-white">
                {stats.cache_ttl_hours}h
              </span>
            </div>
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">Loading stats...</p>
        )}
      </div>
    </div>
  );
}

// ── Settings Panel ──────────────────────────────────────────

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-gray-900 rounded-xl border border-gray-800 w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Settings className="w-5 h-5 text-sensei-400" />
            Settings
          </h2>
          <button onClick={onClose} className="text-gray-500 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-sm text-gray-400 block mb-1">System Prompt</label>
            <textarea
              className="w-full bg-gray-800 text-white text-sm rounded-lg p-3 border border-gray-700 focus:border-sensei-600 focus:outline-none resize-none"
              rows={3}
              placeholder="You are Sensei, a helpful AI assistant..."
              defaultValue="You are Sensei, a helpful AI assistant powered by GLM-5.2. Be concise and accurate."
            />
          </div>

          <div>
            <label className="text-sm text-gray-400 block mb-1">Temperature: 0.7</label>
            <input
              type="range"
              min="0"
              max="2"
              step="0.1"
              defaultValue="0.7"
              className="w-full accent-sensei-600"
            />
          </div>

          <div>
            <label className="text-sm text-gray-400 block mb-1">Max Tokens: 4096</label>
            <input
              type="range"
              min="256"
              max="32768"
              step="256"
              defaultValue="4096"
              className="w-full accent-sensei-600"
            />
          </div>

          <div className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50">
            <span className="text-sm text-gray-400">Token Compression</span>
            <span className="text-sm font-semibold text-sensei-400">Enabled</span>
          </div>

          <div className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50">
            <span className="text-sm text-gray-400">Cross-session Memory</span>
            <span className="text-sm font-semibold text-sensei-400">Enabled</span>
          </div>

          <p className="text-xs text-gray-600 pt-2">
            Settings are configured via environment variables. See{" "}
            <code className="text-gray-500">.env.example</code> for full reference.
          </p>
        </div>
      </div>
    </div>
  );
}
