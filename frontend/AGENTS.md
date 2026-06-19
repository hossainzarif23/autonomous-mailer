# AGENTS.md

## Project Overview
- **Area:** Frontend client for the Autonomous Email Agent.
- **Goal:** provide a Next.js 14 App Router client for Google-authenticated login, a conversation-style dashboard with a sidebar, structured chat rendering (markdown, email cards, research/summary blocks, draft artifacts), an approval modal (approve/edit/reject), and live SSE notifications.
- **Stack:** Next.js 14 (App Router), React 18, TypeScript (strict), Tailwind CSS 3, Zustand (state), Axios (REST) + fetch/EventSource (SSE), Radix UI primitives via shadcn/ui, lucide-react icons. Package manager is **npm**.

For full product context, read [../README.md](../README.md). For repo-wide rules, read [../AGENTS.md](../AGENTS.md).

## Commands
Run from `frontend/`. Uses **npm** (`package-lock.json`, lockfileVersion 3). No pnpm/yarn.

```bash
npm install
npm run dev        # next dev  (http://localhost:3000)
npm run build      # next build (also runs TypeScript type checking)
npm run start      # next start
npm run lint       # next lint
```

Notes:
- There is **no `test` script** and no test framework (no jest/vitest/playwright). No test files exist.
- There is **no `type-check` script** — TypeScript is checked via `npm run build`. To type-check without a full build: `npx tsc --noEmit`.
- There is **no ESLint config file** — `next lint` relies on `eslint-config-next` defaults (it may prompt to create a config on first run).
- There is **no Prettier** config.
- `next.config.js` is minimal (`{ reactStrictMode: true }`); there is **no `output: "export"`** — the app is not a static export.

## Environment
Copy `.env.local.example` to `.env.local`. Required values:
- `NEXT_PUBLIC_API_URL` — backend API base, e.g. `http://localhost:8000/api` (hardcoded fallback matches this).
- `NEXT_PUBLIC_APP_NAME` — declared in the example but not referenced in code.

All env vars are `NEXT_PUBLIC_` (client-exposed). There is no Firebase config.

## Architecture

### App Router structure (`app/`)
- `layout.tsx` (server): root `<html>/<body>`, metadata title "Email Agent", imports `globals.css`, wraps children in `<Providers>`.
- `page.tsx` (server): reads `access_token` cookie via `cookies()` from `next/headers`, redirects to `/dashboard` if present else `/login`.
- `providers.tsx` (`"use client"`): renders children + global `<Toaster/>`.
- `login/page.tsx` (server): "Continue with Google" button is an `<a href>` to `${NEXT_PUBLIC_API_URL}/auth/login` — **the backend initiates OAuth**. Reads `searchParams.error` for OAuth failure messages.
- `auth/callback/page.tsx` (server): static "Signing you in" spinner — the backend completes the OAuth callback and redirects; this page is transitional only.
- `dashboard/layout.tsx` (server): wraps dashboard and **mounts `<ApprovalModal/>` globally** so any SSE-triggered approval can open it.
- `dashboard/page.tsx` (`"use client"`): calls `useAuth()` + `useSSE(status === "authenticated")`; renders `<ConversationSidebar/>` + `<ChatWindow/>` + `<InputBar/>` in a `grid-cols-[300px_minmax(0,1fr)]` layout.
- `error.tsx` / `global-error.tsx` (`"use client"`): Next.js error boundaries.

### Components (`components/`)
- `approval/ApprovalModal.tsx`: Radix Dialog bound to `useApprovalStore`. Edits to/subject/body, writes rejection feedback, POSTs to `/approve/{draft_id}` with `action: "approve"|"edit"|"reject"`. Uses `markPending`/`clearPending` to prevent re-opening the same draft mid-submission.
- `chat/ChatWindow.tsx`: renders starter prompt cards when empty, else maps `chatStore.messages` to `<ConversationTurn/>`.
- `chat/ConversationSidebar.tsx`: hydrates conversation list on mount, auto-loads first conversation, renders user card (with `gmail_scope_granted` badge), New Chat, conversation list, logout.
- `chat/ConversationTurn.tsx`: the rich renderer — splits assistant `content_blocks` into action/status pills and content blocks via `BlockRenderer` switch: `markdown`, `status`, `tool_action`, `email_list`, `summary`, `research_report`, `draft_email`, `system_notice`. User turns render right-aligned.
- `chat/EmailCard.tsx`, `chat/InputBar.tsx`, `chat/MarkdownResponse.tsx` (custom hand-rolled markdown renderer — no react-markdown dependency).
- `chat/MessageBubble.tsx`: legacy, appears unused (the active path uses `ConversationTurn`).
- `notifications/NotificationToast.tsx`: thin `<Toaster/>` wrapper (the global Toaster is already in `providers.tsx`; this appears redundant).
- `ui/*`: standard shadcn/ui primitives (`button` with cva variants, `dialog`, `input`, `textarea`, `toast`, `toaster`), all forward refs, all use `cn()`.

