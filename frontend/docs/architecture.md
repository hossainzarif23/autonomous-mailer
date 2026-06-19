# Frontend Architecture

This is the detailed architecture of the Next.js frontend in `frontend/`.
For commands, conventions, and rules see [`../AGENTS.md`](../AGENTS.md).
For environment variables see [`environment.md`](environment.md).
For product-level context see [`../../README.md`](../../README.md).

## Tech Stack
- **Framework:** Next.js 14 (`^14.2.0`) App Router, React 18 (`^18.3.1`), TypeScript 5.6 (strict).
- **Styling:** Tailwind CSS 3, `tailwindcss-animate`, custom HSL CSS-variable theme, lucide-react icons.
- **State:** Zustand (`^4.5.5`) — 3 stores + a toast store.
- **Data:** Axios (`^1.7.7`) for REST, raw `fetch` + `ReadableStream` for SSE chat streaming, browser `EventSource` for notifications.
- **UI primitives:** Radix UI (`@radix-ui/react-dialog`, `react-toast`, `react-slot`) via shadcn/ui (`components.json`).
- **Utilities:** `clsx` + `tailwind-merge` (`cn()`), `class-variance-authority`.
- **Package manager:** npm (`package-lock.json`, lockfileVersion 3). No pnpm/yarn.

## App Router Structure (`app/`)
- `layout.tsx` (server component): root `<html>/<body>`, sets metadata (`title: "Email Agent"`), imports `globals.css`, wraps children in `<Providers>`.
- `page.tsx` (server component): reads `access_token` cookie via `cookies()` from `next/headers`, `redirect()` to `/dashboard` if present else `/login`.
- `providers.tsx` (`"use client"`): renders `children` + global `<Toaster/>`.
- `login/page.tsx` (server component): marketing/login card. The "Continue with Google" button is an `<a href>` pointing to `${NEXT_PUBLIC_API_URL}/auth/login` — i.e. **the backend initiates OAuth**. Reads `searchParams.error` for OAuth failure messages.
- `auth/callback/page.tsx` (server component): static "Signing you in" spinner. The backend completes the OAuth callback and redirects to the dashboard; this page is transitional only and does nothing functional.
- `dashboard/layout.tsx` (server component): wraps dashboard in a grid background `<div>` and **mounts `<ApprovalModal/>` globally** so any SSE-triggered approval can open it.
- `dashboard/page.tsx` (`"use client"`): the main app. Calls `useAuth()` and `useSSE(status === "authenticated")`. Shows a loading spinner while `idle`/`loading`, then renders `<ConversationSidebar/>` + `<ChatWindow/>` + `<InputBar/>` in a `grid-cols-[300px_minmax(0,1fr)]` layout.
- `error.tsx` + `global-error.tsx` (`"use client"`): Next.js error boundaries with "Try Again"/"Back to Dashboard" buttons.

## Components (`components/`)
- `approval/ApprovalModal.tsx` (`"use client"`): Radix Dialog bound to `useApprovalStore`. Lets the user edit `to`/`subject`/`body`, write rejection `feedback`, and approve or request rewrite. POSTs to `api.post("/approve/{draft_id}")` with `action: "approve" | "edit" | "reject"`, sending `edited_to/subject/body` and `feedback`. Uses `markPending`/`clearPending` to prevent re-opening the same draft mid-submission; on error reopens the modal.
- `chat/ChatWindow.tsx` (`"use client"`): reads `messages` from `chatStore`; shows starter prompt cards when empty, else maps messages to `<ConversationTurn/>`.
- `chat/ConversationSidebar.tsx` (`"use client"`): on mount hydrates the conversation list via `useChat().refreshConversations()` and auto-loads the first conversation. Renders user card (name/email + `gmail_scope_granted` badge), "New Chat" button, conversation list (active highlight + date), logout button, streaming indicator. Uses `getErrorMessage` with a Retry affordance.
- `chat/ConversationTurn.tsx` (`"use client"`): the rich renderer. Splits assistant `content_blocks` into action pills, status pills, and content blocks; `BlockRenderer` switch over block types: `markdown`, `status`, `tool_action`, `email_list` (maps `EmailCard`s), `summary`, `research_report`, `draft_email` (inline `DraftEmailCard`), `system_notice`. User turns render right-aligned as a primary bubble.
- `chat/EmailCard.tsx` (`"use client"`): single `EmailSummary` card (subject, from, date, snippet).
- `chat/InputBar.tsx` (`"use client"`): controlled input; submits via `useChat().sendMessage`; disabled while `isStreaming`; restores message text on send failure.
- `chat/MarkdownResponse.tsx` (`"use client"`): **custom hand-rolled markdown renderer** (headings H1–H3, blockquotes, ordered/unordered lists, inline `**bold**`, `*italic*`, `` `code` ``). No `react-markdown` dependency.
- `chat/MessageBubble.tsx`: a simpler legacy bubble (no `"use client"`, reads `message.metadata?.is_waiting_approval`). Not referenced by the active render path (`ConversationTurn` is used instead) — likely dead/legacy.
- `notifications/NotificationToast.tsx` (`"use client"`): trivial wrapper rendering `<Toaster/>`. The global `<Toaster/>` is already mounted in `providers.tsx`, so this appears redundant/unused.
- `ui/*`: standard shadcn/ui primitives — `button` (cva variants: default/outline/ghost; sizes: default/sm/lg; supports `asChild`), `dialog`, `input`, `textarea`, `toast`, `toaster`. All forward refs, all use `cn()`.

