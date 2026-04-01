# Autonomous Email Agent

A full-stack Gmail assistant that combines Google OAuth, FastAPI, LangChain/LangGraph agents, human-in-the-loop approval, and a premium conversation-style dashboard UI.

The application can:

- authenticate a user with Google and store Gmail tokens securely
- read recent emails and search Gmail by sender or topic
- summarize threads and individual messages
- draft fresh emails and replies with agent orchestration
- research fresh-email topics on the web before drafting
- pause the final send action for human approval
- resume the interrupted workflow after approve, edit-and-approve, or reject-with-feedback
- stream chat progress and approval notifications to a Next.js dashboard

## Current Status

This repository is no longer a scaffold. It currently includes:

- backend authentication, Gmail service integration, agent system, SSE, and approval resume flow
- frontend login flow, dashboard, conversation sidebar, premium chat rendering, approval modal, and toast notifications
- LangGraph checkpointing with PostgreSQL-backed persistence
- structured conversation rendering with inline summaries, research notes, email result cards, and draft artifacts
- basic backend unit tests for core services and agent factories

The implementation plan that guided the build is available in [`IMPLEMENTATION_PLAN_V2.md`](./IMPLEMENTATION_PLAN_V2.md).

## Architecture

### Backend

The backend is a FastAPI app in [`backend/app`](./backend/app) with these major areas:

- `routers/`
  - `auth.py`: Google OAuth login, callback, logout, current-user endpoint
  - `chat.py`: conversation creation, history loading, streaming chat endpoint
  - `emails.py`: direct Gmail read/search endpoints
  - `approve.py`: approve, edit, or reject draft flows and LangGraph resume
  - `notifications.py`: SSE notification stream and notification list/read APIs
- `agents/`
  - `coordinator.py`: main LangChain agent that routes work
  - `mail_reader_agent.py`: read/search/summarize Gmail tasks
  - `mailing_agent.py`: draft-only agent for fresh emails and replies
  - `web_search_agent.py`: Tavily-backed research agent
  - `tools/`: Gmail tools, web-search tool, and final `send_email` tool
- `services/`
  - `gmail_service.py`: Gmail API integration
  - `auth_service.py`: token validation/refresh and JWT session utilities
  - `hitl_service.py`: HITL interrupt persistence and approval payload serialization
  - `notification_service.py`: per-user in-memory event broadcaster plus persisted notifications
- `models/`: SQLAlchemy models for users, conversations, drafts, and notifications
- `checkpointer.py`: LangGraph PostgreSQL checkpointer setup

### Frontend

The frontend is a Next.js App Router app in [`frontend`](./frontend) with:

- Google-authenticated login and protected dashboard routing
- premium chat UI with turn-based conversation rendering
- conversation sidebar with history loading and new-chat creation
- inline rendering for:
  - markdown-like assistant responses
  - tool/action status chips
  - email result cards
  - research blocks
  - summary blocks
  - draft email artifacts
- approval modal for approve, edit, and reject-with-feedback
- SSE listener for approval requests, send results, and error notifications

## Product Flow

### 1. Login

1. The user opens the frontend.
2. The frontend redirects unauthenticated traffic to `/login`.
3. The backend starts Google OAuth from `/api/auth/login`.
4. On callback, the backend stores encrypted Gmail tokens and sets an `httpOnly` JWT cookie.
5. The user lands on `/dashboard`.

### 2. Chat Request

1. The user types a prompt in the dashboard.
2. The frontend ensures a conversation exists and posts to `/api/chat/message`.
3. The backend constructs an `AgentContext` with:
   - current user
   - current conversation
   - Gmail service
   - DB session
   - notification service
4. The coordinator agent runs with the conversation ID as the LangGraph `thread_id`.
5. Streaming SSE events update the chat UI live.

### 3. Draft + Approval

1. The coordinator drafts an email or reply.
2. The final `send_email` action is wrapped with LangChain human-in-the-loop middleware.
3. LangGraph interrupts before sending.
4. The backend persists the pending draft and broadcasts `approval_required`.
5. The frontend opens the approval modal and also shows the draft inline in the thread.
6. The user can:
   - approve
   - edit then approve
   - reject with feedback
7. The backend resumes the same LangGraph thread with `Command(resume=...)`.
8. If approved, Gmail send happens after resume.
9. If rejected, the coordinator can rewrite the draft, optionally rerunning research for fresh-email workflows.

## Tech Stack

### Backend

- FastAPI
- SQLAlchemy async + Alembic
- PostgreSQL / Neon
- Authlib for Google OAuth
- `google-api-python-client` for Gmail
- LangChain
- LangGraph
- `langgraph-checkpoint-postgres`
- `langchain-openrouter`
- Tavily Python client

### Frontend

- Next.js 14 App Router
- React 18
- Tailwind CSS
- Zustand
- Axios
- Radix UI primitives

## Environment Variables

### Backend

Copy [`backend/.env.example`](./backend/.env.example) to `backend/.env`.

Required values:

