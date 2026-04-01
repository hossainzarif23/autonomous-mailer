"use client";

import { Sparkles, SquarePen } from "lucide-react";

import { ConversationTurn } from "@/components/chat/ConversationTurn";
import { useChatStore } from "@/stores/chatStore";

const starterMessages = [
  "Read my last five emails and tell me what matters.",
  "Find emails about job opportunities from the past two weeks.",
  "Summarize the BRAC Bank thread and list action items.",
  "Write a fresh email to ceo@company.com about AI trends in Bangladesh."
];

export function ChatWindow() {
  const messages = useChatStore((state) => state.messages);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 lg:px-8 lg:py-8">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-10">
        {messages.length === 0 ? (
          <section className="rounded-[2.5rem] border border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(249,250,251,0.92))] p-8 shadow-[0_30px_70px_-45px_rgba(15,23,42,0.28)] lg:p-10">
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <Sparkles className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-primary">Workspace</p>
                <h2 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">Ask the agent to read, research, draft, and send.</h2>
              </div>
            </div>
            <p className="mt-6 max-w-3xl text-[15px] leading-8 text-muted-foreground">
              Responses are rendered as readable reports with inline artifacts for summaries, research, inbox results,
              and approval-gated email drafts.
            </p>
            <div className="mt-8 grid gap-4 md:grid-cols-2">
              {starterMessages.map((message) => (
                <div
                  key={message}
                  className="rounded-[1.75rem] border border-border/70 bg-background/85 p-5 shadow-[0_18px_45px_-35px_rgba(15,23,42,0.22)]"
                >
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-primary">
                    <SquarePen className="h-3.5 w-3.5" />
                    Prompt idea
                  </div>
                  <p className="mt-3 text-sm leading-7 text-foreground/90">{message}</p>
                </div>
              ))}
            </div>
          </section>
        ) : (
          messages.map((message) => <ConversationTurn key={message.id} message={message} />)
        )}
      </div>
    </div>
  );
}
