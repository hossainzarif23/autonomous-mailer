import { Button } from "@/components/ui/button";

const authLoginUrl = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/auth/login`;

interface LoginPageProps {
  searchParams?: {
    error?: string;
  };
}

export default function LoginPage({ searchParams }: LoginPageProps) {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="w-full max-w-md rounded-[2rem] border border-border/70 bg-card/95 p-10 shadow-2xl backdrop-blur">
        <div className="mb-8 space-y-3">
          <p className="text-sm font-semibold uppercase tracking-[0.3em] text-primary">Email Agent</p>
          <h1 className="text-4xl font-semibold tracking-tight">Google-authenticated email automation.</h1>
          <p className="text-sm leading-6 text-muted-foreground">
            Sign in with Google to grant Gmail read and send access to the backend.
          </p>
        </div>
        {searchParams?.error ? (
          <div className="mb-5 rounded-2xl border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {decodeURIComponent(searchParams.error)}
          </div>
        ) : null}
        <Button asChild className="w-full">
          <a href={authLoginUrl}>Continue with Google</a>
        </Button>
      </div>
    </main>
  );
}
