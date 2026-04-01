"use client";

import { FormEvent, useState } from "react";
import { SendHorizonal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useChat } from "@/hooks/useChat";

export function InputBar() {
  const [message, setMessage] = useState("");
  const { isStreaming, sendMessage } = useChat();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = message.trim();
    if (!value || isStreaming) {
      return;
    }

    setMessage("");
    try {
      await sendMessage(value);
    } catch {
      setMessage(value);
    }
  }

  return (
    <div className="border-t border-border/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.84),rgba(248,250,252,0.94))] px-4 py-5 backdrop-blur lg:px-8">
      <form className="mx-auto flex w-full max-w-5xl items-center gap-3 rounded-[1.75rem] border border-border/70 bg-card/90 p-3 shadow-[0_24px_60px_-42px_rgba(15,23,42,0.28)]" onSubmit={(event) => void handleSubmit(event)}>
        <Input
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Ask to read, search, summarize, reply, or draft an email."
          disabled={isStreaming}
          className="border-0 bg-transparent text-[15px] shadow-none focus-visible:ring-0"
        />
        <Button type="submit" disabled={isStreaming || !message.trim()} className="rounded-[1.2rem] px-5">
          <SendHorizonal className="mr-2 h-4 w-4" />
          {isStreaming ? "Streaming" : "Send"}
        </Button>
      </form>
    </div>
  );
}
