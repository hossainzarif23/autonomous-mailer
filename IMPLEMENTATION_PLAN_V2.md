# Autonomous Email Agent System — Implementation Plan v2.0

> **Changelog from v1:** Corrected LLM integration to use `ChatOpenRouter` from `langchain-openrouter`. Corrected agent construction to use `create_agent` (not `create_react_agent`). Replaced closure-based dependency injection with `context_schema` + `ToolRuntime`. Integrated native LangGraph `interrupt()` / `Command(resume=...)` for HITL. Used `AsyncPostgresSaver` for checkpointing. Replaced Tavily LangChain wrapper with direct `TavilyClient`. Removed Docker.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Design](#2-architecture-design)
3. [Technology Stack & Versions](#3-technology-stack--versions)
4. [Project Structure](#4-project-structure)
5. [Database Schema (Neon/PostgreSQL)](#5-database-schema-neonpostgresql)
6. [Google OAuth & Gmail API Setup](#6-google-oauth--gmail-api-setup)
7. [Backend — FastAPI](#7-backend--fastapi)
8. [AI Agent System — LangChain](#8-ai-agent-system--langchain)
9. [Frontend — Next.js](#9-frontend--nextjs)
10. [Real-Time Notifications (SSE)](#10-real-time-notifications-sse)
11. [Human-in-the-Loop — Native LangGraph Pattern](#11-human-in-the-loop--native-langgraph-pattern)
12. [Environment Variables](#12-environment-variables)
13. [API Contract](#13-api-contract)
14. [Security Considerations](#14-security-considerations)
15. [Local Development Setup (No Docker)](#15-local-development-setup-no-docker)
16. [Step-by-Step Implementation Order](#16-step-by-step-implementation-order)

---

## 1. System Overview

An autonomous, multi-agent email assistant that:

- Authenticates users via **Google OAuth 2.0** (Gmail read + send scopes)
- **Reads** emails by recency, topic/keyword, or sender (name or email address)
- **Summarizes** email threads
- **Responds** to emails with **native LangGraph `interrupt()`-based HITL** approval
- **Composes fresh emails** via a web-search → coordinator → mailing agent pipeline
- Sends **real-time notifications** to the frontend after every send action

### High-Level User Journey

```
User opens app
  → Google OAuth login (scopes: gmail.readonly + gmail.send)
  → Lands on Chat UI (new conversation created)
  → Types a natural-language command
      e.g. "Read my last email"
           "Find emails about job opportunities"
           "Summarize emails from BRAC Bank"
           "Reply to the last email from hr@example.com"
           "Write a fresh email to ceo@company.com about AI trends in Bangladesh"
  → Coordinator Agent interprets intent → routes to sub-agent
  → For send/reply: LangGraph interrupt fires → approval modal shown
  → User approves/edits/rejects → graph resumes via Command(resume=...)
  → Notification toast shown after action completes
```

---

## 2. Architecture Design

### 2.1 Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        NEXT.JS FRONTEND                          │
│  ┌────────────┐  ┌──────────────────┐  ┌─────────────────────┐  │
│  │ Auth Pages │  │  Chat Interface  │  │  Approval Modal     │  │
│  │ (OAuth)    │  │  (SSE consumer)  │  │  (HITL)             │  │
│  └────────────┘  └──────────────────┘  └─────────────────────┘  │
└──────────────────────────┬───────────────────────────────────────┘
                           │ HTTPS / SSE
┌──────────────────────────▼───────────────────────────────────────┐
│                       FASTAPI BACKEND                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                     API ROUTERS                             │ │
│  │   /auth   /chat   /emails   /approve   /notifications       │ │
│  └───────────────────────┬─────────────────────────────────────┘ │
│                          │                                       │
│  ┌───────────────────────▼─────────────────────────────────────┐ │
│  │           LANGCHAIN AGENT SYSTEM                            │ │
│  │                                                             │ │
│  │  ┌─────────────────────────────────────────────────────┐   │ │
│  │  │  COORDINATOR AGENT  (create_agent)                  │   │ │
│  │  │  context_schema=AgentContext                        │   │ │
│  │  │  checkpointer=AsyncPostgresSaver (Neon)             │   │ │
│  │  └────────┬──────────────────────┬───────────────────┬─┘   │ │
│  │           │                      │                   │     │ │
│  │  ┌────────▼───────┐  ┌───────────▼──────┐  ┌────────▼───┐ │ │
│  │  │ MAIL READER    │  │  MAILING AGENT   │  │ WEB SEARCH │ │ │
│  │  │ AGENT          │  │  + interrupt()   │  │ AGENT      │ │ │
│  │  │ (sub-graph)    │  │  for HITL        │  │ (sub-graph)│ │ │
│  │  └────────┬───────┘  └──────────────────┘  └────────────┘ │ │
│  └───────────┼───────────────────────────────────────────────┘  │
│              │                                                   │
│  ┌───────────▼───────────────────────────────────────────────┐  │
│  │                  SHARED SERVICES                          │  │
│  │  GmailService | AsyncPostgresSaver | NotificationService  │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                           │
           ┌───────────────▼──────────────────┐
           │         EXTERNAL SERVICES        │
           │  Gmail API | OpenRouter | Tavily  │
           └──────────────────────────────────┘
```

### 2.2 Multi-Agent Architecture

```
User message
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  COORDINATOR AGENT  (create_agent)                           │
│                                                              │
│  Tools:                                                      │
│    call_mail_reader_agent(task)  ──────────►  MAIL READER    │
│    call_web_search_agent(topic)  ──────────►  WEB SEARCH     │
│    call_mailing_agent(action, params) ─────►  MAILING AGENT  │
│    ask_for_clarification(question)                           │
│                                                              │
│  Context: AgentContext (injected per request)                │
│  Checkpointer: AsyncPostgresSaver (thread_id = conv_id)      │
└──────────────────────────────────────────────────────────────┘
```

Each sub-agent is itself a `create_agent(...)` compiled graph, exposed to the coordinator as an async callable tool. The coordinator passes `runtime.context` down when invoking sub-agents, so all agents share the same `AgentContext` (user credentials, DB session, notification service).

### 2.3 HITL Flow with Native LangGraph `interrupt()`

```
Mailing Agent tool: send_email_with_approval()
    │
    ▼
Creates EmailDraft in DB  (status = "pending_approval")
    │
    ▼
Calls interrupt({type, draft_id, to, subject, body})
    │  ← Graph checkpoints here; execution pauses
    ▼
FastAPI SSE stream receives "__interrupt__" event
    │
    ▼
Broadcasts SSE to frontend: { type: "approval_required", draft_id, draft }
    │
    ▼
Frontend shows Approval Modal
    │
    ▼
User clicks Approve / Edit & Approve / Reject
    │
    ▼
POST /api/approve/{draft_id}  { action, edited_body? }
    │
    ▼
Backend: draft updated in DB → coordinator_agent.ainvoke(
           Command(resume={"approved": True/False, "edited_body": ...}),
           config={"configurable": {"thread_id": conversation_id}}
         )
    │
    ▼
Graph resumes after interrupt() call
    │
    ├─ approved → GmailService.send_email() → notification
    └─ rejected  → notification
```

---

## 3. Technology Stack & Versions

| Layer | Technology | Version / Notes |
|---|---|---|
| Frontend Framework | Next.js | 14.x (App Router) |
| Frontend UI | Tailwind CSS + shadcn/ui | latest |
| Frontend State | Zustand | 4.x |
| Backend Framework | FastAPI | 0.115.x |
| Backend Server | Uvicorn | 0.30.x |
| ORM | SQLAlchemy (async) | 2.x |
| DB Migrations | Alembic | 1.13.x |
| Database | Neon (PostgreSQL 16) | — |
| DB Driver | asyncpg | 0.29.x |
| Auth | Google OAuth 2.0 (Authlib) | 1.3.x |
| JWT | python-jose[cryptography] | 3.3.x |
| Gmail Integration | google-api-python-client + google-auth | 2.x |
| **LLM Integration** | **langchain-openrouter** | **latest** |
| **LLM Class** | **ChatOpenRouter** | **NOT ChatOpenAI** |
| **Agent Factory** | **langchain.agents.create_agent** | **NOT create_react_agent** |
| LangGraph | langgraph | 0.3.x |
| LangGraph Checkpointer | langgraph-checkpoint-postgres | latest |
| Web Search | **tavily-python (TavilyClient direct)** | latest |
| Real-time | Server-Sent Events (SSE) | — |
| HTTP Client | httpx | 0.27.x |
| Validation | Pydantic v2 | 2.x |
| Secrets | python-dotenv | 1.x |

**LLM**: `qwen/qwen3.5-35b-a3b` via OpenRouter
- 262,144 token context; hybrid sparse MoE + linear attention
- $0.25/M input, $2/M output
- Tool calling: ✅  Streaming: ✅  Structured output: ✅

---

## 4. Project Structure

```
email-agent/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app entry point
│   │   ├── config.py                  # pydantic-settings Settings class
│   │   ├── database.py                # Async SQLAlchemy engine + session factory
│   │   │
│   │   ├── models/                    # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── email_draft.py
│   │   │   └── notification.py
│   │   │
│   │   ├── schemas/                   # Pydantic v2 request/response schemas
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── chat.py
│   │   │   ├── email.py
│   │   │   └── approval.py
│   │   │
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py               # /auth/login, /callback, /logout, /me
│   │   │   ├── chat.py               # /chat/message (SSE), /chat/conversations
│   │   │   ├── emails.py             # /emails/recent, /search, /{id}
│   │   │   ├── approve.py            # /approve/{draft_id}, /approve/pending
│   │   │   └── notifications.py      # /notifications/stream, /notifications
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── gmail_service.py      # Gmail API wrapper (async)
│   │   │   ├── auth_service.py       # Token refresh, OAuth helpers
│   │   │   └── notification_service.py # Per-user asyncio.Queue SSE broadcaster
│   │   │
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── context.py            # AgentContext dataclass definition
│   │   │   ├── llm.py                # ChatOpenRouter singleton
│   │   │   ├── coordinator.py        # Coordinator agent (create_agent)
│   │   │   ├── mail_reader_agent.py  # Mail reader sub-agent (create_agent)
│   │   │   ├── mailing_agent.py      # Mailing sub-agent with interrupt()
│   │   │   ├── web_search_agent.py   # Web search sub-agent (create_agent)
│   │   │   └── tools/
│   │   │       ├── __init__.py
│   │   │       ├── gmail_tools.py    # @tool functions using ToolRuntime
│   │   │       ├── search_tools.py   # TavilyClient-based @tool
│   │   │       └── draft_tools.py    # Draft creation + interrupt trigger
│   │   │
│   │   ├── checkpointer.py           # AsyncPostgresSaver setup
│   │   │
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   └── auth_middleware.py    # JWT validation dependency
│   │   │
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── token_encryption.py   # Fernet encryption for OAuth tokens
│   │       └── email_parser.py       # Gmail API response parsing helpers
│   │
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 001_initial_schema.py
│   │
│   ├── alembic.ini
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                  # Redirect to /login or /dashboard
│   │   ├── login/page.tsx
│   │   ├── auth/callback/page.tsx
│   │   └── dashboard/
│   │       ├── layout.tsx
│   │       └── page.tsx
│   │
│   ├── components/
│   │   ├── ui/                       # shadcn/ui components
│   │   ├── chat/
│   │   │   ├── ChatWindow.tsx
│   │   │   ├── MessageBubble.tsx
│   │   │   ├── InputBar.tsx
│   │   │   └── EmailCard.tsx
│   │   ├── approval/
│   │   │   └── ApprovalModal.tsx
│   │   └── notifications/
│   │       └── NotificationToast.tsx
│   │
│   ├── hooks/
│   │   ├── useSSE.ts
│   │   ├── useChat.ts
│   │   └── useAuth.ts
│   │
│   ├── stores/
│   │   ├── authStore.ts
│   │   ├── chatStore.ts
│   │   └── approvalStore.ts
│   │
│   ├── lib/
│   │   ├── api.ts
│   │   └── utils.ts
│   │
│   ├── types/index.ts
│   ├── middleware.ts                  # Route protection
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   └── package.json
│
└── README.md
```

---

## 5. Database Schema (Neon/PostgreSQL)

> **Note on LangGraph checkpointer tables:** `AsyncPostgresSaver.setup()` auto-creates its own checkpoint tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`). Do NOT create these manually — just call `await checkpointer.setup()` on app startup.

### 5.1 Application Tables (Alembic-managed)

```sql
-- users
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_id           VARCHAR(255) UNIQUE NOT NULL,
    email               VARCHAR(255) UNIQUE NOT NULL,
    name                VARCHAR(255),
    picture_url         TEXT,
    access_token        TEXT NOT NULL,         -- Fernet-encrypted
    refresh_token       TEXT,                  -- Fernet-encrypted
    token_expiry        TIMESTAMPTZ,
    gmail_scope_granted BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- conversations (maps to LangGraph thread_id)
CREATE TABLE conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(255),                  -- auto-generated from first message
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- email_drafts
CREATE TABLE email_drafts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    draft_type      VARCHAR(20) NOT NULL CHECK (draft_type IN ('reply', 'fresh')),
    to_address      VARCHAR(255) NOT NULL,
    subject         VARCHAR(500) NOT NULL,
    body            TEXT NOT NULL,
    in_reply_to     VARCHAR(500),     -- Gmail message ID for threading
    thread_id       VARCHAR(500),     -- Gmail thread ID for threading
    status          VARCHAR(30) NOT NULL DEFAULT 'pending_approval'
                        CHECK (status IN (
                            'pending_approval', 'approved',
                            'rejected', 'sent', 'send_failed'
                        )),
    edited_to       VARCHAR(255),     -- populated if user edited before approving
    edited_subject  VARCHAR(500),
    edited_body     TEXT,
    gmail_sent_id   VARCHAR(500),     -- Gmail message ID after successful send
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- notifications
CREATE TABLE notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type        VARCHAR(50) NOT NULL,
    title       VARCHAR(255) NOT NULL,
    body        TEXT,
    metadata    JSONB DEFAULT '{}',
    is_read     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_email_drafts_user_id ON email_drafts(user_id);
CREATE INDEX idx_email_drafts_status ON email_drafts(status);
CREATE INDEX idx_notifications_user_unread ON notifications(user_id) WHERE is_read = FALSE;
```

---

## 6. Google OAuth & Gmail API Setup

### 6.1 Google Cloud Setup

1. Create project in Google Cloud Console
2. Enable **Gmail API**
3. Configure **OAuth Consent Screen** → External → add scopes below
4. Create **OAuth 2.0 Client ID** (Web application)
5. Authorized redirect URIs:
   - `http://localhost:8000/api/auth/callback` (dev)
   - `https://yourdomain.com/api/auth/callback` (prod)

### 6.2 Required Scopes

```
openid
email
profile
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/gmail.send
```

### 6.3 OAuth Flow

```
Browser                   FastAPI                        Google
  │                          │                              │
  │  GET /api/auth/login      │                              │
  ├─────────────────────────►│                              │
  │                          │  Build auth URL + state      │
  │◄─────────────────────────┤  (store state in session)    │
  │  302 → accounts.google   │                              │
  ├─────────────────────────────────────────────────────►  │
  │                                                         │
  │  User grants consent → Google callback                  │
  │◄───────────────────────────────────────────────────────┤
  │  GET /api/auth/callback?code=...&state=...              │
  ├─────────────────────────►│                              │
  │                          │  Verify state               │
  │                          │  Exchange code for tokens ─►│
  │                          │◄────────────────────────────┤
  │                          │  Encrypt + store tokens      │
  │                          │  Issue JWT cookie            │
  │◄─────────────────────────┤                              │
  │  Set-Cookie: jwt=...      │                              │
  │  302 → /dashboard         │                              │
```

### 6.4 Token Management

- All OAuth tokens **Fernet-encrypted** before storing in Neon
- `auth_service.get_valid_access_token(user_id, db)`:
  1. Query `users` table for token + expiry
  2. If `token_expiry < now() + 5min` → call Google token refresh endpoint
  3. Decrypt refresh token → get new access token → encrypt + store
  4. Return decrypted access token ready for Gmail API

---

## 7. Backend — FastAPI

### 7.1 `main.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.database import engine
from app.models import Base
from app.checkpointer import get_checkpointer
from app.routers import auth, chat, emails, approve, notifications

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables (Alembic handles migrations; this is a safety net)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Initialize LangGraph checkpointer (creates checkpoint tables in Neon)
    checkpointer = await get_checkpointer()
    await checkpointer.setup()
    app.state.checkpointer = checkpointer
    yield
    await engine.dispose()

app = FastAPI(title="Email Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,  # required for httpOnly cookie auth
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(emails.router, prefix="/api/emails", tags=["emails"])
app.include_router(approve.router, prefix="/api/approve", tags=["approve"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
```

### 7.2 Auth Middleware (JWT dependency)

```python
# app/middleware/auth_middleware.py
from fastapi import Depends, HTTPException, Cookie
from jose import jwt, JWTError
from app.config import settings
from app.database import get_db
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession

async def get_current_user(
    access_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db)
) -> User:
    if not access_token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(access_token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401, "User not found")
    return user
```

### 7.3 Chat Router with SSE Streaming

```python
# app/routers/chat.py
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from app.agents.coordinator import get_coordinator_agent
from app.agents.context import AgentContext
from app.services.gmail_service import GmailService
from app.services.auth_service import get_valid_access_token
from app.services.notification_service import notification_service
import json, asyncio

router = APIRouter()

@router.post("/message")
async def chat_message(
    body: ChatMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    # Build AgentContext — this is the dependency injection point
    access_token = await get_valid_access_token(current_user.id, db)
    gmail_svc = GmailService(access_token)
    
    context = AgentContext(
        user_id=str(current_user.id),
        gmail_service=gmail_svc,
        db_session=db,
        notification_service=notification_service,
    )
    
    agent = get_coordinator_agent(request.app.state.checkpointer)
    
    config = {"configurable": {"thread_id": str(body.conversation_id)}}

    async def event_stream():
        try:
            async for event in agent.astream(
                {"messages": [{"role": "user", "content": body.message}]},
                config=config,
                context=context,
                stream_mode=["updates", "messages"],
            ):
                # Stream token-level updates to the client
                if "messages" in event:
                    for msg in event["messages"]:
                        if hasattr(msg, "content") and msg.content:
                            yield f"data: {json.dumps({'type': 'token', 'content': msg.content})}\n\n"

                # Detect LangGraph interrupt (HITL trigger)
                if "__interrupt__" in event:
                    interrupt_payload = event["__interrupt__"][0].value
                    # Broadcast to the notification SSE stream (separate channel)
                    await notification_service.broadcast(
                        str(current_user.id),
                        {"type": "approval_required", **interrupt_payload}
                    )
                    yield f"data: {json.dumps({'type': 'approval_pending', 'draft_id': interrupt_payload['draft_id']})}\n\n"
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

### 7.4 Approve Router

```python
# app/routers/approve.py
@router.post("/{draft_id}")
async def process_approval(
    draft_id: str,
    body: ApprovalRequest,   # { action, edited_to?, edited_subject?, edited_body? }
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    # 1. Load and validate draft
    draft = await db.get(EmailDraft, draft_id)
    if not draft or draft.user_id != current_user.id:
        raise HTTPException(404)
    if draft.status != "pending_approval":
        raise HTTPException(409, "Draft is not awaiting approval")

    # 2. Apply edits if any
    if body.action == "edit_and_approve":
        draft.edited_to = body.edited_to or draft.to_address
        draft.edited_subject = body.edited_subject or draft.subject
        draft.edited_body = body.edited_body
    
    approved = body.action in ("approve", "edit_and_approve")
    draft.status = "approved" if approved else "rejected"
    await db.commit()

    # 3. Resume the LangGraph graph for this conversation thread
    agent = get_coordinator_agent(request.app.state.checkpointer)
    config = {"configurable": {"thread_id": str(draft.conversation_id)}}
    
    await agent.ainvoke(
        Command(resume={
            "approved": approved,
            "edited_to": draft.edited_to,
            "edited_subject": draft.edited_subject,
            "edited_body": draft.edited_body,
        }),
        config=config,
        context=AgentContext(
            user_id=str(current_user.id),
            gmail_service=GmailService(await get_valid_access_token(current_user.id, db)),
            db_session=db,
            notification_service=notification_service,
        ),
    )

    return {"success": True}
```

### 7.5 Key Service: `GmailService`

```python
# app/services/gmail_service.py
import base64, email
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

class GmailService:
    def __init__(self, access_token: str):
        creds = Credentials(token=access_token)
        self.service = build("gmail", "v1", credentials=creds)

    async def list_messages(self, query: str = "", max_results: int = 10) -> list[dict]:
        """Returns parsed email summaries matching Gmail search query."""
        ...

    async def get_message(self, message_id: str) -> dict:
        """Returns full email with decoded body."""
        ...

    async def get_thread(self, thread_id: str) -> dict:
        """Returns all messages in a thread."""
        ...

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Sends email via Gmail API. Returns Gmail message ID."""
        # Construct MIME message
        # Set In-Reply-To and References headers for threading
        # Encode as base64url
        # Call users().messages().send(threadId=thread_id)
        ...

    def _build_query(self, sender: str = None, topic: str = None, days_back: int = None) -> str:
        """Translates intent parameters to Gmail search query syntax."""
        parts = []
        if sender:
            parts.append(f"from:{sender}")
        if topic:
            parts.append(f"subject:({topic}) OR ({topic})")
        if days_back:
            from datetime import date, timedelta
            since = (date.today() - timedelta(days=days_back)).strftime("%Y/%m/%d")
            parts.append(f"after:{since}")
        return " ".join(parts)
```

---

## 8. AI Agent System — LangChain

### 8.1 `AgentContext` — Dependency Injection via `context_schema`

```python
# app/agents/context.py
from dataclasses import dataclass
from app.services.gmail_service import GmailService
from app.services.notification_service import NotificationService
from sqlalchemy.ext.asyncio import AsyncSession

@dataclass
class AgentContext:
    """
    Runtime context injected into every agent invocation.
    Accessible inside tools via ToolRuntime[AgentContext].
    Accessible inside middleware via Runtime[AgentContext].
    Never stored globally — created fresh per request.
    """
    user_id: str
    gmail_service: GmailService
    db_session: AsyncSession
    notification_service: NotificationService
```

### 8.2 `ChatOpenRouter` LLM Setup

```python
# app/agents/llm.py
from langchain_openrouter import ChatOpenRouter
from app.config import settings

def get_llm() -> ChatOpenRouter:
    return ChatOpenRouter(
        model="qwen/qwen3.5-35b-a3b",
        temperature=0.2,
        max_tokens=4096,
        app_url=settings.APP_URL,
        app_title="Email Agent",
    )
```

### 8.3 `AsyncPostgresSaver` Checkpointer

```python
# app/checkpointer.py
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.config import settings

_checkpointer: AsyncPostgresSaver | None = None

async def get_checkpointer() -> AsyncPostgresSaver:
    global _checkpointer
    if _checkpointer is None:
        # Use psycopg connection string format (NOT asyncpg format)
        # AsyncPostgresSaver uses psycopg3 (psycopg) under the hood
        conn_string = settings.DATABASE_URL.replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        _checkpointer = AsyncPostgresSaver.from_conn_string(conn_string)
    return _checkpointer
```

> **Important:** `langgraph-checkpoint-postgres` uses `psycopg` (v3), not `asyncpg`. Install both `asyncpg` (for SQLAlchemy) and `psycopg[binary,pool]` (for LangGraph checkpointer). They use different connection strings — see env var section.

### 8.4 Gmail Tools (using `ToolRuntime`)

```python
# app/agents/tools/gmail_tools.py
from langchain.tools import tool, ToolRuntime
from app.agents.context import AgentContext

@tool
async def get_recent_emails(count: int, runtime: ToolRuntime[AgentContext]) -> str:
    """
    Fetches the most recent emails from the user's Gmail inbox.
    Args:
        count: Number of emails to fetch (1-20)
    """
    gmail = runtime.context.gmail_service
    emails = await gmail.list_messages(max_results=count)
    return _format_email_list(emails)

@tool
async def search_emails_by_sender(sender: str, runtime: ToolRuntime[AgentContext]) -> str:
    """
    Searches the user's Gmail for emails from a specific sender.
    Args:
        sender: Email address or name/organization of the sender
    """
    gmail = runtime.context.gmail_service
    query = gmail._build_query(sender=sender)
    emails = await gmail.list_messages(query=query, max_results=10)
    return _format_email_list(emails)

@tool
async def search_emails_by_topic(topic: str, runtime: ToolRuntime[AgentContext]) -> str:
    """
    Searches the user's Gmail for emails related to a topic or keyword.
    Args:
        topic: Topic, keyword, or subject matter to search for
    """
    gmail = runtime.context.gmail_service
    query = gmail._build_query(topic=topic)
    emails = await gmail.list_messages(query=query, max_results=10)
    return _format_email_list(emails)

@tool
async def get_email_thread(thread_id: str, runtime: ToolRuntime[AgentContext]) -> str:
    """
    Fetches the complete email thread (all replies) for a given thread ID.
    Args:
        thread_id: Gmail thread ID
    """
    gmail = runtime.context.gmail_service
    thread = await gmail.get_thread(thread_id)
    return _format_thread(thread)

@tool
async def get_full_email(message_id: str, runtime: ToolRuntime[AgentContext]) -> str:
    """
    Fetches the complete content of a single email.
    Args:
        message_id: Gmail message ID
    """
    gmail = runtime.context.gmail_service
    message = await gmail.get_message(message_id)
    return _format_full_email(message)

# Helper formatters
def _format_email_list(emails: list[dict]) -> str: ...
def _format_thread(thread: dict) -> str: ...
def _format_full_email(email: dict) -> str: ...
```

### 8.5 Web Search Tool (Direct TavilyClient)

```python
# app/agents/tools/search_tools.py
from langchain.tools import tool
from tavily import TavilyClient
from typing import Dict, Any
from app.config import settings

tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)

@tool
def web_search(query: str) -> Dict[str, Any]:
    """
    Search the web for information relevant to composing an email.
    Returns recent, relevant results including titles, URLs, and content snippets.
    Args:
        query: Search query string
    """
    try:
        return tavily_client.search(query)
    except Exception as e:
        return {"error": str(e)}
```

### 8.6 Draft Tools with LangGraph `interrupt()`

```python
# app/agents/tools/draft_tools.py
from langchain.tools import tool, ToolRuntime
from langgraph.types import interrupt
from app.agents.context import AgentContext
from app.models.email_draft import EmailDraft
import uuid

@tool
async def compose_and_request_approval(
    to: str,
    subject: str,
    body: str,
    draft_type: str,
    in_reply_to: str | None,
    thread_id: str | None,
    conversation_id: str,
    runtime: ToolRuntime[AgentContext],
) -> str:
    """
    Creates an email draft and pauses execution to request human approval.
    DO NOT call this without first confirming the recipient address.
    Args:
        to: Recipient email address
        subject: Email subject line
        body: Full email body text
        draft_type: "reply" or "fresh"
        in_reply_to: Gmail message ID being replied to (for replies only)
        thread_id: Gmail thread ID (for replies only)
        conversation_id: Current conversation UUID (used to resume after approval)
    """
    db = runtime.context.db_session
    user_id = runtime.context.user_id

    # 1. Persist draft to DB
    draft = EmailDraft(
        id=uuid.uuid4(),
        user_id=user_id,
        conversation_id=conversation_id,
        draft_type=draft_type,
        to_address=to,
        subject=subject,
        body=body,
        in_reply_to=in_reply_to,
        thread_id=thread_id,
        status="pending_approval",
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    # 2. Interrupt graph execution — waits here for human action
    # The interrupt value is sent to the frontend via SSE in the chat router
    approval = interrupt({
        "type": "approval_required",
        "draft_id": str(draft.id),
        "draft": {
            "to": to,
            "subject": subject,
            "body": body,
            "draft_type": draft_type,
        }
    })

    # 3. Execution resumes here after POST /api/approve/{draft_id}
    #    approval = Command(resume={...}).resume value
    if not approval.get("approved"):
        draft.status = "rejected"
        await db.commit()
        return "The email was not sent — the user rejected it."

    # 4. Apply any edits from approval modal
    final_to      = approval.get("edited_to") or to
    final_subject = approval.get("edited_subject") or subject
    final_body    = approval.get("edited_body") or body

    # 5. Send via Gmail
    gmail = runtime.context.gmail_service
    try:
        gmail_id = await gmail.send_email(
            to=final_to,
            subject=final_subject,
            body=final_body,
            in_reply_to=in_reply_to,
            thread_id=thread_id,
        )
        draft.status = "sent"
        draft.gmail_sent_id = gmail_id
        await db.commit()

        # 6. Persist + broadcast notification
        notification_svc = runtime.context.notification_service
        await notification_svc.broadcast(user_id, {
            "type": "email_sent",
            "title": "Email Sent",
            "body": f"Your email to {final_to} has been sent.",
            "draft_id": str(draft.id),
        })
        return f"Email successfully sent to {final_to}. Gmail message ID: {gmail_id}"

    except Exception as e:
        draft.status = "send_failed"
        await db.commit()
        return f"Failed to send email: {str(e)}"
```

### 8.7 Mail Reader Agent

```python
# app/agents/mail_reader_agent.py
from langchain.agents import create_agent
from app.agents.llm import get_llm
from app.agents.context import AgentContext
from app.agents.tools.gmail_tools import (
    get_recent_emails, search_emails_by_sender,
    search_emails_by_topic, get_email_thread, get_full_email
)

MAIL_READER_SYSTEM_PROMPT = """
You are a specialized email reading assistant with read-only access to the user's Gmail.
Your responsibilities:
- Fetch and display recent emails when asked
- Search emails by sender name or email address
- Search emails by topic, keyword, or subject
- Summarize individual emails or complete threads
- Extract key information: sender, date, subject, main points, action items

Always present emails clearly. For summaries, highlight:
  1. Who sent it and when
  2. The core message or request
  3. Any deadlines or action items

Never attempt to send or modify any email.
"""

def get_mail_reader_agent(checkpointer=None):
    return create_agent(
        model=get_llm(),
        tools=[
            get_recent_emails,
            search_emails_by_sender,
            search_emails_by_topic,
            get_email_thread,
            get_full_email,
        ],
        system_prompt=MAIL_READER_SYSTEM_PROMPT,
        context_schema=AgentContext,
        checkpointer=checkpointer,
        name="mail_reader_agent",
    )
```

### 8.8 Web Search Agent

```python
# app/agents/web_search_agent.py
from langchain.agents import create_agent
from app.agents.llm import get_llm
from app.agents.context import AgentContext
from app.agents.tools.search_tools import web_search

WEB_SEARCH_SYSTEM_PROMPT = """
You are a research agent. Your job is to gather relevant, accurate, up-to-date
information from the web to help compose a well-informed professional email.

When given a topic:
1. Search for recent developments, key facts, and relevant data
2. Identify 3-5 strong talking points
3. Note any relevant statistics or credible sources

Return your research in this structure:
{
  "topic_summary": "brief overview",
  "key_points": ["point 1", "point 2", ...],
  "relevant_facts": ["fact with source", ...],
  "suggested_tone": "professional / informational / persuasive"
}

Do not compose the email — only provide the research.
"""

def get_web_search_agent(checkpointer=None):
    return create_agent(
        model=get_llm(),
        tools=[web_search],
        system_prompt=WEB_SEARCH_SYSTEM_PROMPT,
        context_schema=AgentContext,
        checkpointer=checkpointer,
        name="web_search_agent",
    )
```

### 8.9 Mailing Agent

```python
# app/agents/mailing_agent.py
from langchain.agents import create_agent
from app.agents.llm import get_llm
from app.agents.context import AgentContext
from app.agents.tools.gmail_tools import get_full_email, get_email_thread
from app.agents.tools.draft_tools import compose_and_request_approval

MAILING_AGENT_SYSTEM_PROMPT = """
You are a specialized email composition agent. You draft and send emails
on behalf of the user.

CRITICAL RULES:
1. NEVER send an email without calling compose_and_request_approval — this
   is mandatory for every email, no exceptions.
2. Always confirm the recipient email address before drafting. If not provided,
   ask the coordinator to request it from the user.
3. For replies: first fetch the original email to understand context and
   maintain proper threading.
4. Compose emails in a professional, clear, concise tone unless instructed otherwise.
5. After calling compose_and_request_approval, report the outcome (sent/rejected)
   back to the coordinator.

For fresh emails using research:
- Use the provided research_data to craft the email body
- Make the email natural and professional, not a bullet-point summary of research
- Suggest a clear, specific subject line
"""

def get_mailing_agent(checkpointer=None):
    return create_agent(
        model=get_llm(),
        tools=[
            get_full_email,
            get_email_thread,
            compose_and_request_approval,
        ],
        system_prompt=MAILING_AGENT_SYSTEM_PROMPT,
        context_schema=AgentContext,
        checkpointer=checkpointer,
        name="mailing_agent",
    )
```

### 8.10 Coordinator Agent

```python
# app/agents/coordinator.py
from langchain.agents import create_agent
from langchain.tools import tool, ToolRuntime
from langchain_core.messages import HumanMessage
from app.agents.llm import get_llm
from app.agents.context import AgentContext
from app.agents.mail_reader_agent import get_mail_reader_agent
from app.agents.web_search_agent import get_web_search_agent
from app.agents.mailing_agent import get_mailing_agent

COORDINATOR_SYSTEM_PROMPT = """
You are the central coordinator of an email assistant system. You understand
the user's request and delegate to specialized sub-agents.

SUB-AGENTS available to you:
- call_mail_reader: for reading, searching, and summarizing emails
- call_web_search: for researching topics before writing a fresh email
- call_mailing_agent: for composing, replying to, and sending emails

INTENT ROUTING:
- "read/show/get my emails" → call_mail_reader
- "emails from [sender]" → call_mail_reader
- "emails about [topic]" → call_mail_reader
- "summarize [email/thread]" → call_mail_reader
- "reply to [email]" → call_mailing_agent (it will fetch the original email)
- "write/compose/send email about [topic]" → FIRST call_web_search for research,
   THEN pass research results to call_mailing_agent
- "write email to [person]" (no topic needing research) → call_mailing_agent directly

IMPORTANT:
- For fresh emails, always ask for the recipient's email address if not provided
  before invoking the mailing agent.
- For replies, pass the Gmail message ID to the mailing agent.
- Always report results back to the user clearly and concisely.
"""

# Sub-agent tool wrappers
# Each wraps a sub-agent graph as a callable tool, passing context through

def make_coordinator_tools(checkpointer):
    mail_reader = get_mail_reader_agent(checkpointer)
    web_search_agent = get_web_search_agent(checkpointer)
    mailing_agent = get_mailing_agent(checkpointer)

    @tool
    async def call_mail_reader(task: str, runtime: ToolRuntime[AgentContext]) -> str:
        """
        Delegates email reading, searching, or summarization tasks to the
        mail reader sub-agent.
        Args:
            task: Detailed description of the reading/search/summarization task
        """
        result = await mail_reader.ainvoke(
            {"messages": [HumanMessage(content=task)]},
            context=runtime.context,
            config={"configurable": {"thread_id": f"mail_reader_{runtime.context.user_id}"}},
        )
        return result["messages"][-1].content

    @tool
    async def call_web_search(topic: str, runtime: ToolRuntime[AgentContext]) -> str:
        """
        Delegates web research for a given topic to the web search sub-agent.
        Use this before composing a fresh email on a topic that requires current information.
        Args:
            topic: The topic to research
        """
        result = await web_search_agent.ainvoke(
            {"messages": [HumanMessage(content=f"Research this topic for an email: {topic}")]},
            context=runtime.context,
            config={"configurable": {"thread_id": f"search_{runtime.context.user_id}"}},
        )
        return result["messages"][-1].content

    @tool
    async def call_mailing_agent(task: str, runtime: ToolRuntime[AgentContext]) -> str:
        """
        Delegates email composition and sending to the mailing sub-agent.
        For fresh emails, include research_data in the task description.
        For replies, include the original message_id.
        Args:
            task: Detailed task description including recipient, topic,
                  research data (if any), and any specific instructions
        """
        result = await mailing_agent.ainvoke(
            {"messages": [HumanMessage(content=task)]},
            context=runtime.context,
            config={"configurable": {"thread_id": f"mailing_{runtime.context.user_id}"}},
        )
        return result["messages"][-1].content

    return [call_mail_reader, call_web_search, call_mailing_agent]


_coordinator_agent = None

def get_coordinator_agent(checkpointer):
    global _coordinator_agent
    if _coordinator_agent is None:
        tools = make_coordinator_tools(checkpointer)
        _coordinator_agent = create_agent(
            model=get_llm(),
            tools=tools,
            system_prompt=COORDINATOR_SYSTEM_PROMPT,
            context_schema=AgentContext,
            checkpointer=checkpointer,
            name="coordinator",
        )
    return _coordinator_agent
```

---

## 9. Frontend — Next.js

### 9.1 Pages

**`/` (root):** Server component. Checks for JWT cookie → redirect `/dashboard` or `/login`.

**`/login`:** Clean page with Google button. Clicking calls `GET /api/auth/login` which returns a redirect to Google. No client-side OAuth handling — all done server-side.

**`/auth/callback`:** Shows loading spinner. The actual callback is handled by FastAPI at `/api/auth/callback` which sets cookie and redirects to `/dashboard`.

**`/dashboard`:** Protected by `middleware.ts`. Contains sidebar (conversations) + main chat area. On mount, initializes SSE connection for real-time events.

### 9.2 Chat Interface

```
┌────────────────────────────────────────────────────────┐
│  📧 Email Agent                          [New Chat]     │
├─────────────────┬──────────────────────────────────────┤
│                 │                                      │
│  PAST CHATS     │  ┌──────────────────────────────┐   │
│                 │  │ 🤖  Hello! I can help you:   │   │
│  > Chat 1       │  │  • Read your latest emails   │   │
│    Chat 2       │  │  • Search by sender/topic    │   │
│                 │  │  • Summarize threads         │   │
│                 │  │  • Reply to emails           │   │
│                 │  │  • Write new emails          │   │
│                 │  └──────────────────────────────┘   │
│                 │                                      │
│                 │  ┌──────────────────────────────┐   │
│                 │  │ 👤  Show emails from BRAC Bank│   │
│                 │  └──────────────────────────────┘   │
│                 │                                      │
│                 │  ┌──────────────────────────────┐   │
│                 │  │ 🤖  [thinking...]             │   │
│                 │  │  Searching Gmail...           │   │
│                 │  │                               │   │
│                 │  │  ┌────────────────────────┐  │   │
│                 │  │  │ 📧 Statement - March    │  │   │
│                 │  │  │ From: alerts@bracbank   │  │   │
│                 │  │  │ 2 days ago              │  │   │
│                 │  │  │ [View Full] [Reply]     │  │   │
│                 │  │  └────────────────────────┘  │   │
│                 │  └──────────────────────────────┘   │
│                 │                                      │
│                 │  ┌──────────────────────────────┐   │
│                 │  │ Ask me anything...    [Send] │   │
│                 │  └──────────────────────────────┘   │
└─────────────────┴──────────────────────────────────────┘
```

### 9.3 Approval Modal

```
┌────────────────────────────────────────────────────┐
│  ✉️  Review Email Before Sending                    │
├────────────────────────────────────────────────────┤
│  To:       [recipient@example.com               ]  │
│  Subject:  [RE: Your Application               ]   │
├────────────────────────────────────────────────────┤
│  Message:                                          │
│  ┌──────────────────────────────────────────────┐  │
│  │ Dear Hiring Team,                            │  │
│  │                                              │  │
│  │ Thank you for reaching out. I am very        │  │
│  │ interested in this opportunity...            │  │
│  └──────────────────────────────────────────────┘  │
│                                    [Edit ✏️]        │
├────────────────────────────────────────────────────┤
│               [Reject ✗]   [Approve & Send ✓]      │
└────────────────────────────────────────────────────┘
```

**Triggered by:** SSE event `{ type: "approval_required", draft_id, draft: { to, subject, body } }`

**On Approve:** `POST /api/approve/{draft_id}` → `{ action: "approve" }` (or `"edit_and_approve"` with edited fields)

**On Reject:** `POST /api/approve/{draft_id}` → `{ action: "reject" }`

### 9.4 Key Hooks

**`useSSE.ts`** — establishes `EventSource` to `/api/notifications/stream`:
```typescript
// Event type handlers:
// "approval_required" → setApprovalModal(draft data)
// "email_sent"        → showToast("success", "Email sent!")
// "email_rejected"    → showToast("info", "Email cancelled")
// "error"             → showToast("error", message)
// "ping"              → no-op (heartbeat)
// Auto-reconnects with exponential backoff on disconnect
```

**`useChat.ts`** — manages chat state and SSE streaming from `/api/chat/message`:
```typescript
// Reads token-by-token stream from chat SSE
// Assembles tokens into assistant message in real-time
// Handles "approval_pending" event (updates UI to show waiting state)
// Handles "done" event (marks message as complete)
```

### 9.5 Route Protection

```typescript
// middleware.ts
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const token = request.cookies.get('access_token')?.value
  const isProtected = request.nextUrl.pathname.startsWith('/dashboard')
  
  if (isProtected && !token) {
    return NextResponse.redirect(new URL('/login', request.url))
  }
  if (!isProtected && token && request.nextUrl.pathname === '/login') {
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }
}

export const config = {
  matcher: ['/dashboard/:path*', '/login'],
}
```

### 9.6 TypeScript Types

```typescript
// types/index.ts
export type MessageRole = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  metadata?: {
    emails?: EmailSummary[]
    draft_id?: string
    is_waiting_approval?: boolean
  }
  created_at: string
}

export interface EmailSummary {
  message_id: string
  thread_id: string
  from_name: string
  from_email: string
  subject: string
  snippet: string
  date: string
}

export interface EmailDraft {
  id: string
  to: string
  subject: string
  body: string
  draft_type: 'reply' | 'fresh'
}

export type ApprovalAction = 'approve' | 'edit_and_approve' | 'reject'

export interface SSEEvent {
  type: 'token' | 'approval_pending' | 'approval_required' | 'email_sent' | 
        'email_rejected' | 'error' | 'done' | 'ping'
  content?: string
  draft_id?: string
  draft?: EmailDraft
  title?: string
  body?: string
}
```

---

## 10. Real-Time Notifications (SSE)

### 10.1 `NotificationService`

```python
# app/services/notification_service.py
import asyncio
import json
from collections import defaultdict

class NotificationService:
    """
    Per-user SSE event broadcaster using asyncio.Queue.
    Multiple connections per user are supported (e.g., multiple browser tabs).
    """
    def __init__(self):
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, user_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[user_id].append(queue)
        return queue

    def unsubscribe(self, user_id: str, queue: asyncio.Queue):
        try:
            self._queues[user_id].remove(queue)
        except ValueError:
            pass

    async def broadcast(self, user_id: str, event: dict):
        for queue in self._queues.get(user_id, []):
            await queue.put(event)

# Module-level singleton
notification_service = NotificationService()
```

### 10.2 SSE Endpoint

```python
# In notifications router
@router.get("/stream")
async def notification_stream(
    current_user: User = Depends(get_current_user),
):
    user_id = str(current_user.id)
    queue = notification_service.subscribe(user_id)

    async def generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive through proxies
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            notification_service.unsubscribe(user_id, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
```

---

## 11. Human-in-the-Loop — Native LangGraph Pattern

This is the complete, authoritative HITL flow using LangGraph's built-in `interrupt()` and `Command(resume=...)` — no custom waiting or polling required.

### 11.1 How It Works

1. **`compose_and_request_approval` tool** (in `draft_tools.py`) calls `interrupt(payload)` mid-execution
2. LangGraph **checkpoints the full graph state** to Neon via `AsyncPostgresSaver`
3. Execution **pauses** — the `astream()` loop in the chat router receives an `__interrupt__` event
4. Chat router broadcasts the interrupt payload to the frontend via the **notification SSE stream**
5. Frontend shows the **Approval Modal** with editable To/Subject/Body fields
6. User clicks Approve or Reject → **`POST /api/approve/{draft_id}`** fires
7. Approve router calls `agent.ainvoke(Command(resume={...}), config={"configurable": {"thread_id": conversation_id}})`
8. LangGraph **restores the checkpointed state** and **resumes execution** right after the `interrupt()` call
9. The tool receives the resume value, sends the email (if approved), and returns
10. Notification SSE broadcasts `email_sent` or `email_rejected` to the frontend
11. Frontend shows a **toast notification** and closes the modal

### 11.2 Why This Is Better Than the v1 Approach

| v1 (custom async wait) | v2 (LangGraph interrupt) |
|---|---|
| Agent blocks thread waiting for approval event | Agent checkpoints state and fully exits |
| Required custom PendingApprovalStore in memory | State lives in Neon DB via checkpointer |
| Could timeout or lose state on server restart | Fully durable — survives restarts |
| Complex asyncio coordination | Native LangGraph feature — minimal code |
| Separate approval store + notification store | Single graph state snapshot |

### 11.3 Thread ID Strategy

```
conversation_id (UUID) → used as LangGraph thread_id for coordinator agent
"mail_reader_{user_id}"  → isolated thread for mail reader sub-agent calls
"search_{user_id}"       → isolated thread for web search sub-agent calls
"mailing_{user_id}"      → isolated thread for mailing sub-agent calls
```

Sub-agents use user-scoped (not conversation-scoped) thread IDs because their state doesn't need to persist across conversations — only the coordinator's state does (for HITL resume).

---

## 12. Environment Variables

### 12.1 Backend `.env`

```env
# App
APP_ENV=development
APP_URL=http://localhost:8000
SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_hex(32))">
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=24

# Neon Database
# For SQLAlchemy (uses asyncpg driver)
DATABASE_URL=postgresql+asyncpg://user:pass@ep-xxx.us-east-1.aws.neon.tech/emailagent?sslmode=require
# For LangGraph checkpointer (uses psycopg3 driver)
DATABASE_URL_PSYCOPG=postgresql://user:pass@ep-xxx.us-east-1.aws.neon.tech/emailagent?sslmode=require

# Google OAuth
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/callback

# Token Encryption (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
TOKEN_ENCRYPTION_KEY=<fernet-key>

# OpenRouter
OPENROUTER_API_KEY=<your OpenRouter API key>

# Tavily
TAVILY_API_KEY=<your Tavily API key>

# CORS
FRONTEND_URL=http://localhost:3000
```

### 12.2 Frontend `.env.local`

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api
NEXT_PUBLIC_APP_NAME=Email Agent
```

---

## 13. API Contract

### Authentication

```
GET  /api/auth/login              → 302 to Google OAuth
GET  /api/auth/callback           → processes OAuth, sets JWT cookie, 302 to /dashboard
POST /api/auth/logout             → clears cookie → { success: true }
GET  /api/auth/me                 → { id, email, name, picture_url, gmail_scope_granted }
```

### Chat

```
POST /api/chat/conversations              → { id, created_at }
GET  /api/chat/conversations              → [{ id, title, created_at, updated_at }]
GET  /api/chat/history/{conv_id}          → pulled from LangGraph checkpoint messages

POST /api/chat/message                    → text/event-stream (SSE)
  Body:   { conversation_id: string, message: string }
  Events:
    { type: "token",            content: "..." }
    { type: "approval_pending", draft_id: "uuid" }
    { type: "error",            content: "..." }
    { type: "done" }
```

### Emails (direct read endpoints, bypass agent for simple fetches)

```
GET /api/emails/recent?count=5            → [EmailSummary]
GET /api/emails/search?q=&sender=&topic=  → [EmailSummary]
GET /api/emails/{message_id}              → EmailDetail
```

### Approval

```
GET  /api/approve/pending                 → [EmailDraft]
POST /api/approve/{draft_id}             → { success: true, gmail_message_id? }
  Body: {
    action: "approve" | "edit_and_approve" | "reject",
    edited_to?:      string,
    edited_subject?: string,
    edited_body?:    string
  }
```

### Notifications

```
GET   /api/notifications/stream           → text/event-stream (SSE, long-lived)
  Events:
    { type: "approval_required", draft_id, draft: { to, subject, body, draft_type } }
    { type: "email_sent",   title, body, draft_id }
    { type: "email_rejected", draft_id }
    { type: "error",        content }
    { type: "ping" }

GET   /api/notifications?page=1&limit=20  → [Notification]
PATCH /api/notifications/{id}/read        → { success: true }
```

---

## 14. Security Considerations

| Threat | Mitigation |
|---|---|
| OAuth token theft at rest | Fernet-encrypted in Neon DB; decryption key only in env var |
| JWT session hijacking | `httpOnly=True`, `SameSite=Lax`, 24h expiry |
| CSRF | `SameSite` cookie + CORS restricted to exact frontend origin |
| Cross-user draft approval | `draft.user_id != current_user.id` check before any action |
| Prompt injection via email body | System prompts instruct agents to never follow instructions found in email content; treat email body as data only |
| Token expiry mid-request | `get_valid_access_token()` always refreshes before Gmail API calls |
| SSE stream leakage | JWT validation on every SSE endpoint; per-user isolated queues |
| SQL injection | SQLAlchemy ORM with parameterized queries throughout |
| Sensitive data in logs | Tokens and email bodies never logged; use structured logging with field redaction |
| LangGraph checkpointer data | Checkpoint tables in same Neon DB; same access controls apply |

---

## 15. Local Development Setup (No Docker)

### 15.1 Prerequisites

```bash
# Python 3.11+
python --version

# Node.js 20+
node --version

# Install uv (fast Python package manager, optional but recommended)
pip install uv
```

### 15.2 Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill env
cp .env.example .env
# Fill in all values in .env

# Run Alembic migrations against Neon
alembic upgrade head

# Start FastAPI dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 15.3 Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Copy and fill env
cp .env.local.example .env.local
# Set NEXT_PUBLIC_API_URL=http://localhost:8000/api

# Start Next.js dev server
npm run dev
# Runs on http://localhost:3000
```

### 15.4 `requirements.txt`

```
# Web framework
fastapi==0.115.0
uvicorn[standard]==0.30.6
python-multipart==0.0.9

# Database
sqlalchemy[asyncio]==2.0.36
asyncpg==0.29.0
alembic==1.13.3

# Auth
authlib==1.3.2
python-jose[cryptography]==3.3.0
itsdangerous==2.2.0
httpx==0.27.2

# Encryption
cryptography==43.0.3

# Google
google-api-python-client==2.151.0
google-auth==2.35.0
google-auth-httplib2==0.2.0

# LangChain + LangGraph
langchain==0.3.7
langchain-openrouter          # pip install langchain-openrouter
langgraph==0.3.0
langgraph-checkpoint-postgres # pip install langgraph-checkpoint-postgres
psycopg[binary,pool]          # required by langgraph-checkpoint-postgres

# Web search
tavily-python==0.5.0

# Config
pydantic-settings==2.6.0
python-dotenv==1.0.1
```

---

## 16. Step-by-Step Implementation Order

### Phase 1: Foundation (Days 1–2)

**Step 1 — Backend scaffold**
- Init Python project, install requirements
- `config.py` with pydantic-settings `Settings` class
- `database.py` — async SQLAlchemy engine with Neon URL
- All SQLAlchemy models (`User`, `Conversation`, `EmailDraft`, `Notification`)
- Alembic init + `001_initial_schema.py` migration → run against Neon

**Step 2 — Frontend scaffold**
- `create-next-app` with TypeScript + Tailwind + App Router
- Install `shadcn/ui` components (Button, Dialog, Input, Textarea, Toast)
- Install `zustand`, `axios`
- Create folder structure, `types/index.ts`, empty store files

---

### Phase 2: Authentication (Days 3–4)

**Step 3 — Backend Auth**
- `token_encryption.py` (Fernet key from env)
- `auth_service.py` — `get_valid_access_token()`, token refresh
- Auth router: `/login`, `/callback`, `/logout`, `/me`
- JWT middleware dependency `get_current_user`
- **Test:** Full OAuth flow in browser, verify tokens stored encrypted in Neon

**Step 4 — Frontend Auth**
- `middleware.ts` — route protection
- `/login` page with Google button
- `/auth/callback` page (shows spinner while FastAPI handles redirect)
- `useAuth` hook + `authStore`
- `lib/api.ts` — axios instance with `withCredentials: true`

---

### Phase 3: Gmail Service (Day 5)

**Step 5 — GmailService**
- `gmail_service.py` — all methods: `list_messages`, `get_message`, `get_thread`, `send_email`, `_build_query`
- `email_parser.py` — parse raw Gmail API message dicts into clean Python dicts
- Direct email endpoints: `/api/emails/recent`, `/search`, `/{id}`
- **Test:** Verify `list_messages`, `get_message`, and `send_email` with a real Gmail account

---

### Phase 4: LangChain Agent System (Days 6–10)

**Step 6 — Foundation**
- `context.py` — `AgentContext` dataclass
- `llm.py` — `ChatOpenRouter` with `qwen/qwen3.5-35b-a3b`
- `checkpointer.py` — `AsyncPostgresSaver` from Neon psycopg connection string
- Wire checkpointer setup into FastAPI lifespan

**Step 7 — Gmail Tools**
- `gmail_tools.py` — all 5 tools using `ToolRuntime[AgentContext]`
- **Test:** Invoke tools directly with a mock `AgentContext`

**Step 8 — Web Search Tool**
- `search_tools.py` — `web_search` using `TavilyClient` directly
- **Test:** Call `tavily_client.search()` with sample queries

**Step 9 — Draft Tool + HITL**
- `draft_tools.py` — `compose_and_request_approval` with `interrupt()`
- **Test:** Verify `interrupt()` raises `GraphInterrupt` when called outside a running graph, and pauses correctly when inside `create_agent`

**Step 10 — Mail Reader Agent**
- `mail_reader_agent.py` — `create_agent(...)` with Gmail tools + `AgentContext`
- **Test:** `agent.ainvoke({"messages": [...]}, context=ctx)` for all 4 reading intents

**Step 11 — Web Search Agent**
- `web_search_agent.py` — `create_agent(...)` with Tavily tool
- **Test:** Research a topic, verify structured output

**Step 12 — Mailing Agent**
- `mailing_agent.py` — `create_agent(...)` with Gmail read tools + `compose_and_request_approval`
- **Test:** Trigger a compose flow, verify interrupt fires and draft saved to Neon

**Step 13 — Coordinator Agent**
- `coordinator.py` — `create_agent(...)` wrapping sub-agents as tools
- **Test:** All 6 intents end-to-end (without sending actual emails yet)

---

### Phase 5: Real-Time + HITL Integration (Days 11–12)

**Step 14 — Notification Service + SSE**
- `notification_service.py` with per-user `asyncio.Queue`
- Notifications SSE endpoint with 30s heartbeat ping
- **Test:** Connect SSE in browser, verify ping events arrive

**Step 15 — Chat Router with SSE Streaming**
- `/api/chat/message` SSE endpoint
- `AgentContext` construction per request
- `__interrupt__` detection → broadcast to notification SSE
- **Test:** Full chat flow — send message, see token streaming in browser

**Step 16 — Approve Router + HITL Resume**
- Approve endpoint: update DB + `Command(resume=...)` into coordinator
- **Test:** Trigger a draft → SSE fires `approval_required` → approve via API → email sent

---

### Phase 6: Frontend Completion (Days 13–15)

**Step 17 — Chat UI**
- `ChatWindow.tsx`, `MessageBubble.tsx`, `InputBar.tsx`
- `EmailCard.tsx` for rendering email summaries inside messages
- `useChat` hook (streaming from `/api/chat/message`)
- `chatStore`

**Step 18 — SSE + Notification wiring**
- `useSSE.ts` hook — connect to `/api/notifications/stream`
- Wire `approval_required` → `approvalStore.open(draft)`
- Wire `email_sent` / `email_rejected` → toast

**Step 19 — Approval Modal**
- `ApprovalModal.tsx` — editable To/Subject/Body
- Connect approve/reject buttons to `/api/approve/{draft_id}`
- Close modal on success, show toast

**Step 20 — Conversation Sidebar**
- List conversations from `/api/chat/conversations`
- "New Chat" button creates new conversation
- Clicking conversation loads history from LangGraph checkpoint

---

### Phase 7: Polish (Day 16)

**Step 21 — Error handling**
- Global FastAPI exception handler → structured `{ error, detail }` response
- Frontend error boundaries
- Retry logic in `api.ts` for 401 (trigger re-auth)

**Step 22 — Final end-to-end tests**
- ✅ Read last 5 emails
- ✅ Search emails by topic ("job opportunities")
- ✅ Search emails by sender ("BRAC Bank")
- ✅ Summarize an email thread
- ✅ Reply to an email — trigger HITL → approve → email sent → notification
- ✅ Compose fresh email on a topic — web search → draft → HITL → approve → sent

---

## Key Implementation Notes for Claude Code

1. **`ChatOpenRouter`, not `ChatOpenAI`:**
   ```python
   from langchain_openrouter import ChatOpenRouter
   llm = ChatOpenRouter(model="qwen/qwen3.5-35b-a3b", temperature=0.2, app_title="Email Agent")
   ```

2. **`create_agent`, not `create_react_agent`:**
   ```python
   from langchain.agents import create_agent
   agent = create_agent(model=llm, tools=[...], system_prompt="...", context_schema=AgentContext)
   ```

3. **`ToolRuntime` for dependency injection in tools** — never use global state or closures:
   ```python
   from langchain.tools import tool, ToolRuntime
   @tool
   async def my_tool(param: str, runtime: ToolRuntime[AgentContext]) -> str:
       service = runtime.context.gmail_service  # injected at invocation time
   ```

4. **Tavily via direct client** — not LangChain's TavilySearchResults wrapper:
   ```python
   from tavily import TavilyClient
   tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
   @tool
   def web_search(query: str) -> Dict[str, Any]:
       try:
           return tavily_client.search(query)
       except Exception as e:
           return {"error": str(e)}
   ```

5. **Two separate DB connection strings in env:**
   - `DATABASE_URL` with `postgresql+asyncpg://` prefix → SQLAlchemy ORM
   - `DATABASE_URL_PSYCOPG` with `postgresql://` prefix → LangGraph `AsyncPostgresSaver`
   Both point to the same Neon database; they just use different drivers.

6. **`AsyncPostgresSaver.setup()` in lifespan** — call once on app startup. This creates the LangGraph checkpoint tables in Neon automatically. Never create these tables manually.

7. **`interrupt()` is not an exception to catch** — it pauses the graph at the LangGraph level. The `astream()` loop will yield an event with key `"__interrupt__"`. Detect it like this:
   ```python
   async for event in agent.astream(inputs, config=config, context=context):
       if "__interrupt__" in event:
           interrupt_payload = event["__interrupt__"][0].value
           # handle it
   ```

8. **Resume uses `Command`, not a new message:**
   ```python
   from langgraph.types import Command
   await agent.ainvoke(
       Command(resume={"approved": True, "edited_body": "..."}),
       config={"configurable": {"thread_id": conversation_id}},
       context=context,
   )
   ```

9. **Sub-agent thread IDs are user-scoped, not conversation-scoped.** Only the coordinator agent needs conversation-scoped threads (for HITL resume). Sub-agents are called as tools within a coordinator turn and don't need persistent cross-turn state.

10. **CORS `allow_credentials=True` is mandatory** — the frontend sends the JWT as an httpOnly cookie. Without this, the browser will block the cookie on CORS preflight.

11. **`X-Accel-Buffering: no`** header on SSE responses — prevents nginx from buffering the stream, which would make the real-time experience broken in production.

12. **Gmail reply threading** — when sending a reply, construct the MIME message with:
    ```python
    msg["In-Reply-To"] = original_message_id
    msg["References"] = original_message_id
    # AND pass threadId to the Gmail API send call
    service.users().messages().send(userId="me", body={"raw": encoded, "threadId": thread_id})
    ```
    Without both headers AND `threadId`, Gmail will create a new thread instead of threading the reply.

---

*End of Implementation Plan — Version 2.0*