### Hooks (`hooks/`)
- `useAuth.ts`: on mount (status `idle`) GETs `/auth/me` to hydrate `authStore`; `logout()` POSTs `/auth/logout` then redirects to `/login`. Exposes `{ user, status, refreshUser, logout }`.
- `useChat.ts`: conversations CRUD + **`sendMessage`** which uses **`fetch`** (not axios) to POST `/chat/message` and manually parses the SSE stream via `ReadableStream` + `TextDecoder`, splitting on `\n\n` and parsing `data:` lines as `SSEEvent`. Handles `turn_started`, `token`, `approval_pending` (sets `waiting_approval` + reloads history), `turn_completed`/`done` (reload history), `error`.
- `useSSE.ts`: long-lived `EventSource` to `${NEXT_PUBLIC_API_URL}/notifications/stream` with `withCredentials: true`. Handles `approval_required` (opens ApprovalModal), `email_sent`, `email_rejected`, `error` (toasts + `clearPending`). Reloads active conversation history on matching events. Exponential backoff reconnect (capped 10s). Enabled only when authenticated.
- `use-toast.ts`: custom Zustand-backed `useToastStore` + `useToast()` (not shadcn's useToast).

### Lib / Stores / Types
- `lib/api.ts`: shared `axios` instance, `baseURL = NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"`, `withCredentials: true`. Response interceptor: on **401** (and not on `/login`) redirects to `/login?next=...`, guarded by `_authRedirectTriggered` to prevent loops. Exports `getErrorMessage` (handles FastAPI `detail` arrays with `msg`/`loc`, string detail, `{error}` field).
- `lib/utils.ts`: shadcn `cn()` (`twMerge(clsx(...))`).
- `stores/` (Zustand, all `"use client"`): `authStore` (`user`, `status: idle|loading|authenticated|unauthenticated`), `chatStore` (`conversations`, `activeConversationId`, `messages`, `isStreaming`, ...), `approvalStore` (`isOpen`, `draft`, `pendingDraftIds`, `open` refuses drafts already in `pendingDraftIds`, `markPending`, `clearPending`).
- `types/index.ts`: `Conversation`, `UserProfile` (incl. `gmail_scope_granted`), `EmailSummary`, `EmailDraft`, `ChatContentBlock` discriminated union (`markdown|status|tool_action|email_list|summary|research_report|draft_email|system_notice`), `ChatMessage`, `SSEEvent` (type union: `token|turn_started|...|approval_required|email_sent|email_rejected|...|done|ping`).

### Routing & Auth Flow
Auth is **cookie-based, not bearer tokens**. The frontend never reads the token value and never puts it in an Authorization header.
1. `app/page.tsx` (server) checks `access_token` cookie presence → redirects to `/login` or `/dashboard`.
2. `/login` links to the backend `${NEXT_PUBLIC_API_URL}/auth/login` (backend initiates Google OAuth).
3. `middleware.ts` (edge, matcher `["/dashboard/:path*", "/login"]`) checks cookie **presence**: no token on `/dashboard` → `/login`; token on `/login` → `/dashboard`. Validation happens client-side via `/auth/me`.
4. Backend OAuth callback sets the httpOnly `access_token` cookie and redirects to `/dashboard`.
5. `useAuth()` GETs `/auth/me` (cookies included) to hydrate the user; axios 401 interceptor redirects to `/login` on failure.
6. `useSSE` opens the notifications `EventSource` only once authenticated.

## Conventions
- App Router with `app/`; server components for cookie-reading routes, client islands marked `"use client"` for everything interactive (all `components/*` except `MessageBubble.tsx`, all `hooks/*`, all `stores/*`).
- State management via Zustand stores as the single UI source of truth; components select slices directly.
- REST via the shared axios instance in `lib/api.ts` (cookies, 401 auto-redirect). The **streaming** chat endpoint uses raw `fetch` + `ReadableStream` (axios can't stream). Notifications use browser `EventSource`. All send `withCredentials`/`credentials: "include"`.
- Imports use the `@/*` alias (e.g. `@/stores/chatStore`, `@/components/ui/button`, `@/lib/api`).
- UI: shadcn/ui primitives + Tailwind; custom HSL CSS-variable theme in `globals.css` (slate base, emerald primary, orange accent, `--radius: 1rem`); heavy large rounded radii, layered gradients, soft shadows; `darkMode: ["class"]` configured but no dark theme defined.
- Errors: `getErrorMessage(error, fallback)` widely; user-facing failures via `useToast`; server components rely on `error.tsx`/`global-error.tsx`.
- Essentially client-driven after the initial server redirect; no SSR data fetching beyond cookie checks.

## Do
- Mark interactive files with `"use client"` at the top.
- Use the shared `api` axios instance for REST and `withCredentials`/`credentials: "include"` everywhere so the httpOnly auth cookie is sent.
- Use shadcn/ui primitives (`components/ui/*`) before writing custom markup.
- Use Zustand stores for shared UI state; keep selectors granular.
- Use `getErrorMessage` for consistent FastAPI error rendering, and `useToast` for user-facing failures.
- Keep the API base URL from `NEXT_PUBLIC_API_URL` (with the `http://localhost:8000/api` fallback) — it is duplicated in `api.ts`, `useChat.ts`, and `useSSE.ts`; keep them in sync.

## Don't
- Do not put the JWT in an `Authorization` header — it is an httpOnly cookie set by the backend.
- Do not read the token value client-side (only check cookie **presence** in `middleware.ts`/`app/page.tsx`).
- Do not use Firebase, bearer tokens, or Next.js Server Actions/Route Handlers for core behavior — this is a client-rendered app calling the FastAPI backend.
- Do not run `pnpm ...` — this repo uses **npm**. Do not claim a `test` script exists.
- Do not add `output: "export"` to `next.config.js` or assume static-export behavior.
- Do not reopen the ApprovalModal for a draft already in `approvalStore.pendingDraftIds` (prevents stale SSE re-prompting mid-submission).

## Testing
- No frontend test setup exists. No test script, no framework, no test files.
- If adding tests later, add a `test` script and a framework (e.g. vitest) to `package.json` and create the config. Until then, rely on `npm run lint` and `npm run build` (which type-checks).

## Related Docs
- `../README.md` for product purpose, API overview, and env vars.
- `../backend/AGENTS.md` for the backend contract (SSE event names, content block types, `/approve` request shape, auth cookie).
