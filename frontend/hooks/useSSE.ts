"use client";

import { useEffect } from "react";

import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api";
import { useApprovalStore } from "@/stores/approvalStore";
import { useChatStore } from "@/stores/chatStore";
import type { SSEEvent } from "@/types";

const notificationsUrl =
  `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/notifications/stream`;

export function useSSE(enabled = true) {
  const open = useApprovalStore((state) => state.open);
  const clearPending = useApprovalStore((state) => state.clearPending);
  const { toast } = useToast();
  const activeConversationId = useChatStore((state) => state.activeConversationId);
  const setMessages = useChatStore((state) => state.setMessages);

  useEffect(() => {
    if (!enabled) return;

    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let isUnmounted = false;
    let retryCount = 0;

    const connect = () => {
      if (isUnmounted) {
        return;
      }

      source = new EventSource(notificationsUrl, { withCredentials: true });

      source.onopen = () => {
        retryCount = 0;
      };

      source.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as SSEEvent;
          const refreshIfActive = async () => {
            if (!payload.conversation_id || payload.conversation_id !== activeConversationId) {
              return;
            }
            const response = await api.get(`/chat/history/${payload.conversation_id}`);
            setMessages(response.data);
          };

          if (payload.type === "approval_required" && payload.draft) {
            open({
              id: payload.draft_id ?? "",
              ...payload.draft,
              description: payload.description ?? payload.draft.description ?? null
            });
            void refreshIfActive();
          } else if (payload.type === "email_sent") {
            if (payload.draft_id) {
              clearPending(payload.draft_id);
            }
            toast({
              title: payload.title ?? "Email Sent",
              description: payload.body ?? "The approved email was sent successfully."
            });
            void refreshIfActive();
          } else if (payload.type === "email_rejected") {
            if (payload.draft_id) {
              clearPending(payload.draft_id);
            }
            toast({
              title: payload.title ?? "Draft Rejected",
              description: payload.body ?? "The draft was rejected and was not sent."
            });
            void refreshIfActive();
          } else if (payload.type === "error") {
            if (payload.draft_id) {
              clearPending(payload.draft_id);
            }
            toast({
              title: payload.title ?? "Error",
              description: payload.content ?? "Something went wrong."
            });
            void refreshIfActive();
          }
        } catch {
          // Ignore malformed events and keep the stream alive.
        }
      };

      source.onerror = () => {
        source?.close();
        source = null;

        if (isUnmounted) {
          return;
        }

        const delay = Math.min(1000 * 2 ** retryCount, 10000);
        retryCount += 1;
        reconnectTimer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      isUnmounted = true;
      source?.close();
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
    };
  }, [activeConversationId, clearPending, enabled, open, setMessages, toast]);
}
