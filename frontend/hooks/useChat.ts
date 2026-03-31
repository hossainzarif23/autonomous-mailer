"use client";

import { useChatStore } from "@/stores/chatStore";

export function useChat() {
  return useChatStore();
}

