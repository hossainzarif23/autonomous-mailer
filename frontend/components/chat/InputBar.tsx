"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { SendHorizonal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useChat } from "@/hooks/useChat";

const MAX_ROWS = 8;
const LINE_HEIGHT_PX = 24;
const MAX_HEIGHT_PX = LINE_HEIGHT_PX * MAX_ROWS;

export function InputBar() {
  const [message, setMessage] = useState("");
  const { isStreaming, sendMessage } = useChat();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "auto";
    const nextHeight = Math.min(textarea.scrollHeight, MAX_HEIGHT_PX);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > MAX_HEIGHT_PX ? "auto" : "hidden";
  }, [message]);

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

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      const form = event.currentTarget.form;
      if (form) {
        form.requestSubmit();
      }
    }
  }

  const canSend = !isStreaming && message.trim().length > 0;

  return (
    <div className="border-t border-border/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.84),rgba(248,250,252,0.94))] px-4 py-5 backdrop-blur lg:px-8">
      <form
        className="mx-auto flex w-full max-w-5xl items-end gap-3 rounded-[1.75rem] border border-border/70 bg-card/90 p-3 shadow-[0_24px_60px_-42px_rgba(15,23,42,0.28)]"
        onSubmit={(event) => void handleSubmit(event)}
      >
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask to read, search, summarize, reply, or draft an email."
          disabled={isStreaming}
          rows={1}
          className="min-h-10 max-h-48 flex-1 resize-none border-0 bg-transparent px-2 py-2 text-[15px] leading-6 shadow-none outline-none placeholder:text-muted-foreground focus-visible:ring-0 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
        />
        <Button type="submit" disabled={!canSend} className="h-10 rounded-[1.2rem] px-5">
          <SendHorizonal className="mr-2 h-4 w-4" />
          {isStreaming ? "Streaming" : "Send"}
        </Button>
      </form>
    </div>
  );
}