- `APP_ENV`
- `APP_URL`
- `SECRET_KEY`
- `JWT_ALGORITHM`
- `JWT_EXPIRY_HOURS`
- `DATABASE_URL`
- `DATABASE_URL_PSYCOPG`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `TOKEN_ENCRYPTION_KEY`
- `OPENROUTER_API_KEY`
- `TAVILY_API_KEY`
- `FRONTEND_URL`

Optional LangSmith tracing:

- `LANGSMITH_TRACING`
- `LANGSMITH_PROJECT`
- `LANGSMITH_ENDPOINT`
- `LANGSMITH_API_KEY`

Important notes:

- `DATABASE_URL` is for SQLAlchemy and uses `postgresql+asyncpg://`
- `DATABASE_URL_PSYCOPG` is for LangGraph checkpointing and uses `postgresql://`
- both URLs point to the same database

### Frontend

Copy [`frontend/.env.local.example`](./frontend/.env.local.example) to `frontend/.env.local`.

Required values:

- `NEXT_PUBLIC_API_URL`
- `NEXT_PUBLIC_APP_NAME`

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL or Neon
- Google Cloud OAuth credentials with Gmail scopes
- OpenRouter API key
- Tavily API key

### Backend Setup

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup

```powershell
cd frontend
npm install
Copy-Item .env.local.example .env.local
npm run dev
```

Frontend default URL:

- `http://localhost:3000`

Backend default URL:

- `http://localhost:8000`

Health check:

- `GET http://localhost:8000/health`

## Database and Persistence

The app uses two persistence layers:

1. Application tables managed through Alembic and SQLAlchemy
   - users
   - conversations
   - email drafts
   - notifications

2. LangGraph checkpoint tables managed automatically by `AsyncPostgresSaver.setup()`
   - used for conversation history and interruption/resume

The initial schema migration lives in [`backend/alembic/versions/001_initial_schema.py`](./backend/alembic/versions/001_initial_schema.py).

## API Overview

### Auth

- `GET /api/auth/login`
- `GET /api/auth/callback`
- `POST /api/auth/logout`
- `GET /api/auth/me`

### Chat

- `POST /api/chat/conversations`
- `GET /api/chat/conversations`
- `GET /api/chat/history/{conversation_id}`
- `POST /api/chat/message`

### Direct Gmail Reads

- `GET /api/emails/recent`
- `GET /api/emails/search`
- `GET /api/emails/{message_id}`

### Approval

- `GET /api/approve/pending`
- `POST /api/approve/{draft_id}`

### Notifications

- `GET /api/notifications/stream`
- `GET /api/notifications`
- `PATCH /api/notifications/{notification_id}/read`

## Conversation UI Model

The dashboard now renders structured assistant turns instead of plain bubbles. Assistant history can contain content blocks such as:

- `markdown`
- `status`
- `tool_action`
- `email_list`
- `summary`
- `research_report`
- `draft_email`
- `system_notice`

This lets the UI present:

- polished prose for the main answer
- action rails for agent activity
- inline email cards for read/search results
- research notes for fresh-email workflows
- first-class draft artifacts with approval state

## Human-in-the-Loop Behavior

The current approval model is:

- the final `send_email` tool is the approval boundary
- a draft is persisted before approval
- the dashboard shows the draft inline and in the modal
- submission closes the modal immediately on the frontend
- a pending-draft guard prevents stale SSE events from reopening the same draft while approval is in flight
- once resume completes, conversation history is refreshed to reflect sent, rejected, rewritten, or failed states

## Testing and Verification

### Backend tests currently in the repo

Located in [`backend/tests`](./backend/tests):

- `test_agent_factories.py`
- `test_agent_tools.py`
- `test_auth_service.py`
- `test_email_parser.py`
- `test_gmail_service.py`
- `test_notification_service.py`

### Useful verification commands

Backend compile check:

```powershell
python -m compileall backend\app
```

Frontend type check:

```powershell
cd frontend
npx tsc --noEmit
```

### Manual end-to-end checks

- log in through Google OAuth
- confirm `/dashboard` loads
- read recent emails
- search by sender or topic
- summarize a thread
- draft a fresh email with research
- approve a draft and verify Gmail send
- reject a draft with feedback and verify rewrite flow
- reload the dashboard and verify structured conversation history persists

## Important Implementation Notes

- The backend returns structured JSON errors in the shape `{ error, detail }`
- SSE is used in two places:
  - `/api/chat/message` for request-scoped assistant streaming
  - `/api/notifications/stream` for long-lived approval and send notifications
- The conversation ID is also the coordinator’s LangGraph `thread_id`
- Only the coordinator thread is conversation-scoped; sub-agents use user-scoped thread IDs
- The project currently uses LangChain v1 style agents and LangGraph v1 checkpointing
- No Docker setup is included in this repository

## Repository Layout

```text
backend/
  alembic/
  app/
    agents/
    middleware/
    models/
    routers/
    schemas/
    services/
    utils/
  tests/
  requirements.txt

frontend/
  app/
  components/
  hooks/
  lib/
  stores/
  types/
  package.json
```

## Roadmap Reference

For the original phased implementation plan, architectural notes, and intended evolution of the system, see:

- [`IMPLEMENTATION_PLAN_V2.md`](./IMPLEMENTATION_PLAN_V2.md)
