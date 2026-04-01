"use client";

import { useEffect } from "react";

import { useToast } from "@/hooks/use-toast";
import { useApprovalStore } from "@/stores/approvalStore";
import type { SSEEvent } from "@/types";

const notificationsUrl =
  `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/notifications/stream`;

export function useSSE(enabled = true) {
  const open = useApprovalStore((state) => state.open);
  const { toast } = useToast();

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
          if (payload.type === "approval_required" && payload.draft) {
            open({
              id: payload.draft_id ?? "",
              ...payload.draft,
              description: payload.description ?? payload.draft.description ?? null
            });
          } else if (payload.type === "email_sent") {
            toast({
              title: payload.title ?? "Email Sent",
              description: payload.body ?? "The approved email was sent successfully."
            });
          } else if (payload.type === "email_rejected") {
            toast({
              title: payload.title ?? "Draft Rejected",
              description: payload.body ?? "The draft was rejected and was not sent."
            });
          } else if (payload.type === "error") {
            toast({
              title: payload.title ?? "Error",
              description: payload.content ?? "Something went wrong."
            });
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
  }, [enabled, open, toast]);
}
