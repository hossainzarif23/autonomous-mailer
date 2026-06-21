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

function buildToolActionBlock(
  label: string,
  state: "running" | "complete" | "waiting" | "error",
  detail?: string,
  toolCallId?: string
): ChatContentBlock {
  return { type: "tool_action", label, state, detail, tool_call_id: toolCallId };
}

function upsertMarkdownBlock(blocks: ChatContentBlock[], content: string): ChatContentBlock[] {
  const markdownBlock = buildMarkdownBlock(content);
  const markdownIndex = blocks.findIndex((block) => block.type === "markdown");

  if (markdownIndex >= 0) {
    return blocks.map((block, index) => (index === markdownIndex ? markdownBlock : block));
  }

  if (!content) {
    return blocks;
  }

  return [...blocks, markdownBlock];
}

function upsertToolActionBlock(
  blocks: ChatContentBlock[],
  label: string,
  state: "running" | "complete" | "waiting" | "error",
  detail?: string,
  toolCallId?: string
): ChatContentBlock[] {
  const toolBlock = buildToolActionBlock(label, state, detail, toolCallId);
  const toolIndex = blocks.findIndex((block) => {
    if (block.type !== "tool_action") {
      return false;
    }

    if (toolCallId && block.tool_call_id) {
      return block.tool_call_id === toolCallId;
    }

    return block.label === label;
  });

  if (toolIndex >= 0) {
    return blocks.map((block, index) => (index === toolIndex ? toolBlock : block));
  }

  const markdownIndex = blocks.findIndex((block) => block.type === "markdown");
  if (markdownIndex >= 0) {
    return [...blocks.slice(0, markdownIndex), toolBlock, ...blocks.slice(markdownIndex)];
  }

  return [...blocks, toolBlock];
}

function mergeStreamingBlocks(
  currentBlocks: ChatContentBlock[] | null | undefined,
  options: {
    statusDetail: string;
    markdownContent: string;
    toolAction?: {
      label: string;
      state: "running" | "complete" | "waiting" | "error";
      detail?: string;
      toolCallId?: string;
    };
  }
): ChatContentBlock[] {
  const preservedBlocks = (currentBlocks ?? []).filter((block) => block.type !== "status");
  const toolMergedBlocks = options.toolAction
    ? upsertToolActionBlock(
        preservedBlocks,
        options.toolAction.label,
        options.toolAction.state,
        options.toolAction.detail,
        options.toolAction.toolCallId
      )
    : preservedBlocks;
  const contentMergedBlocks = upsertMarkdownBlock(toolMergedBlocks, options.markdownContent);

  return [buildStatusBlock("Working", "pending", options.statusDetail), ...contentMergedBlocks];
}

function mergeApprovalBlocks(
  currentBlocks: ChatContentBlock[] | null | undefined,
  fallbackMarkdown: string
): ChatContentBlock[] {
  const preservedBlocks = (currentBlocks ?? []).filter((block) => block.type !== "status");
  if (preservedBlocks.length > 0) {
    return [buildStatusBlock("Waiting for approval", "pending", fallbackMarkdown), ...preservedBlocks];
  }

  return [buildStatusBlock("Waiting for approval", "pending", fallbackMarkdown), buildMarkdownBlock(fallbackMarkdown)];
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
      let didReceiveDone = false;
      let didBlockForApproval = false;

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
            const currentAssistantMessage = useChatStore.getState().messages.find((messageItem) => messageItem.id === assistantId);
            updateMessage(assistantId, {
              content: assistantContent,
              status: "streaming",
              content_blocks: mergeStreamingBlocks(currentAssistantMessage?.content_blocks, {
                statusDetail: "The agent is preparing the response.",
                markdownContent: assistantContent
              })
            });
          } else if (payload.type === "action_started" || payload.type === "action_completed") {
            const toolLabel = payload.label ?? payload.tool ?? "Action";
            const toolState = payload.type === "action_completed" ? "complete" : "running";
            const safeDetail = payload.content?.trim() || undefined;
            const currentAssistantMessage = useChatStore.getState().messages.find((messageItem) => messageItem.id === assistantId);
            updateMessage(assistantId, {
              content: assistantContent,
              status: "streaming",
              content_blocks: mergeStreamingBlocks(currentAssistantMessage?.content_blocks, {
                statusDetail: safeDetail ?? "The agent is using a tool.",
                markdownContent: assistantContent,
                toolAction: {
                  label: toolLabel,
                  state: toolState,
                  detail: safeDetail,
                  toolCallId: payload.tool_call_id
                }
              })
            });
          } else if (payload.type === "approval_blocked") {
            const blockedMessage = payload.content || "Review the pending draft before sending another message in this conversation.";
            const currentAssistantMessage = useChatStore.getState().messages.find((messageItem) => messageItem.id === assistantId);
            didBlockForApproval = true;
            updateMessage(assistantId, {
              content: assistantContent || blockedMessage,
              status: "waiting_approval",
              content_blocks: mergeApprovalBlocks(currentAssistantMessage?.content_blocks, assistantContent || blockedMessage),
              metadata: {
                draft_id: payload.draft_id,
                is_waiting_approval: true
              }
            });
            toast({
              title: "Approval Required",
              description: blockedMessage
            });
          } else if (payload.type === "approval_pending") {
            const currentAssistantMessage = useChatStore.getState().messages.find((messageItem) => messageItem.id === assistantId);
            updateMessage(assistantId, {
              status: "waiting_approval",
              content: assistantContent,
              content_blocks: mergeApprovalBlocks(
                currentAssistantMessage?.content_blocks,
                assistantContent || "A draft is ready and requires human review."
              ),
              metadata: {
                draft_id: payload.draft_id,
                is_waiting_approval: true
              }
            });
            if (!didBlockForApproval) {
              await reloadConversation(conversationId);
            }
          } else if (payload.type === "turn_completed" || payload.type === "done") {
            didCompleteTurn = true;
            if (payload.type === "done") {
              didReceiveDone = true;
            }
            if (!didBlockForApproval) {
              await reloadConversation(conversationId);
            }
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

      if (!didCompleteTurn && !(didBlockForApproval && didReceiveDone)) {
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
