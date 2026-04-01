"use client";

import { api, getErrorMessage } from "@/lib/api";
import { useChatStore } from "@/stores/chatStore";
import { useToast } from "@/hooks/use-toast";
import type { ChatContentBlock, ChatMessage, SSEEvent } from "@/types";

function buildMarkdownBlock(content: string): ChatContentBlock {
  return { type: "markdown", content };
}

function buildStatusBlock(label: string, tone: "neutral" | "pending" | "success" | "warning" | "error" = "neutral", detail?: string): ChatContentBlock {
  return { type: "status", label, tone, detail };
}

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
    const response = await api.get<{ id: string; title: string | null; created_at: string; updated_at: string }[]>("/chat/conversations");
    setConversations(response.data);
    return response.data;
  }

  async function hydrateConversation(conversationId: string, options?: { setActive?: boolean }) {
    const response = await api.get<ChatMessage[]>(`/chat/history/${conversationId}`);
    if (options?.setActive !== false) {
      setActiveConversationId(conversationId);
    }
    setMessages(
      response.data.map((message) => ({
        ...message,
        content_blocks: message.content_blocks && message.content_blocks.length > 0 ? message.content_blocks : [buildMarkdownBlock(message.content)]
      }))
    );
    return response.data;
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

    try {
      await hydrateConversation(conversationId);
    } catch (error) {
      const message = getErrorMessage(error, "Failed to load the selected conversation.");
      toast({
        title: "History Error",
        description: message
      });
      throw error;
    }
  }

  async function reloadConversation(conversationId: string) {
    try {
      await hydrateConversation(conversationId, { setActive: false });
    } catch {
      // Preserve current UI if background hydration fails.
    }
  }

  async function createConversation() {
    try {
      const response = await api.post<{ id: string }>("/chat/conversations");
      setActiveConversationId(response.data.id);
      setMessages([]);
      await refreshConversations();
      return response.data.id;
    } catch (error) {
      const message = getErrorMessage(error, "Failed to create a new conversation.");
      toast({
        title: "Conversation Error",
        description: message
      });
      throw error;
    }
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
      content_blocks: [buildMarkdownBlock(trimmed)],
      status: "complete",
      created_at: createdAt
    };
    const assistantId = crypto.randomUUID();

    appendMessage(userMessage);
    appendMessage({
      id: assistantId,
      role: "assistant",
      content: "",
      content_blocks: [buildStatusBlock("Thinking", "pending", "The coordinator is working through your request.")],
      status: "streaming",
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
      let didCompleteTurn = false;

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
          if (payload.type === "turn_started") {
            updateMessage(assistantId, {
              turn_id: payload.turn_id ?? undefined
            });
          } else if (payload.type === "token" && payload.content) {
            assistantContent += payload.content;
            updateMessage(assistantId, {
              content: assistantContent,
              status: "streaming",
              content_blocks: [
                buildStatusBlock("Working", "pending", "The agent is preparing the response."),
                buildMarkdownBlock(assistantContent)
              ]
            });
          } else if (payload.type === "approval_pending") {
            updateMessage(assistantId, {
              status: "waiting_approval",
              content: assistantContent,
              content_blocks: [
                buildStatusBlock("Waiting for approval", "pending", "A draft is ready and requires human review."),
                ...(assistantContent ? [buildMarkdownBlock(assistantContent)] : [])
              ],
              metadata: {
                draft_id: payload.draft_id,
                is_waiting_approval: true
              }
            });
            await reloadConversation(conversationId);
          } else if (payload.type === "turn_completed" || payload.type === "done") {
            didCompleteTurn = true;
            await reloadConversation(conversationId);
          } else if (payload.type === "error") {
            const errorText = payload.content || "The chat request failed.";
            updateMessage(assistantId, {
              content: errorText,
              status: "error",
              content_blocks: [buildStatusBlock("Request failed", "error", errorText)]
            });
            toast({
              title: "Chat Error",
              description: errorText
            });
          }
        }
      }

      if (!didCompleteTurn) {
        await reloadConversation(conversationId);
      }

      const assistantMessage = useChatStore.getState().messages.find((messageItem) => messageItem.id === assistantId);
      if (!assistantMessage?.content && (!assistantMessage?.content_blocks || assistantMessage.content_blocks.length === 0)) {
        removeMessage(assistantId);
      }
    } catch (error) {
      removeMessage(assistantId);
      toast({
        title: "Chat Error",
        description: getErrorMessage(error, "The chat request failed.")
      });
      throw error;
    } finally {
      void refreshConversations().catch(() => undefined);
      setStreaming(false);
    }
  }

  return {
    activeConversationId,
    createConversation,
    isStreaming,
    loadConversation,
    refreshConversations,
    reloadConversation,
    sendMessage
  };
}
