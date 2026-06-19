# AGENTS.md

## Project Overview
- **Area:** Backend API for the Autonomous Email Agent.
- **Goal:** provide a FastAPI service for Google OAuth, Gmail integration, LangChain/LangGraph agent orchestration, SSE streaming, human-in-the-loop approval resume, and Postgres persistence.
- **Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic, PostgreSQL (asyncpg/psycopg), Authlib (Google OAuth), `google-api-python-client` (Gmail), LangChain v1 + LangGraph v1 (`langgraph-checkpoint-postgres`), `langchain-openrouter` (LLM), Tavily (web search). Python 3.11+.

For full product context, read [README.md](../README.md). For repo-wide rules, read [../AGENTS.md](../AGENTS.md).

## Commands
Run from `backend/` with the venv active (PowerShell). This project uses **pip + venv**, not uv/poetry.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env          # then fill in real values
alembic upgrade head                 # requires DATABASE_URL_PSYCOPG
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verification:
- **Compile check:** `python -m compileall app` (the README's documented check)
- **Tests:** `python -m unittest discover -s tests` (stdlib `unittest`; pytest is NOT installed)
- **Health:** `GET http://localhost:8000/health`

Notes:
- There is **no lint command** — ruff is not installed and no ruff config exists. Do not run `uv run ruff check .`.
- There is **no pyproject.toml / uv.lock**. Do not run `uv sync` or `uv run ...`.
- The FastAPI app object is `app.main:app`.

## Environment
Copy `.env.example` to `.env`. Required values: `APP_ENV`, `APP_URL`, `SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRY_HOURS`, `DATABASE_URL`, `DATABASE_URL_PSYCOPG`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `TOKEN_ENCRYPTION_KEY`, `OPENROUTER_API_KEY`, `TAVILY_API_KEY`, `FRONTEND_URL`. Optional LangSmith tracing: `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`, `LANGSMITH_API_KEY`.

The two DB URLs point to the **same** database:
- `DATABASE_URL` uses `postgresql+asyncpg://...` (asyncpg) and is consumed by SQLAlchemy in `app/database.py`. asyncpg query params use `ssl=`/`timeout=`, which `database.py` normalizes into `connect_args`.
- `DATABASE_URL_PSYCOPG` uses `postgresql://...` (psycopg3) and is consumed by LangGraph's `AsyncPostgresSaver` (`app/checkpointer.py`) and by Alembic (`config.sync_database_url` returns this). psycopg uses `sslmode=`/`connect_timeout=`.

## Architecture

### Entry point (`app/main.py`)
- `FastAPI(title="Email Agent API", lifespan=lifespan)`. Lifespan runs `Base.metadata.create_all` for local bootstrap (Alembic is still the source of truth), then `await checkpointer.setup()` to create LangGraph checkpoint tables, storing it on `app.state.checkpointer`.
- Middleware order: `CORSMiddleware` (origins=`[FRONTEND_URL]`, credentials) then `SessionMiddleware` (Authlib OAuth needs it).
- Routers mounted: `/api/auth`, `/api/chat`, `/api/emails`, `/api/approve`, `/api/notifications`.
- Global exception handlers produce a uniform `{"error": <ExceptionClassName>, "detail": ...}` shape for `HTTPException`, `RequestValidationError` (422), and a catch-all 500.
- `GET /health` → `{"status": "ok"}`.

### Routers (`app/routers/`)
- `auth.py`: `GET /login` (Google OAuth redirect), `GET /callback` (exchanges code, upserts User with encrypted tokens, sets httpOnly `access_token` JWT cookie, redirects to `FRONTEND_URL/dashboard`), `POST /logout` (clears cookie), `GET /me` (protected, returns `AuthenticatedUser`).
- `chat.py` (largest router): `POST /conversations`, `GET /conversations`, `GET /history/{conversation_id}` (reconstructs structured assistant turns from LangGraph checkpoint messages + `EmailDraft` rows), `POST /message` (**SSE streaming** — runs the coordinator with `thread_id=conversation_id`, emits `turn_started`/`token`/`approval_pending`/`turn_completed`/`done`/`error`).
- `emails.py`: direct Gmail reads — `GET /recent`, `GET /search`, `GET /{message_id}` (each builds `GmailService(access_token)` from `get_valid_access_token`).
- `approve.py`: `GET /pending`, `POST /{draft_id}` (the HITL resume endpoint — validates ownership/pending state, then resumes the same LangGraph thread with `Command(resume={"decisions": [...]})`; sets `needs_research_refresh` when a fresh draft is rejected with research cues).
- `notifications.py`: `GET /stream` (**SSE** long-lived, 30s ping keepalives), `GET /` (paginated list), `PATCH /{notification_id}/read`.

### Agents (`app/agents/`)
LangChain v1 `create_agent` style with `HumanInTheLoopMiddleware`.
- `coordinator.py`: the orchestrator. `EmailAgentState(AgentState)` adds `current_draft`, `research_summary`, `draft_feedback`, `needs_research_refresh`. `make_coordinator_tools` builds `call_mail_reader`, `call_web_search`, `call_mailing_agent` (each delegates to a sub-agent via `.ainvoke` with **user-scoped** thread IDs like `mail_reader_{user_id}`, returning `Command(update=...)`) plus `send_email` (the HITL boundary). `get_coordinator_agent(checkpointer)` is a memoized factory that rebuilds only when the checkpointer identity changes.
- `mail_reader_agent.py`: read-only (5 Gmail read/search tools). `mailing_agent.py`: draft-only, never sends. `web_search_agent.py`: Tavily research. All memoized factories.
- `context.py`: `@dataclass AgentContext(user_id, conversation_id, gmail_service, db_session, notification_service)` — the LangGraph `context_schema` passed to every agent.
- `llm.py`: `@lru_cache get_llm() -> ChatOpenRouter` — model `qwen/qwen3.6-plus-preview:free`, temperature 0.1, max_tokens 4096. Sets `LANGSMITH_*` env vars only when `LANGSMITH_TRACING=true`.
- `tools/gmail_tools.py` (5 async tools reading `runtime.context.gmail_service`), `tools/search_tools.py` (Tavily `web_search`), `tools/draft_tools.py` (`send_email` — after resume sends via Gmail, updates the `EmailDraft` to `sent`/`send_failed`, creates a notification, broadcasts, returns `Command(update=...)` clearing draft state).

### Services (`app/services/`)
- `auth_service.py`: `build_jwt_for_user` (HS256), `build_oauth_scopes` (openid/email/profile + gmail.readonly + gmail.send), `get_valid_access_token(user_id, db)` (returns cached token if >5 min from expiry, else refreshes via refresh_token, re-encrypts, persists), `refresh_google_access_token`, `fetch_google_userinfo`.
- `gmail_service.py`: `GmailService(access_token)` wraps `googleapiclient.discovery.build("gmail","v1")`; async methods offload sync Gmail calls via `asyncio.to_thread` (`list_messages`, `get_message`, `get_thread`, `send_email`). `_build_query` constructs Gmail search syntax.
- `hitl_service.py`: `is_hitl_interrupt`, `persist_hitl_interrupts` (creates `EmailDraft` rows with `status="pending_approval"`, creates notifications, broadcasts `approval_required`).
- `notification_service.py`: `NotificationService` — per-user in-memory `asyncio.Queue` broadcaster (`subscribe`/`unsubscribe`/`broadcast`) + `create_notification` (persists a row). Module-level singleton `notification_service` is the SSE backbone.

### Models / Schemas / Utils
- `models/` (SQLAlchemy 2.0 `Mapped`/`mapped_column`, UUID PKs): `users`, `conversations`, `email_drafts` (`draft_type` and `status` CHECK constraints), `notifications` (JSONB `metadata`). Google OAuth tokens are Fernet-encrypted at rest in `users`.
- `schemas/` (Pydantic v2): request/response models per router.
- `utils/`: `email_parser.py` (base64url decode, multipart text/plain→html fallback, thread sorting), `token_encryption.py` (Fernet `encrypt_token`/`decrypt_token`).
- `middleware/auth_middleware.py`: `get_current_user` is a FastAPI dependency (not ASGI middleware) — decodes the JWT cookie, loads `User`, raises 401. Used on every protected endpoint.
- `checkpointer.py`: singleton `AsyncPostgresSaver` over a `psycopg_pool.AsyncConnectionPool` (min 1/max 5, `dict_row`, `prepare_threshold=None`) on `DATABASE_URL_PSYCOPG`.

### Database / Migrations
- Alembic config: `alembic.ini` leaves `sqlalchemy.url` blank; `alembic/env.py` injects `settings.sync_database_url` (= `DATABASE_URL_PSYCOPG`) and sets `target_metadata = Base.metadata`.
- One migration: `alembic/versions/001_initial_schema.py` (creates `pgcrypto` extension, all 4 tables, indexes, CHECK/FK constraints).
- Two persistence layers in the same DB: app tables (Alembic) and LangGraph checkpoint tables (`AsyncPostgresSaver.setup()` at startup). `main.py` also runs `Base.metadata.create_all` as a local bootstrap convenience, but Alembic is the source of truth.

## Conventions
- `from __future__ import annotations` at the top of essentially every module; PEP 604 unions (`str | None`) everywhere.
- Fully async: routers, services, tools are `async def`; DB via `AsyncSession`; Gmail calls via `asyncio.to_thread`.
- Dependency injection: `Depends(get_db)` for the session, `Depends(get_current_user)` for the authed `User`, `request.app.state.checkpointer` for the LangGraph checkpointer.
- Pydantic v2 for schemas; SQLAlchemy 2.0 typed `Mapped`/`mapped_column` for models.
- Memoized agent factories rebuild only when the checkpointer identity changes (it is created during lifespan startup).
- LangGraph: coordinator thread = `conversation_id`; sub-agent threads are user-scoped. State updates use `Command(update=...)`. HITL via `HumanInTheLoopMiddleware(interrupt_on={"send_email": ...})`; resume via `Command(resume={"decisions": [...]})`.
- Uniform error shape `{"error": <ClassName>, "detail": ...}` from `main.py` global handlers.
- SSE framing: `text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `data: {json}\n\n`.
- Notifications are dual-path: persisted `Notification` rows (list/read API) + in-memory queue broadcast (live SSE).

## Testing
- Framework: stdlib `unittest` (`TestCase`/`IsolatedAsyncioTestCase`). **pytest is NOT installed**; there is no `pytest.ini`/`conftest.py`.
- Run: `python -m unittest discover -s tests` (from `backend/`).
- Existing passing tests: `test_auth_service.py`, `test_email_parser.py`, `test_gmail_service.py`, `test_notification_service.py` (pure-function/service unit tests with mocks/fakes).
- `test_agent_factories.py` and `test_agent_tools.py` are **stale and broken** — they reference functions that no longer exist after a refactor (`get_mailing_draft_agent`, `fresh_email_routing`, `prepare_fresh_email_with_research`, `compose_and_request_approval`). Fix or delete these when touching agent code.
- No router/integration/DB/LangGraph-workflow tests exist yet.

## Do
- Keep FastAPI as the backend boundary; all privileged operations (Gmail, token refresh, persistence) stay server-side.
- Keep request/response models explicit with Pydantic v2 and async DB access via `AsyncSession`.
- Use the memoized agent factory pattern (`get_coordinator_agent`, etc.) so agents reuse the lifespan-created checkpointer.
- Keep the coordinator conversation-scoped (`thread_id=conversation_id`) and sub-agents user-scoped.
- Persist an `EmailDraft` with `status="pending_approval"` before the LangGraph `interrupt()` resumes the send.
- Refresh the conversation history in the frontend after resume completes (sent/rejected/rewritten/failed states).
- Use `get_valid_access_token(user_id, db)` to always obtain a non-expired Gmail access token (it auto-refreshes).
- Encrypt Google tokens at rest with Fernet (`TOKEN_ENCRYPTION_KEY`).

## Don't
- Do not move auth, Gmail, or orchestration logic into the Next.js frontend.
- Do not put the JWT in an Authorization header client-side — it is an httpOnly cookie.
- Do not run `uv ...` or `ruff check .` — neither uv nor ruff is set up in this repo.
- Do not assume pytest is available — use stdlib `unittest`.
- Do not perform the Gmail send (non-idempotent side effect) before the LangGraph `interrupt()` resumes.
- Do not let sub-agents share the coordinator's conversation-scoped thread; use user-scoped thread IDs.
- Do not rely on `Base.metadata.create_all` as the schema source of truth in production — use Alembic migrations.

## When Stuck
- Verify exact env values in `backend/.env` before debugging auth/Gmail/DB failures (both DB URLs, all Google OAuth creds, `TOKEN_ENCRYPTION_KEY`, `OPENROUTER_API_KEY`, `TAVILY_API_KEY`).
- For OpenRouter model issues, confirm the current model ID in `app/agents/llm.py`.
- Prefer the local LangChain/LangGraph skills first. If they leave uncertainty about current APIs, consult the LangChain docs MCP server at `https://docs.langchain.com/mcp`.

## Related Docs
- `../README.md` for product purpose, status, architecture, API overview, and env vars.
- `../IMPLEMENTATION_PLAN_V2.md` for the original phased build plan.
- `../frontend/AGENTS.md` for the frontend contract (auth cookie, SSE event names, content blocks).