## Hooks (`hooks/`)
- `useAuth.ts` (`"use client"`): on mount when `status === "idle"`, calls `api.get("/auth/me")` to hydrate the `authStore` with `UserProfile`; `logout()` POSTs `/auth/logout` then `window.location.href = "/login"`. Exposes `{ user, status, refreshUser, logout }`.
- `useChat.ts` (`"use client"`): the core chat orchestration. `refreshConversations()` (GET `/chat/conversations`), `hydrateConversation` (GET `/chat/history/{id}`), `createConversation` (POST `/chat/conversations`), `loadConversation`, `reloadConversation`, and **`sendMessage`** which uses **`fetch`** (not axios) to POST `/chat/message` and then **manually parses the SSE stream** via `ReadableStream` reader + `TextDecoder`, splitting on `\n\n` boundaries and parsing `data:` lines as `SSEEvent`. Handles event types `turn_started`, `token` (appends content), `approval_pending` (sets `waiting_approval` + reloads history), `turn_completed`/`done` (reloads history), `error`. Uses optimistic assistant placeholder message with `crypto.randomUUID()` ids; removes it if empty at the end. Surfaces errors via `useToast`.
- `useSSE.ts` (`"use client"`): opens a long-lived `EventSource` to `${NEXT_PUBLIC_API_URL}/notifications/stream` with `withCredentials: true`. Handles `approval_required` (opens `ApprovalModal` via store), `email_sent`, `email_rejected`, `error` (toasts + `clearPending`). Refreshes active conversation history when events match `activeConversationId`. Exponential backoff reconnect (capped at 10s). Enabled only when authenticated.
- `use-toast.ts` (`"use client"`): defines a `useToastStore` (Zustand) with `toasts`/`push`/`dismiss`, plus `useToast()` returning `{ toast }`. Custom toast implementation (not shadcn's `useToast` hook).

## Lib (`lib/`)
- `api.ts`: creates the `axios` instance with `baseURL = NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"`, `withCredentials: true`, JSON content-type. Response interceptor: on **401** (and not already on `/login`), redirects `window.location.href = "/login?next=..."`. Normalizes error messages via `getErrorMessage` (handles FastAPI-style `detail` arrays with `msg`/`loc`, string detail, `{error}` field, generic `Error.message`). Exports `api` and `getErrorMessage`. Uses a `_authRedirectTriggered` guard to prevent redirect loops.
- `utils.ts`: the standard shadcn `cn()` helper (`twMerge(clsx(...))`).

## Stores (`stores/`) — Zustand, all `"use client"`
- `authStore.ts`: `{ user, status: "idle"|"loading"|"authenticated"|"unauthenticated", setUser, setStatus, reset }`.
- `chatStore.ts`: `{ conversations, activeConversationId, messages, isStreaming, setConversations, setActiveConversationId, setMessages, appendMessage, updateMessage, removeMessage, setStreaming, reset }`.
- `approvalStore.ts`: `{ isOpen, draft, originalDraft, feedback, pendingDraftIds, open, close, markPending, clearPending, isPending, updateDraft, setFeedback }`. `open()` refuses to open a draft already in `pendingDraftIds` (prevents re-prompting while in flight).

## Types (`types/index.ts`)
Centralized type definitions:
- `MessageRole` ("user"|"assistant"), `TurnStatus`.
- `Conversation`, `UserProfile` (incl. `gmail_scope_granted: boolean`), `EmailSummary`, `EmailDraft`, `ApprovalAction`, `ApprovalDraftPayload`.
- **`ChatContentBlock`** discriminated union: `markdown | status | tool_action | email_list | summary | research_report | draft_email | system_notice`.
- `ChatMessage` (with optional `content_blocks`, `status`, `turn_id`, `metadata.draft_id`/`is_waiting_approval`).
- **`SSEEvent`** with `type` union: `token | turn_started | action_started | action_completed | artifact_available | approval_pending | approval_required | email_sent | email_rejected | turn_completed | error | done | ping`.

## Routing & Auth Flow
Auth is **cookie-based, not bearer tokens**. The frontend never reads the token value (except cookie *presence* checks) and never puts it in an Authorization header.
1. **Unauthenticated user hits `/`** → `app/page.tsx` (server component) calls `cookies().get("access_token")`. No cookie → `redirect("/login")`.
2. **`/login`** (`app/login/page.tsx`, server): renders "Continue with Google" as an `<a>` to `${NEXT_PUBLIC_API_URL}/auth/login`. The **backend initiates Google OAuth**. Shows `?error=...` banners.
3. **Middleware** (`frontend/middleware.ts`, edge, matcher `["/dashboard/:path*", "/login"]`): reads the `access_token` cookie. If `pathname.startsWith("/dashboard")` and **no token** → `/login`; if on `/login` with a token → `/dashboard`. This is edge-runtime route protection on cookie *presence* (validation is client-side via `/auth/me`).
4. **Backend OAuth callback** → FastAPI exchanges the code, sets the `access_token` httpOnly cookie, redirects to `/dashboard`. (`app/auth/callback/page.tsx` is just a spinner shown during the redirect window.)
5. **`/dashboard`** (`app/dashboard/page.tsx`, `"use client"`): calls `useAuth()` which, on mount with `status === "idle"`, GETs `/auth/me` (cookies included). Success → `status: "authenticated"` + `user`. Failure → `reset()` → `status: "unauthenticated"`. Calls `useSSE(status === "authenticated")` — opens `EventSource` to `/notifications/stream` only once authenticated.
6. **Axios 401 interceptor** (`lib/api.ts`): any API response with status 401 (and not already on `/login`) triggers `window.location.href = "/login?next=<encoded path>"`. Guarded by `_authRedirectTriggered` to avoid loops.
7. **Logout** (`useAuth.logout`): POSTs `/auth/logout` (backend clears the `access_token` cookie), then `window.location.href = "/login"`, and `authStore.reset()`.

### Cookie handling summary
- Cookie name: **`access_token`**.
- Set/cleared by: **FastAPI backend** (the frontend never sets it).
- Sent automatically via `withCredentials: true` (axios), `credentials: "include"` (fetch), and `withCredentials: true` (EventSource).
- Read by frontend **only for presence checks** in `middleware.ts` and `app/page.tsx` — never for the token value. **No bearer tokens, no Firebase ID tokens.**

## Approval Sub-Flow (cross-cutting)
- During chat streaming (`useChat`), an `approval_pending` SSE event marks the assistant message `waiting_approval` and reloads history.
- Separately, `useSSE` listens for `approval_required` events on the notifications stream and calls `approvalStore.open(draft)`, which opens the global `<ApprovalModal/>` (mounted in `dashboard/layout.tsx`). The modal POSTs to `/approve/{draft_id}` with `approve | edit | reject`; on resolution, SSE `email_sent` / `email_rejected` events call `clearPending` and toast the result.

## Server vs Client Split
- **Server components** for routes that read cookies / do redirects: `app/layout.tsx`, `app/page.tsx`, `app/login/page.tsx`, `app/auth/callback/page.tsx`, `app/dashboard/layout.tsx`.
- **Client islands** (`"use client"`) for everything interactive: `app/providers.tsx`, `app/dashboard/page.tsx`, all `components/*` except `MessageBubble.tsx`, all `hooks/*`, all `stores/*`.

## Config Files
- `next.config.js` — minimal: `{ reactStrictMode: true }` (CommonJS). No `output: "export"`, no `images` config, no rewrites, no env passthrough. (The app is **not** a static export.)
- `tailwind.config.ts` — content globs for `app`, `components`, `hooks`, `lib`, `stores`; shadcn color tokens; `darkMode: ["class"]` (configured but no dark theme defined); custom `dashboard-grid` background image; `tailwindcss-animate` plugin.
- `postcss.config.js` — `tailwindcss` + `autoprefixer`.
- `tsconfig.json` — `strict: true`, `target: ES2017`, `moduleResolution: "bundler"`, `jsx: "preserve"`, `incremental: true`, path alias `"@/*": ["./*"]`.
- `components.json` — shadcn/ui config: `style: "default"`, `rsc: true`, `tsx: true`, base color `slate`, `cssVariables: true`, aliases `@/components` and `@/lib/utils`.

## Repository Layout
```
frontend/
  middleware.ts
  next.config.js
  tailwind.config.ts
  postcss.config.js
  tsconfig.json
  components.json
  package.json
  package-lock.json
  .env.local.example
  app/
    layout.tsx
    page.tsx
    providers.tsx
    globals.css
    error.tsx
    global-error.tsx
    login/page.tsx
    auth/callback/page.tsx
    dashboard/
      layout.tsx
      page.tsx
  components/
    approval/ApprovalModal.tsx
    chat/
      ChatWindow.tsx
      ConversationSidebar.tsx
      ConversationTurn.tsx
      EmailCard.tsx
      InputBar.tsx
      MarkdownResponse.tsx
      MessageBubble.tsx
    notifications/NotificationToast.tsx
    ui/
      button.tsx
      dialog.tsx
      input.tsx
      textarea.tsx
      toast.tsx
      toaster.tsx
  hooks/
    useAuth.ts
    useChat.ts
    useSSE.ts
    use-toast.ts
  lib/
    api.ts
    utils.ts
  stores/
    authStore.ts
    chatStore.ts
    approvalStore.ts
  types/
    index.ts
```
