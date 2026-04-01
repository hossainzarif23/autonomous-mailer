"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

export default function Error({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <section className="w-full max-w-xl rounded-[2rem] border border-border bg-card/90 p-8 shadow-xl">
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-primary">Application Error</p>
        <h1 className="mt-3 text-3xl font-semibold">The dashboard hit an unexpected client-side failure.</h1>
        <p className="mt-4 text-sm leading-7 text-muted-foreground">
          Retry the current route first. If the issue persists, refresh the page and re-authenticate.
        </p>
        <div className="mt-6 flex gap-3">
          <Button onClick={() => reset()}>Try Again</Button>
          <Button variant="outline" onClick={() => window.location.assign("/dashboard")}>
            Back to Dashboard
          </Button>
        </div>
      </section>
    </main>
  );
}
