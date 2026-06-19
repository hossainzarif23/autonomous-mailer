# AGENTS.md

## Project Overview
- **Project:** Autonomous Email Agent
- **Purpose:** a full-stack Gmail assistant — Google OAuth, FastAPI, LangChain/LangGraph agents, human-in-the-loop approval, and a conversation-style dashboard UI that reads, summarizes, researches, drafts, and sends email.
- **Structure:** `backend/` is the FastAPI API service; `frontend/` is the Next.js client.

For full product context, read [README.md](./README.md). For the phased build plan and architecture notes, read [IMPLEMENTATION_PLAN_V2.md](./IMPLEMENTATION_PLAN_V2.md).

## Repository Map
- `backend/`: FastAPI API for auth (Google OAuth), Gmail integration, LangChain/LangGraph agent orchestration, SSE streaming, HITL approval resume, and Postgres persistence. Read `backend/AGENTS.md` before changing backend code.
- `frontend/`: Next.js 14 App Router client for login, dashboard, conversation sidebar, structured chat rendering, approval modal, and SSE notifications. Read `frontend/AGENTS.md` before changing frontend code.
- `README.md`: current source of truth for product purpose, status, architecture, API overview, and env vars.
- `IMPLEMENTATION_PLAN_V2.md`: original phased implementation plan and architecture direction.

## Commands
This is a split-stack monorepo with no shared package manager. Run commands inside each package directory.

- **Backend** (`backend/`): install `pip install -r requirements.txt`; dev `uvicorn app.main:app --reload`; migrations `alembic upgrade head`; tests `python -m unittest discover -s tests`; compile check `python -m compileall app`
- **Frontend** (`frontend/`): install `npm install`; dev `npm run dev`; build `npm run build`; lint `npm run lint`

See each package's AGENTS.md for full details and exact invocations.

## Architecture Rules
- Keep the split clean: backend owns auth, Gmail, agent orchestration, persistence, and all privileged operations; frontend is a client-rendered UI only.
- Auth is cookie-based, not bearer tokens. The backend sets an httpOnly `access_token` JWT cookie during Google OAuth callback; the frontend sends it automatically via `withCredentials`. Never put tokens in Authorization headers client-side.
- Two persistence layers share one Postgres database: app tables (users, conversations, email_drafts, notifications) managed by Alembic/SQLAlchemy, and LangGraph checkpoint tables managed automatically by `AsyncPostgresSaver.setup()` at startup.
- `DATABASE_URL` (asyncpg, `postgresql+asyncpg://`) is for SQLAlchemy; `DATABASE_URL_PSYCOPG` (psycopg, `postgresql://`) is for LangGraph checkpointing and Alembic. Both point to the same DB.
- The conversation ID is the coordinator's LangGraph `thread_id`. Sub-agents use user-scoped thread IDs (e.g. `mail_reader_{user_id}`).
- The final `send_email` tool is the human-in-the-loop approval boundary. A draft is persisted before sending; LangGraph interrupts; resume happens via `Command(resume=...)`.
- SSE is used in two places: `/api/chat/message` for request-scoped assistant streaming, and `/api/notifications/stream` for long-lived approval/send notifications.
- The LLM is OpenRouter via `langchain-openrouter` (see `backend/app/agents/llm.py` for the exact model). Web search is Tavily.

## Workflow Rules
- Keep changes small and scoped to the current task.
- After meaningful changes, run the smallest relevant verification step and report what was run.
- Prefer local verification (backend compile check / unittest, frontend `npm run lint` / `build`) over broad end-to-end work unless a task truly spans both services.
- Prefer local skills before remote docs lookups; use the LangChain docs MCP server only when current official references are still needed after the skills.

## Pointers
- Read `frontend/AGENTS.md` for frontend-local commands, UI constraints, and component guidance.
- Read `backend/AGENTS.md` for backend-local commands, API constraints, and LangChain/LangGraph integration guidance.
- Read `README.md` for the full product, API, and env-var reference.
- Keep deep, evolving knowledge in normal docs rather than growing this root file.
