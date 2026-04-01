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
    <div className="border-t border-border/70 bg-card/85 px-4 py-4 backdrop-blur lg:px-8">
      <form className="mx-auto flex w-full max-w-4xl items-center gap-3" onSubmit={(event) => void handleSubmit(event)}>
        <Input
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Ask to read, search, summarize, reply, or draft an email."
          disabled={isStreaming}
        />
        <Button type="submit" disabled={isStreaming || !message.trim()}>
          <SendHorizonal className="mr-2 h-4 w-4" />
          {isStreaming ? "Streaming" : "Send"}
        </Button>
      </form>
    </div>
  );
}
