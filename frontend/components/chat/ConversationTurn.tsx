"use client";

import { CheckCircle2, Clock3, FileSearch, MailCheck, MailPlus, TriangleAlert } from "lucide-react";

import { EmailCard } from "@/components/chat/EmailCard";
import { MarkdownResponse } from "@/components/chat/MarkdownResponse";
import { cn } from "@/lib/utils";
import type {
  ChatContentBlock,
  ChatMessage,
  DraftEmailBlock,
  EmailListBlock,
  ResearchReportBlock,
  StatusBlock,
  SummaryBlock,
  ToolActionBlock
} from "@/types";

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function toneStyles(tone?: string) {
  switch (tone) {
    case "success":
      return "border-emerald-300/70 bg-emerald-50 text-emerald-900";
    case "pending":
      return "border-amber-300/70 bg-amber-50 text-amber-950";
    case "warning":
      return "border-orange-300/70 bg-orange-50 text-orange-950";
    case "error":
      return "border-destructive/40 bg-destructive/5 text-destructive";
    default:
      return "border-border/70 bg-muted/40 text-foreground";
  }
}

function StatusPill({ block }: { block: StatusBlock }) {
  return (
    <div className={cn("rounded-2xl border px-4 py-3 text-sm", toneStyles(block.tone))}>
      <p className="font-medium">{block.label}</p>
      {block.detail ? <p className="mt-1 text-sm/6 opacity-80">{block.detail}</p> : null}
    </div>
  );
}

function ActionPill({ block }: { block: ToolActionBlock }) {
  const icon =
    block.state === "complete" ? (
      <CheckCircle2 className="h-4 w-4" />
    ) : block.state === "error" ? (
      <TriangleAlert className="h-4 w-4" />
    ) : (
      <Clock3 className="h-4 w-4" />
    );

  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-card/75 px-3 py-2 text-xs font-medium text-muted-foreground shadow-sm">
      {icon}
      <span>{block.label}</span>
    </div>
  );
}

function SummaryCard({ block }: { block: SummaryBlock }) {
  return (
    <section className="rounded-[1.75rem] border border-border/70 bg-card/80 p-6 shadow-[0_18px_45px_-30px_rgba(15,23,42,0.22)]">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">
        {block.title || "Summary"}
      </p>
      <div className="mt-4">
        <MarkdownResponse content={block.content} />
      </div>
    </section>
  );
}

function ResearchCard({ block }: { block: ResearchReportBlock }) {
  return (
    <section className="rounded-[1.75rem] border border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.95),rgba(248,250,252,0.88))] p-6 shadow-[0_18px_45px_-30px_rgba(15,23,42,0.22)]">
      <div className="flex items-center gap-2">
        <FileSearch className="h-4 w-4 text-primary" />
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">
          {block.title || "Research"}
        </p>
      </div>
      <div className="mt-4">
        <MarkdownResponse content={block.content} />
      </div>
    </section>
  );
}

function DraftEmailCard({ block }: { block: DraftEmailBlock }) {
  const stateCopy = {
    draft_ready: "Draft ready",
    waiting_approval: "Waiting for approval",
    rewrite_requested: "Rewrite requested",
    sent: "Sent",
    error: "Send failed",
  }[block.approval_state];

  const stateTone =
    block.approval_state === "sent"
      ? "success"
      : block.approval_state === "waiting_approval"
        ? "pending"
        : block.approval_state === "rewrite_requested"
          ? "warning"
          : block.approval_state === "error"
            ? "error"
            : "neutral";

  return (
    <section className="overflow-hidden rounded-[1.75rem] border border-border/70 bg-card/90 shadow-[0_18px_45px_-30px_rgba(15,23,42,0.22)]">
      <div className="border-b border-border/70 bg-muted/35 px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">
              {block.draft_type === "reply" ? "Reply Draft" : "Fresh Email Draft"}
            </p>
            <h3 className="mt-2 text-xl font-semibold text-foreground">{block.subject || "(No subject)"}</h3>
          </div>
          <div className={cn("rounded-full border px-3 py-1.5 text-xs font-semibold", toneStyles(stateTone))}>
            {stateCopy}
          </div>
        </div>
        <p className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
          {block.approval_state === "sent" ? <MailCheck className="h-4 w-4" /> : <MailPlus className="h-4 w-4" />}
          <span>{block.to}</span>
        </p>
      </div>
      <div className="px-6 py-5">
        <div className="rounded-2xl bg-background/70 px-4 py-4">
          <pre className="whitespace-pre-wrap font-sans text-sm leading-7 text-foreground/90">{block.body_preview}</pre>
        </div>
      </div>
    </section>
  );
}

