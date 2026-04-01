"use client";

import { Mail, UserRound } from "lucide-react";

import type { EmailSummary } from "@/types";

interface EmailCardProps {
  email: EmailSummary;
}

export function EmailCard({ email }: EmailCardProps) {
  return (
    <article className="rounded-3xl border border-border/70 bg-card/80 p-5 shadow-[0_18px_45px_-30px_rgba(15,23,42,0.22)]">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">
            <Mail className="h-3.5 w-3.5" />
            Email
          </p>
          <h3 className="mt-3 line-clamp-2 text-base font-semibold text-foreground">
            {email.subject || "(No subject)"}
          </h3>
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">{email.date}</span>
      </div>
      <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
        <UserRound className="h-4 w-4" />
        <span className="truncate">
          {email.from_name} ({email.from_email})
        </span>
      </div>
      <p className="mt-4 text-sm leading-7 text-muted-foreground">{email.snippet}</p>
    </article>
  );
}
