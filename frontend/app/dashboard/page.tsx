"use client";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { ConversationSidebar } from "@/components/chat/ConversationSidebar";
import { InputBar } from "@/components/chat/InputBar";
import { useAuth } from "@/hooks/useAuth";
import { useSSE } from "@/hooks/useSSE";

export default function DashboardPage() {
  const { status } = useAuth();
  useSSE(status === "authenticated");

  if (status === "idle" || status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center px-6">
        <div className="rounded-3xl border border-border bg-card px-10 py-12 text-center shadow-xl">
          <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-primary/20 border-t-primary" />
          <h1 className="text-2xl font-semibold">Loading your workspace</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Validating the session and hydrating the authenticated dashboard state.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="grid min-h-screen grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)]">
      <ConversationSidebar />
      <section className="flex min-h-screen flex-col">
        <ChatWindow />
        <InputBar />
      </section>
    </main>
  );
}
