# AGENTS.md

## Project Overview
- **Area:** Frontend client for the Autonomous Email Agent.
- **Goal:** provide a Next.js 14 App Router client for Google-authenticated login, a conversation-style dashboard with a sidebar, structured chat rendering (markdown, email cards, research/summary blocks, draft artifacts), an approval modal (approve/edit/reject), and live SSE notifications.
- **Stack:** Next.js 14 (App Router), React 18, TypeScript (strict), Tailwind CSS 3, Zustand (state), Axios (REST) + fetch/EventSource (SSE), Radix UI primitives via shadcn/ui, lucide-react icons. Package manager is **npm**.

For full product context, read [../README.md](../README.md). For repo-wide rules, read [../AGENTS.md](../AGENTS.md).
For the detailed frontend architecture, read [docs/architecture.md](docs/architecture.md). For environment variables, read [docs/environment.md](docs/environment.md).

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

## Conventions
- App Router with `app/`; server components for cookie-reading routes, client islands marked `"use client"` for everything interactive (all `components/*` except `MessageBubble.tsx`, all `hooks/*`, all `stores/*`).
- State management via Zustand stores as the single UI source of truth; components select slices directly.
- REST via the shared axios instance in `lib/api.ts` (cookies, 401 auto-redirect). The **streaming** chat endpoint uses raw `fetch` + `ReadableStream` (axios can't stream). Notifications use browser `EventSource`. All send `withCredentials`/`credentials: "include"`.
- Pick the data-access path by need (all send credentials and hit `NEXT_PUBLIC_API_URL`):

  | Need | Use | Why |
  |---|---|---|
  | One-shot REST call | shared axios `api` instance (`lib/api.ts`) | JSON in/out, 401 auto-redirect, uniform error normalization |
  | Streaming chat (SSE) | raw `fetch` + `ReadableStream` | axios can't stream tokens incrementally |
  | Long-lived notifications (SSE) | browser `EventSource` (`useSSE.ts`) | native auto-reconnect for server-pushed events |

- Imports use the `@/*` alias (e.g. `@/stores/chatStore`, `@/components/ui/button`, `@/lib/api`).
- UI: shadcn/ui primitives + Tailwind; custom HSL CSS-variable theme in `globals.css` (slate base, emerald primary, orange accent, `--radius: 1rem`); heavy large rounded radii, layered gradients, soft shadows; `darkMode: ["class"]` configured but no dark theme defined.
- Errors: `getErrorMessage(error, fallback)` widely; user-facing failures via `useToast`; server components rely on `error.tsx`/`global-error.tsx`.
- Auth is **cookie-based, not bearer tokens** — the frontend never reads the token value and never puts it in an Authorization header; only cookie *presence* is checked in `middleware.ts`/`app/page.tsx`.

## Do
- Mark interactive files with `"use client"` at the top.
- Use the shared `api` axios instance for REST and `withCredentials`/`credentials: "include"` everywhere so the httpOnly auth cookie is sent.
- Use shadcn/ui primitives (`components/ui/*`) before writing custom markup.
- Use Zustand stores for shared UI state; keep selectors granular.
- Use `getErrorMessage` for consistent FastAPI error rendering, and `useToast` for user-facing failures.
- Keep the API base URL from `NEXT_PUBLIC_API_URL` (with the `http://localhost:8000/api` fallback) — it is duplicated in `api.ts`, `useChat.ts`, and `useSSE.ts`; keep them in sync.

## Don't
- Do not use Firebase, bearer tokens, or Next.js Server Actions/Route Handlers for core behavior — this is a client-rendered app calling the FastAPI backend.
- Do not run `pnpm ...` — this repo uses **npm**. Do not claim a `test` script exists.
- Do not add `output: "export"` to `next.config.js` or assume static-export behavior.
- Do not reopen the ApprovalModal for a draft already in `approvalStore.pendingDraftIds` (prevents stale SSE re-prompting mid-submission).

## Testing
- No frontend test setup exists. No test script, no framework, no test files.
- If adding tests later, add a `test` script and a framework (e.g. vitest) to `package.json` and create the config. Until then, rely on `npm run lint` and `npm run build` (which type-checks).

## Required Skills
- **Use `nextjs`** for App Router structure, static export behavior, routing, layout, and build issues.
- **Use `shadcn`** for component composition, dialogs, forms, sheets, overlays, and design-system consistency.
- **Use `react-best-practices`** for state flow, rendering, TSX decisions, and modern React usage.

## Related Docs
- [docs/architecture.md](docs/architecture.md) — full frontend architecture (App Router structure, components, hooks, stores, auth flow, approval sub-flow, config files).
- [docs/environment.md](docs/environment.md) — env vars and notes.
- [../README.md](../README.md) — product purpose, API overview.
- [../backend/AGENTS.md](../backend/AGENTS.md) — backend contract (SSE event names, content block types, `/approve` request shape, auth cookie).
