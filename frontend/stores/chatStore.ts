"use client";

import { create } from "zustand";

import type { ChatMessage, Conversation } from "@/types";

interface ChatState {
  conversations: Conversation[];
  activeConversationId: string | null;
  messages: ChatMessage[];
  isStreaming: boolean;
  setConversations: (conversations: Conversation[]) => void;
  upsertConversation: (conversation: Conversation) => void;
  removeConversationById: (conversationId: string) => void;
  setActiveConversationId: (conversationId: string | null) => void;
  setMessages: (messages: ChatMessage[]) => void;
  appendMessage: (message: ChatMessage) => void;
  updateMessage: (messageId: string, patch: Partial<ChatMessage>) => void;
  removeMessage: (messageId: string) => void;
  setStreaming: (isStreaming: boolean) => void;
  reset: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  activeConversationId: null,
  messages: [],
  isStreaming: false,
  setConversations: (conversations) => set({ conversations }),
  upsertConversation: (conversation) =>
    set((state) => {
      const existingIndex = state.conversations.findIndex((entry) => entry.id === conversation.id);
      if (existingIndex === -1) {
        return { conversations: [conversation, ...state.conversations] };
      }
      const next = state.conversations.slice();
      next[existingIndex] = conversation;
      return { conversations: next };
    }),
  removeConversationById: (conversationId) =>
    set((state) => ({
      conversations: state.conversations.filter((conversation) => conversation.id !== conversationId)
    })),
  setActiveConversationId: (activeConversationId) => set({ activeConversationId }),
  setMessages: (messages) => set({ messages }),
  appendMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
  updateMessage: (messageId, patch) =>
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === messageId ? { ...message, ...patch } : message
      )
    })),
  removeMessage: (messageId) =>
    set((state) => ({
      messages: state.messages.filter((message) => message.id !== messageId)
    })),
  setStreaming: (isStreaming) => set({ isStreaming }),
  reset: () =>
    set({
      conversations: [],
      activeConversationId: null,
      messages: [],
      isStreaming: false
    })
}));
