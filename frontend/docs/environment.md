# Frontend Environment

Copy [`../.env.local.example`](../.env.local.example) to `frontend/.env.local`.
All env vars are `NEXT_PUBLIC_` (client-exposed), which is appropriate since this is a client-rendered app.

## Required Variables

| Variable | Example | Used in |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api` | `lib/api.ts`, `hooks/useChat.ts`, `hooks/useSSE.ts`, `app/login/page.tsx` (all with `?? "http://localhost:8000/api"` fallback) |
| `NEXT_PUBLIC_APP_NAME` | `Email Agent` | declared in the example but **not referenced anywhere in code** |

## Notes
- The hardcoded fallback `http://localhost:8000/api` matches the FastAPI backend in `backend/`. The fallback is duplicated in `lib/api.ts`, `hooks/useChat.ts`, and `hooks/useSSE.ts` — keep them in sync when changing the base URL.
- There is **no Firebase config** (`NEXT_PUBLIC_FIREBASE_*`). Auth is cookie-based via the FastAPI backend.
- There is no `.nvmrc`, `.npmrc`, or `engines` field pinning a Node version. `@types/node` is `^22.8.1`, implying Node 22 is the development target.
