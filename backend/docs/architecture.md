# Backend Architecture

This is the detailed architecture of the FastAPI backend in `backend/app/`.
For commands, conventions, and rules see [`../AGENTS.md`](../AGENTS.md).
For environment variables see [`environment.md`](environment.md).
For product-level context see [`../../README.md`](../../README.md).

## Tech Stack
- **Web:** FastAPI 0.135, Uvicorn, Starlette (`SessionMiddleware` for Authlib OAuth), `python-multipart`.
- **Database:** SQLAlchemy 2.0 async (`asyncpg`), Alembic, `psycopg[binary,pool]` (LangGraph checkpointing).
- **Auth:** Authlib (Google OAuth), `python-jose` (HS256 JWT), `cryptography` (Fernet token encryption), `httpx`.
- **Gmail:** `google-api-python-client` + `google-auth`.
- **LLM/Agents:** LangChain v1, LangGraph v1, `langgraph-checkpoint-postgres`, `langchain-openrouter` (model `qwen/qwen3.6-plus-preview:free`), Tavily (web search).
- **Config:** `pydantic-settings`, `python-dotenv`.
- **Python:** 3.11+.

## Entry Point (`app/main.py`)
- `FastAPI(title="Email Agent API", lifespan=lifespan)`.
- **Lifespan** (`@asynccontextmanager`): on startup runs `Base.metadata.create_all` inside `engine.begin()` (local bootstrap convenience; Alembic is the source of truth), then `await get_checkpointer()` + `await checkpointer.setup()` (creates LangGraph checkpoint tables), stores it on `app.state.checkpointer`. On shutdown: `close_checkpointer()` + `engine.dispose()`.
- **Middleware order:** `CORSMiddleware` (allow_origins=`[settings.FRONTEND_URL]`, credentials, all methods/headers), then `SessionMiddleware` (Starlette, `secret_key=settings.SECRET_KEY`) — needed by Authlib's OAuth flow.
- **Routers mounted** with prefixes: `auth` → `/api/auth`, `chat` → `/api/chat`, `emails` → `/api/emails`, `approve` → `/api/approve`, `notifications` → `/api/notifications`.
- **Global exception handlers** produce a uniform `{"error": <ExceptionClassName>, "detail": ...}` shape:
  - `HTTPException` → echoes status code; `detail` is dict/list or string.
  - `RequestValidationError` → 422 with `detail: exc.errors()`.
  - catch-all `Exception` → 500, logs, `detail: "Internal server error"`.
- `GET /health` → `{"status": "ok"}`.

## Config & Database
- `app/config.py`: `Settings(BaseSettings)` via `pydantic-settings`, loads `.env` (`extra="ignore"`). All settings have defaults so the app imports without a full env. Exposes `sync_database_url` property → returns `DATABASE_URL_PSYCOPG` (used by Alembic). `@lru_cache get_settings()` + module-level `settings` singleton.
- `app/database.py`: `_build_async_engine_config` normalizes the asyncpg URL — pops `ssl`/`timeout` query params out of the URL and into typed `connect_args` (asyncpg needs native types, not strings). `engine = create_async_engine(...)` with `echo = (APP_ENV == "development")`. `AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)`. `get_db()` is the async generator dependency yielding an `AsyncSession`.
- `app/checkpointer.py`: singleton `AsyncPostgresSaver` (from `langgraph.checkpoint.postgres.aio`) over a `psycopg_pool.AsyncConnectionPool` (min_size=1, max_size=5, autocommit=True, `prepare_threshold=None`, `dict_row` row factory) connected to `settings.DATABASE_URL_PSYCOPG`. `get_checkpointer()` lazily builds it via `AsyncExitStack`; `close_checkpointer()` tears it down. Stored on `app.state.checkpointer` at startup.

## Routers (`app/routers/`)

