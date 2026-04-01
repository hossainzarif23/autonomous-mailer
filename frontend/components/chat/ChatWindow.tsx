"use client";

import { MessageBubble } from "@/components/chat/MessageBubble";
import { useChatStore } from "@/stores/chatStore";

const starterMessages = [
  "Read my last email.",
  "Find emails about job opportunities.",
  "Summarize emails from BRAC Bank.",
  "Write a fresh email to ceo@company.com about AI trends in Bangladesh."
];

export function ChatWindow() {
  const messages = useChatStore((state) => state.messages);

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-10">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
        {messages.length === 0 ? (
          <section className="rounded-[2rem] border border-border bg-card/90 p-8 shadow-xl">
            <p className="text-sm font-semibold uppercase tracking-[0.3em] text-primary">Assistant</p>
            <h2 className="mt-3 text-3xl font-semibold">Chat streaming and approval are live.</h2>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-muted-foreground">
              Ask for recent emails, search by sender or topic, summarize threads, or draft a reply that pauses for
              approval before sending.
            </p>
            <div className="mt-8 grid gap-3 md:grid-cols-2">
              {starterMessages.map((message) => (
                <div key={message} className="rounded-2xl border border-border bg-background/80 p-4 text-sm">
                  {message}
                </div>
              ))}
            </div>
          </section>
        ) : (
          messages.map((message) => <MessageBubble key={message.id} message={message} />)
        )}
      </div>
    </div>
  );
}
