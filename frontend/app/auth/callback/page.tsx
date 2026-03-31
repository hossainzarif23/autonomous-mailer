export default function AuthCallbackPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="rounded-3xl border border-border bg-card px-10 py-12 text-center shadow-xl">
        <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-primary/20 border-t-primary" />
        <h1 className="text-2xl font-semibold">Signing you in</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          FastAPI will complete the OAuth callback and redirect back to the dashboard.
        </p>
      </div>
    </main>
  );
}

