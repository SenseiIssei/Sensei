import { useCallback, useRef, useState } from "react";
import type { ChatMessage, FileReference, WSMessage } from "@/types";

const WS_URL = `ws://${window.location.hostname}:7000/api/chat/ws`;

interface UseChatOptions {
  onMeta?: (meta: { conversationId: string; tokensSaved: number; compressionEnabled: boolean }) => void;
}

export function useChat(options?: UseChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [tokensSaved, setTokensSaved] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState<string | undefined>(undefined);
  const wsRef = useRef<WebSocket | null>(null);

  const sendMessage = useCallback(
    (content: string, model?: string, files?: FileReference[]) => {
      if (!content.trim() || isStreaming) return;

      setError(null);
      setIsStreaming(true);

      const userMsg: ChatMessage = { role: "user", content, timestamp: Date.now(), files, model };
      setMessages((prev) => [...prev, userMsg]);

      const assistantMsg: ChatMessage = { role: "assistant", content: "", timestamp: Date.now(), model };
      setMessages((prev) => [...prev, assistantMsg]);

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        const payload: Record<string, unknown> = {
          message: content,
          conversation_id: conversationId,
          model: model || selectedModel,
        };
        if (files && files.length > 0) {
          payload.files = files.map(f => ({ name: f.name, type: f.type, size: f.size }));
        }
        ws.send(JSON.stringify(payload));
      };

      ws.onmessage = (event) => {
        try {
          const data: WSMessage = JSON.parse(event.data);

          switch (data.type) {
            case "meta":
              setConversationId(data.conversation_id);
              setTokensSaved((prev) => prev + data.tokens_saved);
              if (data.model) {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === "assistant") {
                    updated[updated.length - 1] = { ...last, model: data.model, tokensSaved: data.tokens_saved };
                  }
                  return updated;
                });
              }
              options?.onMeta?.({
                conversationId: data.conversation_id,
                tokensSaved: data.tokens_saved,
                compressionEnabled: data.compression_enabled,
              });
              break;
            case "token":
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + data.content,
                  };
                }
                return updated;
              });
              break;
            case "done":
              setIsStreaming(false);
              ws.close();
              break;
            case "error":
              setError(data.content);
              setIsStreaming(false);
              ws.close();
              break;
          }
        } catch {
          // Ignore parse errors
        }
      };

      ws.onerror = () => {
        setError("WebSocket connection error — is the backend running on port 7000?");
        setIsStreaming(false);
      };

      ws.onclose = () => {
        setIsStreaming(false);
      };
    },
    [conversationId, isStreaming, options, selectedModel]
  );

  const cancelStreaming = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setTokensSaved(0);
    setError(null);
  }, []);

  const loadConversation = useCallback(
    (messages: ChatMessage[], id: string) => {
      setMessages(messages);
      setConversationId(id);
      setTokensSaved(0);
      setError(null);
    },
    []
  );

  return {
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
  };
}