### `auth.py` (prefix `/api/auth`)
- `GET /login` — redirects to Google OAuth (Authlib `OAuth` client registered as `google`; scopes `openid email profile gmail.readonly gmail.send`; `access_type=offline`, `prompt=consent`, `include_granted_scopes=true`).
- `GET /callback` — exchanges code, fetches userinfo via `fetch_google_userinfo`, upserts `User` (encrypts access/refresh tokens with Fernet), sets an httpOnly JWT cookie `access_token`, redirects to `{FRONTEND_URL}/dashboard`. On OAuth error redirects to `{FRONTEND_URL}/login?error=...`.
- `POST /logout` — deletes the `access_token` cookie.
- `GET /me` (`response_model=AuthenticatedUser`) — protected by `get_current_user`.

### `chat.py` (prefix `/api/chat`) — the largest router
- `POST /conversations` → `CreateConversationResponse` — creates a `Conversation` row.
- `GET /conversations` → `list[ConversationSummary]` — user's conversations, ordered by `updated_at` desc.
- `GET /history/{conversation_id}` → `list[ChatMessageResponse]` — loads LangGraph checkpoint messages via `app.state.checkpointer.aget_tuple({"configurable": {"thread_id": conversation_id}})` plus `EmailDraft` rows, then reconstructs structured assistant turns (`_serialize_history`) with content blocks: `markdown`, `status`, `tool_action`, `email_list`, `summary`, `research_report`, `draft_email`.
- `POST /message` — **SSE streaming** (`StreamingResponse`, `text/event-stream`). Builds `AgentContext`, gets the coordinator via `get_coordinator_agent(request.app.state.checkpointer)`, runs `coordinator.astream(..., stream_mode=["messages","updates"], version="v2")` with `thread_id = conversation_id`. Emits SSE events: `turn_started`, `token`, `approval_pending` (when a HITL interrupt is detected via `is_hitl_interrupt` and persisted via `persist_hitl_interrupts`), `turn_completed`, `done`, `error`. Sets the conversation title from the first message.
- Heavy helper layer parses sub-agent tool outputs (mail reader JSON payload, research payload) into UI blocks.

### `emails.py` (prefix `/api/emails`) — direct Gmail reads, all protected
- `GET /recent?count=` (1–20, default 5) → `list[EmailSummary]`.
- `GET /search?q=&sender=&topic=&count=` (1–20, default 10) → `list[EmailSummary]`.
- `GET /{message_id}` → `EmailDetail`.
- Each builds a `GmailService(access_token)` from `get_valid_access_token`.

### `approve.py` (prefix `/api/approve`) — HITL resume
- `GET /pending` — lists drafts with `status="pending_approval"` for the user.
- `POST /{draft_id}` (`ApprovalRequest` → `ApprovalResponse`) — the core resume endpoint. Validates ownership + pending state. For `edit`/`approve` stores edited fields; for `reject` marks `status="rejected"`, creates a notification, broadcasts `email_rejected`. Then resumes the same LangGraph thread with `coordinator.astream(Command(resume={"decisions": [_build_decision(...)]}, update={current_draft, draft_feedback, needs_research_refresh}), ...)`. `needs_research_refresh` is set when a fresh draft is rejected and feedback contains research cues (`_feedback_requires_research`). Persists any new HITL interrupts surfaced during resume.

### `notifications.py` (prefix `/api/notifications`)
- `GET /stream` — **SSE** long-lived stream. Subscribes to the in-memory `notification_service` queue, 30s timeout yields `{"type":"ping"}` keepalives, unsubscribes on cancel.
- `GET ""` (root, i.e. `/api/notifications`) — paginated list (`page`, `limit` up to 100) → `list[NotificationResponse]`.
- `PATCH /{notification_id}/read` — marks read.

## Auth Dependency (`app/middleware/auth_middleware.py`)
`get_current_user(access_token: str | None = Cookie, db = Depends(get_db)) -> User` — decodes the JWT cookie (`jose.jwt.decode`, algorithm `JWT_ALGORITHM`), loads `User` by `sub`, raises 401 on missing/invalid token or missing user. This is the auth dependency used everywhere; despite the directory name `middleware/`, it is a FastAPI dependency, not ASGI middleware.

