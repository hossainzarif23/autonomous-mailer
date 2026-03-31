"use client";

import { useEffect } from "react";

import { useApprovalStore } from "@/stores/approvalStore";
import type { SSEEvent } from "@/types";

const notificationsUrl =
  `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/notifications/stream`;

export function useSSE(enabled = true) {
  const open = useApprovalStore((state) => state.open);

  useEffect(() => {
    if (!enabled) return;

    const source = new EventSource(notificationsUrl, { withCredentials: true });

    source.onmessage = (event) => {
      const payload = JSON.parse(event.data) as SSEEvent;
      if (payload.type === "approval_required" && payload.draft) {
        open(payload.draft);
      }
    };

    source.onerror = () => {
      source.close();
    };

    return () => {
      source.close();
    };
  }, [enabled, open]);
}

