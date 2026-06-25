"use client";

import { useRef, useState } from "react";

import { api, getErrorMessage } from "@/lib/api";
import { useApprovalStore } from "@/stores/approvalStore";
import { useChatStore } from "@/stores/chatStore";
import { useToast } from "@/hooks/use-toast";
import type { ChatContentBlock, ChatMessage, Conversation, SSEEvent } from "@/types";

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
  const hasMarkdownBlock = preservedBlocks.some((block) => block.type === "markdown");
  const mergedBlocks = hasMarkdownBlock || !fallbackMarkdown ? preservedBlocks : [...preservedBlocks, buildMarkdownBlock(fallbackMarkdown)];

  if (mergedBlocks.length > 0) {
    return [buildStatusBlock("Waiting for approval", "pending", fallbackMarkdown), ...mergedBlocks];
  }

  return [buildStatusBlock("Waiting for approval", "pending", fallbackMarkdown), buildMarkdownBlock(fallbackMarkdown)];
}

async function openPendingDraftIfNeeded(conversationId: string) {
  // Only open if no modal is already open (avoids stealing focus mid-edit).
  if (useApprovalStore.getState().isOpen) {
    return;
  }
  try {
    const response = await api.get<Array<{
      id: string;
      conversation_id?: string | null;
      to: string;
      subject: string;
      body: string;
      draft_type: "reply" | "fresh";
      status?: string | null;
      description?: string | null;
    }>>("/approve/pending");
    const draft = response.data.find((entry) => entry.conversation_id === conversationId);
    if (!draft) {
      return;
    }
    useApprovalStore.getState().open({
      id: draft.id,
      to: draft.to,
      subject: draft.subject,
      body: draft.body,
      draft_type: draft.draft_type,
      status: draft.status ?? null,
      conversation_id: draft.conversation_id ?? null,
      description: draft.description ?? null
    });
  } catch {
    // Replay is best-effort. If /approve/pending fails, the notification
    // stream will still surface the approval_required event when it reconnects.
  }
}