## Agents (`app/agents/`) — LangChain v1 `create_agent` style
- `context.py`: `@dataclass AgentContext(user_id, conversation_id, gmail_service, db_session, notification_service)` with `user_uuid`/`conversation_uuid` properties. This is the LangGraph `context_schema` passed to every agent.
- `llm.py`: `@lru_cache get_llm() -> ChatOpenRouter` — model `qwen/qwen3.6-plus-preview:free`, temperature 0.1, max_tokens 4096, `app_url=settings.APP_URL`, `app_title="Email Agent"`. Sets `LANGSMITH_*` env vars only if `LANGSMITH_TRACING=true`.
- `coordinator.py`: the orchestrator. Defines `EmailAgentState(AgentState)` with extra fields `current_draft`, `research_summary`, `draft_feedback`, `needs_research_refresh`. A `@dynamic_prompt` `coordinator_prompt` injects state into the system prompt. `make_coordinator_tools(checkpointer)` builds 4 tools: `call_mail_reader`, `call_web_search`, `call_mailing_agent` (each delegates to a sub-agent via `.ainvoke` with **user-scoped** thread IDs like `mail_reader_{user_id}`, returns `Command(update=...)`), plus `send_email` (imported from `draft_tools`). `get_coordinator_agent(checkpointer)` is a memoized factory (rebuilds if checkpointer identity changes) using `create_agent(model, tools, system_prompt, state_schema, context_schema, checkpointer, middleware=[coordinator_prompt, HumanInTheLoopMiddleware(interrupt_on={"send_email": {allowed_decisions: approve/edit/reject, description fn}})], name="coordinator")`.
- `mail_reader_agent.py`: read-only agent, tools = `get_recent_emails, search_emails_by_sender, search_emails_by_topic, get_email_thread, get_full_email`. Memoized factory.
- `mailing_agent.py`: draft-only agent (never sends), tools = `get_full_email, get_email_thread`. Strict JSON output schema enforced via prompt. Memoized factory `get_mailing_agent`.
- `web_search_agent.py`: research agent, tool = `web_search` (Tavily). Memoized factory.
- `tools/gmail_tools.py`: 5 `@tool` async functions reading from `runtime.context.gmail_service`, formatting output as plain-text blocks the LLM consumes.
- `tools/search_tools.py`: `@lru_cache get_tavily_client()` + `@tool web_search(query)` (search_depth="advanced", max_results=5, include_answer="advanced").
- `tools/draft_tools.py`: `@tool async send_email(...)` — the **HITL boundary**. After resume it calls `gmail_service.send_email`, updates the latest pending `EmailDraft` to `sent` (+ `gmail_sent_id`) or `send_failed`, creates a notification, broadcasts `email_sent`/`error`, and returns a `Command(update=...)` clearing `current_draft`/`draft_feedback`/`needs_research_refresh`.

## Services (`app/services/`)
- `auth_service.py`: `build_jwt_for_user` (HS256 JWT with sub/iat/exp), `build_oauth_scopes` (openid/email/profile + gmail.readonly + gmail.send), `compute_token_expiry`, `gmail_scopes_granted` (requires both gmail scopes), `fetch_google_userinfo` (httpx GET to openidconnect userinfo), `refresh_google_access_token` (httpx POST to `oauth2.googleapis.com/token`), and `get_valid_access_token(user_id, db)` — returns cached access token if >5 min from expiry, else refreshes via refresh_token, re-encrypts, and persists.
- `gmail_service.py`: `GmailService(access_token)` wraps `googleapiclient.discovery.build("gmail","v1", credentials=Credentials(token=...), cache_discovery=False)`. Async methods offload synchronous Gmail API calls to threads via `asyncio.to_thread`: `list_messages`, `get_message`, `get_thread`, `send_email` (builds `EmailMessage`, base64url-encodes, sets `threadId` if reply). `_build_query(sender, topic, days_back, query)` constructs Gmail search syntax. Uses `app.utils.email_parser` for parsing.
- `hitl_service.py`: `_send_email_requests(interrupt_value)` extracts `send_email` action requests from a LangGraph interrupt payload; `is_hitl_interrupt(interrupt_value)`; `serialize_draft_for_frontend`; `persist_hitl_interrupts(...)` — for each `send_email` request, creates an `EmailDraft` row with `status="pending_approval"`, commits, creates a notification, broadcasts an `approval_required` event, returns the events list.
- `notification_service.py`: `NotificationService` — per-user in-memory event broadcaster using `defaultdict[str, list[asyncio.Queue]]`. `subscribe`/`unsubscribe`/`broadcast` + `create_notification` (persists a `Notification` row). A module-level singleton `notification_service = NotificationService()` is the SSE backbone.

