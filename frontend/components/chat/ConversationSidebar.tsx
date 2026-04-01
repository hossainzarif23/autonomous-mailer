"use client";

import { Loader2, LogOut, MessageSquarePlus } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useChat } from "@/hooks/useChat";
import { useChatStore } from "@/stores/chatStore";

function formatConversationDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
}

export function ConversationSidebar() {
  const [isLoadingConversations, setIsLoadingConversations] = useState(true);
  const { user, logout } = useAuth();
  const { activeConversationId, conversations, messages, isStreaming } = useChatStore((state) => ({
    activeConversationId: state.activeConversationId,
    conversations: state.conversations,
    messages: state.messages,
    isStreaming: state.isStreaming
  }));
  const { createConversation, loadConversation, refreshConversations } = useChat();

  useEffect(() => {
    let cancelled = false;

    async function hydrateSidebar() {
      try {
        await refreshConversations();
        const state = useChatStore.getState();
        if (cancelled || state.activeConversationId || state.conversations.length === 0) {
          return;
        }

        const [firstConversation] = state.conversations;
        if (!firstConversation) {
          return;
        }

        await loadConversation(firstConversation.id);
      } finally {
        if (!cancelled) {
          setIsLoadingConversations(false);
        }
      }
    }

    void hydrateSidebar();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <aside className="flex h-screen flex-col border-b border-border/70 bg-card/80 p-6 backdrop-blur lg:border-b-0 lg:border-r">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-primary">Workspace</p>
          <h1 className="mt-2 text-2xl font-semibold">Email Agent</h1>
        </div>
        <Button variant="outline" size="sm" onClick={() => void logout()}>
          <LogOut className="mr-2 h-4 w-4" />
          Logout
        </Button>
      </div>

      <div className="mb-4 rounded-2xl border border-border bg-background/85 p-4">
        <p className="text-sm font-semibold">{user?.name ?? user?.email ?? "Authenticated User"}</p>
        <p className="mt-1 text-sm text-muted-foreground">{user?.email ?? "No email available"}</p>
        <p className="mt-3 text-xs uppercase tracking-[0.2em] text-primary">
          {user?.gmail_scope_granted ? "Gmail scopes granted" : "Gmail scopes incomplete"}
        </p>
      </div>

      <Button className="mb-4 w-full justify-start rounded-2xl" onClick={() => void createConversation()} disabled={isStreaming}>
        <MessageSquarePlus className="mr-2 h-4 w-4" />
        New Chat
      </Button>

      <div className="mb-4 rounded-2xl border border-dashed border-border p-4 text-sm text-muted-foreground">
        Phase 6 is live. Conversations load from history, new threads can be created, and approvals continue over SSE.
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">Conversations</p>
          {conversations.length > 0 ? (
            <span className="text-xs text-muted-foreground">{conversations.length}</span>
          ) : null}
        </div>

        <div className="space-y-2">
          {isLoadingConversations ? (
            <div className="flex items-center rounded-2xl border border-border bg-background/70 p-4 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading conversations...
            </div>
          ) : conversations.length === 0 ? (
            <div className="rounded-2xl border border-border bg-background/70 p-4 text-sm text-muted-foreground">
              {messages.length > 0 ? "Conversation history is available in the active thread." : "No conversations yet. Start a new chat to begin."}
            </div>
          ) : (
            conversations.map((conversation) => {
              const isActive = conversation.id === activeConversationId;

              return (
                <button
                  key={conversation.id}
                  type="button"
                  onClick={() => void loadConversation(conversation.id)}
                  disabled={isStreaming}
                  className={[
                    "w-full rounded-2xl border px-4 py-3 text-left transition",
                    isActive
                      ? "border-primary bg-primary/10 shadow-sm"
                      : "border-border bg-background/70 hover:border-primary/40 hover:bg-background"
                  ].join(" ")}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="line-clamp-2 text-sm font-medium">
                      {conversation.title?.trim() || "New conversation"}
                    </p>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {formatConversationDate(conversation.updated_at)}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {isActive ? "Open now" : "Open conversation history"}
                  </p>
                </button>
              );
            })
          )}
        </div>
      </div>

      {isStreaming ? (
        <div className="mt-4 flex items-center rounded-2xl border border-border bg-background/80 px-4 py-3 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Streaming response...
        </div>
      ) : null}
    </aside>
  );
}