function BlockRenderer({ block }: { block: ChatContentBlock }) {
  switch (block.type) {
    case "markdown":
      return <MarkdownResponse content={block.content} />;
    case "status":
      return <StatusPill block={block} />;
    case "tool_action":
      return <ActionPill block={block} />;
    case "email_list":
      return (
        <section className="space-y-4">
          {block.title ? <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">{block.title}</p> : null}
          <div className="grid gap-4">
            {block.emails.map((email) => (
              <EmailCard key={`${email.message_id}-${email.thread_id}`} email={email} />
            ))}
          </div>
        </section>
      );
    case "summary":
      return <SummaryCard block={block} />;
    case "research_report":
      return <ResearchCard block={block} />;
    case "draft_email":
      return <DraftEmailCard block={block} />;
    case "system_notice":
      return <StatusPill block={{ type: "status", label: block.title || "Notice", detail: block.content, tone: "neutral" }} />;
    default:
      return null;
  }
}

function AssistantTurn({ message }: { message: ChatMessage }) {
  const blocks = message.content_blocks ?? [{ type: "markdown", content: message.content } as ChatContentBlock];
  const actionBlocks = blocks.filter((block): block is ToolActionBlock => block.type === "tool_action");
  const statusBlocks = blocks.filter((block): block is StatusBlock => block.type === "status");
  const contentBlocks = blocks.filter((block) => block.type !== "tool_action" && block.type !== "status");

  return (
    <article className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">Email Agent</p>
          <p className="mt-1 text-sm text-muted-foreground">Structured response with actions and artifacts</p>
        </div>
        <span className="text-xs text-muted-foreground">{formatTimestamp(message.created_at)}</span>
      </div>

      {actionBlocks.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {actionBlocks.map((block, index) => (
            <ActionPill key={`${message.id}-action-${index}`} block={block} />
          ))}
        </div>
      ) : null}

      {statusBlocks.length > 0 ? (
        <div className="space-y-3">
          {statusBlocks.map((block, index) => (
            <StatusPill key={`${message.id}-status-${index}`} block={block} />
          ))}
        </div>
      ) : null}

      <div className="space-y-6">
        {contentBlocks.map((block, index) => (
          <BlockRenderer key={`${message.id}-block-${index}`} block={block} />
        ))}
      </div>
    </article>
  );
}

function UserTurn({ message }: { message: ChatMessage }) {
  return (
    <article className="ml-auto max-w-2xl rounded-[2rem] bg-primary px-6 py-5 text-primary-foreground shadow-[0_20px_45px_-30px_rgba(5,150,105,0.75)]">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary-foreground/75">You</p>
      <p className="mt-3 whitespace-pre-wrap text-[15px] leading-8">{message.content}</p>
    </article>
  );
}

interface ConversationTurnProps {
  message: ChatMessage;
}

export function ConversationTurn({ message }: ConversationTurnProps) {
  return (
    <div className={cn("w-full", message.role === "assistant" ? "max-w-4xl" : "max-w-3xl")}>
      {message.role === "assistant" ? <AssistantTurn message={message} /> : <UserTurn message={message} />}
    </div>
  );
}