## Models (`app/models/`) — SQLAlchemy 2.0 `Mapped`/`mapped_column`, UUID PKs (`postgresql.UUID`)
- `base.py`: `class Base(DeclarativeBase): pass`.
- `user.py` (`users`): id, google_id (unique), email (unique), name, picture_url, access_token (encrypted, NOT NULL), refresh_token (encrypted), token_expiry, gmail_scope_granted, created_at, updated_at. Relationships: conversations, email_drafts, notifications (cascade all, delete-orphan).
- `conversation.py` (`conversations`): id, user_id (FK users CASCADE), title, created_at, updated_at. Relationships back to user + email_drafts.
- `email_draft.py` (`email_drafts`): id, user_id (FK CASCADE), conversation_id (FK conversations SET NULL), draft_type (`reply`|`fresh` — CHECK), to_address, subject, body, in_reply_to, thread_id, status (`pending_approval`|`approved`|`rejected`|`sent`|`send_failed` — CHECK, default `pending_approval`), edited_to/edited_subject/edited_body, gmail_sent_id, created_at, updated_at.
- `notification.py` (`notifications`): id, user_id (FK CASCADE), type, title, body, `metadata_json` mapped to a JSONB column named `metadata` (default dict), is_read, created_at.
- `__init__.py` re-exports `Base, Conversation, EmailDraft, Notification, User`.

## Schemas (`app/schemas/`) — Pydantic v2 `BaseModel`
- `auth.py`: `AuthenticatedUser`.
- `chat.py`: `CreateConversationResponse`, `ConversationSummary`, `ChatMessageRequest` (`conversation_id`, `message`), `ChatMessageResponse` (with `content_blocks: list[dict]`, `status`, `turn_id`).
- `email.py`: `EmailSummary`, `EmailDetail(EmailSummary)`.
- `approval.py`: `ApprovalRequest` (`action: Literal["approve","edit","reject"]`, optional edited fields, feedback), `ApprovalResponse`.
- `notification.py`: `NotificationResponse`.

## Utils (`app/utils/`)
- `email_parser.py`: pure functions — base64url decode, HTML strip, multipart `text/plain` then `text/html` fallback, header extraction (`parseaddr`), `parse_gmail_message`, `parse_gmail_thread` (sorts by `internalDate`).
- `token_encryption.py`: Fernet symmetric encryption (`@lru_cache get_fernet()` from `TOKEN_ENCRYPTION_KEY`), `encrypt_token`/`decrypt_token` (raises `ValueError` on `InvalidToken`).

## Database & Migrations
- **Alembic** config in `backend/alembic.ini`: `script_location = alembic`, `prepend_sys_path = .`, `sqlalchemy.url` intentionally blank (injected at runtime).
- `alembic/env.py`: imports `app.config.settings` and `app.models.Base`, sets `sqlalchemy.url` to `settings.sync_database_url` (= `DATABASE_URL_PSYCOPG`), sets `target_metadata = Base.metadata`, enables `compare_type=True`. Has `run_migrations_offline()` and `run_migrations_online()` (`pool.NullPool`).
- **One migration:** `alembic/versions/001_initial_schema.py` (`revision = "001_initial_schema"`, `down_revision = None`): `CREATE EXTENSION IF NOT EXISTS "pgcrypto"`; creates `users`, `conversations` (index on `user_id`), `email_drafts` (indexes on `status`/`user_id`; CHECK constraints on `draft_type`/`status`; FKs users CASCADE, conversations SET NULL), `notifications` (partial index `idx_notifications_user_unread WHERE is_read = false`; `metadata` JSONB default `'{}'::jsonb`). `downgrade()` drops everything in reverse.
- The migration matches the SQLAlchemy models exactly.
- **Two persistence layers** in the same DB:
  1. App tables — managed by **Alembic** (`alembic upgrade head`).
  2. LangGraph checkpoint tables — managed automatically by `AsyncPostgresSaver.setup()` called in `main.py` lifespan.
