"use client";

import { api } from "@/lib/api";
import { useChatStore } from "@/stores/chatStore";
import { useToast } from "@/hooks/use-toast";
import type { ChatMessage, SSEEvent } from "@/types";

export function useChat() {
  const {
    activeConversationId,
    appendMessage,
    setConversations,
    setActiveConversationId,
    setMessages,
    setStreaming,
    updateMessage,
    removeMessage,
    isStreaming
  } = useChatStore();
  const { toast } = useToast();

  async function refreshConversations() {
    const response = await api.get<{ id: string; title: string | null; created_at: string; updated_at: string }[]>(
      "/chat/conversations"
    );
    setConversations(response.data);
  }

  async function ensureConversationId() {
    if (activeConversationId) {
      return activeConversationId;
    }

    const response = await api.post<{ id: string }>("/chat/conversations");
    setActiveConversationId(response.data.id);
    await refreshConversations();
    return response.data.id;
  }

  async function loadConversation(conversationId: string) {
    if (conversationId === activeConversationId) {
      return;
    }

    const response = await api.get<ChatMessage[]>(`/chat/history/${conversationId}`);
    setActiveConversationId(conversationId);
    setMessages(response.data);
  }

  async function createConversation() {
    const response = await api.post<{ id: string }>("/chat/conversations");
    setActiveConversationId(response.data.id);
    setMessages([]);
    await refreshConversations();
    return response.data.id;
  }

  async function sendMessage(message: string) {
    const trimmed = message.trim();
    if (!trimmed || isStreaming) {
      return;
    }

    const conversationId = await ensureConversationId();
    const createdAt = new Date().toISOString();
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
      created_at: createdAt
    };
    const assistantId = crypto.randomUUID();

    appendMessage(userMessage);
    appendMessage({
      id: assistantId,
      role: "assistant",
      content: "",
      created_at: createdAt
    });
    setStreaming(true);

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/chat/message`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            conversation_id: conversationId,
            message: trimmed
          })
        }
      );

      if (!response.ok || !response.body) {
        throw new Error(`Chat request failed with status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantContent = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        let boundaryIndex = buffer.indexOf("\n\n");
        while (boundaryIndex !== -1) {
          const rawEvent = buffer.slice(0, boundaryIndex).trim();
          buffer = buffer.slice(boundaryIndex + 2);
          boundaryIndex = buffer.indexOf("\n\n");

          const dataLine = rawEvent
            .split("\n")
            .find((line) => line.startsWith("data:"));
          if (!dataLine) {
            continue;
          }

          const payload = JSON.parse(dataLine.slice(5).trim()) as SSEEvent;
          if (payload.type === "token" && payload.content) {
            assistantContent += payload.content;
            updateMessage(assistantId, { content: assistantContent });
          } else if (payload.type === "approval_pending") {
            updateMessage(assistantId, {
              content: assistantContent || "Draft prepared and waiting for approval.",
              metadata: {
                draft_id: payload.draft_id,
                is_waiting_approval: true
              }
            });
          } else if (payload.type === "error") {
            const errorText = payload.content || "The chat request failed.";
            updateMessage(assistantId, { content: errorText });
            toast({
              title: "Chat Error",
              description: errorText
            });
          }
        }
      }

      if (!assistantContent) {
        const assistantMessage = useChatStore.getState().messages.find((message) => message.id === assistantId);
        if (!assistantMessage?.content) {
          removeMessage(assistantId);
        }
      }
    } catch (error) {
      removeMessage(assistantId);
      toast({
        title: "Chat Error",
        description: error instanceof Error ? error.message : "The chat request failed."
      });
      throw error;
    } finally {
      void refreshConversations();
      setStreaming(false);
    }
  }

  return {
    activeConversationId,
    createConversation,
    isStreaming,
    loadConversation,
    refreshConversations,
    sendMessage
  };
}
