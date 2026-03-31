import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  return (
    <div
      className={cn(
        "max-w-2xl rounded-3xl px-5 py-4 shadow-sm",
        message.role === "assistant" ? "bg-card" : "ml-auto bg-primary text-primary-foreground"
      )}
    >
      <p className="whitespace-pre-wrap text-sm leading-7">{message.content}</p>
    </div>
  );
}

