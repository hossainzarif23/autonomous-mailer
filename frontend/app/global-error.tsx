"use client";

import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="antialiased">
        <main className="flex min-h-screen items-center justify-center px-6">
          <section className="w-full max-w-xl rounded-[2rem] border border-border bg-card/90 p-8 shadow-xl">
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-primary">Fatal Error</p>
            <h1 className="mt-3 text-3xl font-semibold">The app crashed before the route could recover.</h1>
            <p className="mt-4 text-sm leading-7 text-muted-foreground">
              Retry once. If this remains broken, reload the app and inspect the latest logs from the failing request.
            </p>
            <p className="mt-4 text-xs text-muted-foreground">{error.message}</p>
            <div className="mt-6 flex gap-3">
              <Button onClick={() => reset()}>Try Again</Button>
              <Button variant="outline" onClick={() => window.location.assign("/login")}>
                Go to Login
              </Button>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
