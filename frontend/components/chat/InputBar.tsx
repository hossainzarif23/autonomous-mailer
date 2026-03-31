"use client";

import { SendHorizonal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function InputBar() {
  return (
    <div className="border-t border-border/70 bg-card/85 px-4 py-4 backdrop-blur lg:px-8">
      <form className="mx-auto flex w-full max-w-4xl items-center gap-3">
        <Input placeholder="Phase 2 will connect this input to the chat SSE endpoint." />
        <Button type="submit">
          <SendHorizonal className="mr-2 h-4 w-4" />
          Send
        </Button>
      </form>
    </div>
  );
}

