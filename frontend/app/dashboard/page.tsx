"use client";

import { LogOut } from "lucide-react";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { InputBar } from "@/components/chat/InputBar";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useSSE } from "@/hooks/useSSE";

export default function DashboardPage() {
  const { user, status, logout } = useAuth();
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
      <aside className="border-b border-border/70 bg-card/80 p-6 backdrop-blur lg:border-b-0 lg:border-r">
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
        <div className="rounded-2xl border border-dashed border-border p-4 text-sm text-muted-foreground">
          Phase 5 is live. Chat streams from the coordinator agent, approval requests arrive over SSE, and approved
          drafts resume the interrupted workflow.
        </div>
      </aside>
      <section className="flex min-h-screen flex-col">
        <ChatWindow />
        <InputBar />
      </section>
    </main>
  );
}
