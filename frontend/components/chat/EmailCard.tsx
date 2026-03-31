import type { EmailSummary } from "@/types";

interface EmailCardProps {
  email: EmailSummary;
}

export function EmailCard({ email }: EmailCardProps) {
  return (
    <article className="rounded-2xl border border-border bg-background/80 p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="font-semibold">{email.subject}</h3>
          <p className="text-sm text-muted-foreground">
            {email.from_name} ({email.from_email})
          </p>
        </div>
        <span className="text-xs text-muted-foreground">{email.date}</span>
      </div>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{email.snippet}</p>
    </article>
  );
}

