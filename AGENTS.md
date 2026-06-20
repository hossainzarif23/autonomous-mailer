# AGENTS.md

## Project Overview
- **Project:** Autonomous Email Agent
- **Purpose:** a full-stack Gmail assistant — Google OAuth, FastAPI, LangChain/LangGraph agents, human-in-the-loop approval, and a conversation-style dashboard UI that reads, summarizes, researches, drafts, and sends email.
- **Structure:** `backend/` is the FastAPI API service; `frontend/` is the Next.js client.

For full product context, read [README.md](./README.md). For the phased build plan and architecture notes, read [IMPLEMENTATION_PLAN_V2.md](./IMPLEMENTATION_PLAN_V2.md).

## Repository Map
- `backend/`: FastAPI API for auth (Google OAuth), Gmail integration, LangChain/LangGraph agent orchestration, SSE streaming, HITL approval resume, and Postgres persistence. Read `backend/AGENTS.md` before changing backend code; see `backend/docs/` for its detailed architecture and environment.
- `frontend/`: Next.js 14 App Router client for login, dashboard, conversation sidebar, structured chat rendering, approval modal, and SSE notifications. Read `frontend/AGENTS.md` before changing frontend code; see `frontend/docs/` for its detailed architecture and environment.
- `README.md`: current source of truth for product purpose, status, architecture, API overview, and env vars.
- `IMPLEMENTATION_PLAN_V2.md`: original phased implementation plan and architecture direction.

## Commands
This is a split-stack monorepo with no shared package manager. Run commands inside each package directory.

- **Backend** (`backend/`): install `pip install -r requirements.txt`; dev `uvicorn app.main:app --reload`; migrations `alembic upgrade head`; tests `python -m unittest discover -s tests`; compile check `python -m compileall app`
- **Frontend** (`frontend/`): install `npm install`; dev `npm run dev`; build `npm run build`; lint `npm run lint`

See each package's AGENTS.md for full details and exact invocations.

## Architecture Rules
- Keep the split clean: backend owns auth, Gmail, agent orchestration, persistence, and all privileged operations; frontend is a client-rendered UI only.
- Auth is cookie-based, not bearer tokens. The backend sets an httpOnly `access_token` JWT cookie during the Google OAuth callback; the frontend sends it automatically via `withCredentials`. Never put tokens in Authorization headers client-side. (Backend owns setting the cookie; frontend only checks cookie *presence*.)
- One Postgres database backs two persistence layers: app tables (Alembic/SQLAlchemy) and LangGraph checkpoint tables. The exact DSN env vars and startup wiring live in `backend/AGENTS.md` and `backend/docs/environment.md`.
- Conversation IDs are the coordinator's LangGraph `thread_id`; sub-agents use user-scoped thread IDs. Thread-scoping specifics live in `backend/AGENTS.md`.
- The final `send_email` tool is the human-in-the-loop approval boundary: a draft is persisted before sending, then LangGraph interrupts and resumes on approval. The exact HITL/resume mechanics live in `backend/AGENTS.md` and `backend/docs/architecture.md`.
- SSE is used in two places: `/api/chat/message` for request-scoped assistant streaming, and `/api/notifications/stream` for long-lived approval/send notifications.
- The LLM is OpenRouter via `langchain-openrouter` (exact model ID in `backend/app/agents/llm.py`); web search is Tavily.

## Workflow Rules
- Keep changes small and scoped to the current task.
- After meaningful changes, run the smallest relevant verification step and report what was run.
- Prefer local verification (backend compile check / unittest, frontend `npm run lint` / `build`) over broad end-to-end work unless a task truly spans both services.
- Prefer local skills before remote docs lookups; use the LangChain docs MCP server only when current official references are still needed after the skills.

## Pointers
- Read `frontend/AGENTS.md` for frontend-local commands, UI constraints, and component guidance; `frontend/docs/architecture.md` and `frontend/docs/environment.md` for frontend detail.
- Read `backend/AGENTS.md` for backend-local commands, API constraints, and LangChain/LangGraph integration guidance; `backend/docs/architecture.md` and `backend/docs/environment.md` for backend detail.
- Read `README.md` for the full product, API, and env-var reference.
- Keep deep, evolving knowledge in the `docs/` directories rather than growing the AGENTS.md files.