- Note: `main.py` lifespan *also* runs `Base.metadata.create_all` as a local bootstrap convenience, but Alembic is the source of truth.

## Cross-Cutting Flows

### Auth flow (cookie-based)
1. `GET /api/auth/login` → Google OAuth redirect (scopes include `gmail.readonly` + `gmail.send`).
2. `GET /api/auth/callback` → exchange code, `fetch_google_userinfo`, upsert `User` with Fernet-encrypted tokens, build HS256 JWT, set httpOnly `access_token` cookie, redirect to `{FRONTEND_URL}/dashboard`.
3. `GET /api/auth/me` → `get_current_user` decodes cookie, loads `User`.
4. `POST /api/auth/logout` → deletes the cookie.
5. `get_valid_access_token(user_id, db)` auto-refreshes the Google access token via refresh_token when <5 min from expiry.

### Chat → HITL → approval resume
1. `POST /api/chat/message` (SSE) runs the coordinator with `thread_id = conversation_id`.
2. The `send_email` tool is wrapped in `HumanInTheLoopMiddleware(interrupt_on={"send_email": ...})` → LangGraph interrupts before sending.
3. `persist_hitl_interrupts` creates an `EmailDraft` (`status="pending_approval"`), creates a notification, broadcasts `approval_required`; an `approval_pending` SSE event is sent on the chat stream.
4. `POST /api/approve/{draft_id}` resumes the same LangGraph thread with `Command(resume={"decisions": [...]})`. `needs_research_refresh` is set when a fresh draft is rejected with research cues.
5. On resume, `send_email` performs the Gmail send, updates the `EmailDraft` to `sent`/`send_failed`, creates a notification, broadcasts `email_sent`/`error`, and clears draft state.

### SSE
Two SSE streams, both `text/event-stream` with `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `data: {json}\n\n` framing:
- `/api/chat/message` — request-scoped assistant streaming (`turn_started`, `token`, `approval_pending`, `turn_completed`, `done`, `error`).
- `/api/notifications/stream` — long-lived approval/send notifications (`approval_required`, `email_sent`, `email_rejected`, `error`, `ping` keepalives).

## Thread Scoping
- Coordinator thread = `conversation_id` (conversation-scoped).
- Sub-agent threads are **user-scoped**: `f"mail_reader_{user_id}"`, `f"mailing_agent_{user_id}"`, `f"web_search_{user_id}"`. Sub-agents never share the coordinator's conversation-scoped thread.

## Repository Layout
```
backend/
  alembic/
    env.py
    script.py.mako
    versions/001_initial_schema.py
  app/
    __init__.py
    main.py
    config.py
    database.py
    checkpointer.py
    agents/
      __init__.py
      context.py
      llm.py
      coordinator.py
      mail_reader_agent.py
      mailing_agent.py
      web_search_agent.py
      tools/
        __init__.py
        gmail_tools.py
        search_tools.py
        draft_tools.py
    middleware/
      __init__.py
      auth_middleware.py
    models/
      __init__.py
      base.py
      user.py
      conversation.py
      email_draft.py
      notification.py
    routers/
      __init__.py
      auth.py
      chat.py
      emails.py
      approve.py
      notifications.py
    schemas/
      __init__.py
      auth.py
      chat.py
      email.py
      approval.py
      notification.py
    services/
      __init__.py
      auth_service.py
      gmail_service.py
      hitl_service.py
      notification_service.py
    utils/
      __init__.py
      email_parser.py
      token_encryption.py
  tests/
  requirements.txt
  alembic.ini
  .env.example
```