export function useChat() {
  const {
    activeConversationId,
    appendMessage,
    setConversations,
    upsertConversation,
    removeConversationById,
    setActiveConversationId,
    setMessages,
    setStreaming,
    updateMessage,
    removeMessage,
    isStreaming
  } = useChatStore();
  const { toast } = useToast();
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);
  const createConversationPromiseRef = useRef<Promise<string> | null>(null);

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

  async function runCreateConversation(): Promise<string> {
    const tempId = `temp-${crypto.randomUUID()}`;
    const nowIso = new Date().toISOString();
    const optimisticConversation: Conversation = {
      id: tempId,
      title: null,
      created_at: nowIso,
      updated_at: nowIso
    };

    setIsCreatingConversation(true);
    upsertConversation(optimisticConversation);
    setActiveConversationId(tempId);
    setMessages([]);

    try {
      const response = await api.post<{ id: string }>("/chat/conversations");
      const realId = response.data.id;
      // Replace the optimistic entry in place with the real conversation so
      // the list and the active id stay in sync. Removing the temp first
      // would leave a frame where activeConversationId points at a real id
      // that isn't in the list, which the sidebar renders as "no active
      // conversation" — the user perceives the click as a no-op.
      upsertConversation({
        id: realId,
        title: null,
        created_at: optimisticConversation.created_at,
        updated_at: optimisticConversation.updated_at
      });
      if (useChatStore.getState().activeConversationId === tempId) {
        setActiveConversationId(realId);
      }
      return realId;
    } catch (error) {
      removeConversationById(tempId);
      if (useChatStore.getState().activeConversationId === tempId) {
        setActiveConversationId(null);
      }
      throw error;
    } finally {
      setIsCreatingConversation(false);
    }
  }

  function createConversation(): Promise<string> {
    if (createConversationPromiseRef.current) {
      return createConversationPromiseRef.current;
    }

    const promise = runCreateConversation()
      .catch((error) => {
        const message = getErrorMessage(error, "Failed to create a new conversation.");
        toast({
          title: "Conversation Error",
          description: message
        });
        throw error;
      })
      .finally(() => {
        createConversationPromiseRef.current = null;
      });

    createConversationPromiseRef.current = promise;
    return promise;
  }

  async function ensureConversationId() {
    const current = useChatStore.getState().activeConversationId;
    if (current && !current.startsWith("temp-")) {
      return current;
    }

    return createConversation();
  }

  async function loadConversation(conversationId: string) {
    if (conversationId === useChatStore.getState().activeConversationId) {
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
      let didReloadConversation = false;
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
          } else if (payload.type === "research_report" && payload.content) {
            // Surface the parsed research content as a structured block so the
            // hand-rolled MarkdownResponse (and its react-markdown replacement)
            // renders it with full markdown fidelity during the live stream.
            const currentAssistantMessage = useChatStore.getState().messages.find((messageItem) => messageItem.id === assistantId);
            const existingBlocks = (currentAssistantMessage?.content_blocks ?? []).filter(
              (block) => !(block.type === "status" && block.tone === "pending" && (block.label === "Working" || block.label === "Thinking"))
            );
            const hasResearch = existingBlocks.some(
              (block) => block.type === "research_report" && block.tool_call_id === payload.tool_call_id
            );
            if (!hasResearch) {
              const researchBlock: ChatContentBlock = {
                type: "research_report",
                title: payload.title ?? "Research Notes",
                content: payload.content,
                tool_call_id: payload.tool_call_id ?? null
              };
              updateMessage(assistantId, {
                content: assistantContent,
                status: "streaming",
                content_blocks: [...existingBlocks, researchBlock]
              });
            }
          } else if (payload.type === "draft_artifact" && payload.draft) {
            // Live-update the draft_email block as soon as the mailing agent
            // produces it, instead of waiting for the history reload.
            const currentAssistantMessage = useChatStore.getState().messages.find((messageItem) => messageItem.id === assistantId);
            const existingBlocks = (currentAssistantMessage?.content_blocks ?? []).filter(
              (block) => !(block.type === "status" && (block.label === "Working" || block.label === "Thinking"))
            );
            const draftBlock: ChatContentBlock = {
              type: "draft_email",
              draft_id: "",
              to: String(payload.draft.to ?? ""),
              subject: String(payload.draft.subject ?? ""),
              body_preview: String(payload.draft.body ?? ""),
              draft_type: (payload.draft.draft_type === "reply" ? "reply" : "fresh"),
              approval_state: "draft_ready",
              conversation_id: payload.conversation_id ?? null
            };
            const filtered = existingBlocks.filter((block) => block.type !== "draft_email");
            updateMessage(assistantId, {
              content: assistantContent,
              status: "streaming",
              content_blocks: [...filtered, draftBlock]
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
          } else if (payload.type === "approval_required" && payload.draft) {
            // The request-scoped stream carries the full draft body so the
            // active tab can open the modal even if the notification EventSource
            // is dead or reconnecting. The notification broadcast is still
            // fired for other tabs / devices (see useSSE.ts).
            didBlockForApproval = true;
            useApprovalStore.getState().open({
              id: payload.draft_id ?? payload.draft.id ?? "",
              to: payload.draft.to,
              subject: payload.draft.subject,
              body: payload.draft.body,
              draft_type: payload.draft.draft_type,
              status: payload.draft.status,
              conversation_id: payload.draft.conversation_id ?? payload.conversation_id ?? null,
              description: payload.description ?? payload.draft.description ?? null
            });
            const currentAssistantMessage = useChatStore.getState().messages.find((messageItem) => messageItem.id === assistantId);
            updateMessage(assistantId, {
              content: assistantContent,
              status: "waiting_approval",
              content_blocks: mergeApprovalBlocks(
                currentAssistantMessage?.content_blocks,
                assistantContent || "A draft is ready and requires human review."
              ),
              metadata: {
                draft_id: payload.draft_id,
                is_waiting_approval: true
              }
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
          } else if (payload.type === "turn_completed" || payload.type === "done") {
            if (payload.type === "done") {
              if (!didReloadConversation) {
                await reloadConversation(conversationId);
                didReloadConversation = true;
              }
            } else if (!didBlockForApproval && !didReloadConversation) {
              await reloadConversation(conversationId);
              didReloadConversation = true;
            }
            // Replay: if we ended the stream in a waiting_approval state but
            // the modal isn't open, query the server for the pending draft.
            // This recovers from dropped approval_required events (e.g. the
            // notification EventSource was dead) by going to the source of
            // truth — the email_drafts table.
            await openPendingDraftIfNeeded(conversationId);
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

      if (!didReloadConversation) {
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
    isCreatingConversation,
    isStreaming,
    loadConversation,
    refreshConversations,
    reloadConversation,
    sendMessage
  };
}
