# Backend Environment

Copy [`../.env.example`](../.env.example) to `backend/.env` and fill in real values.
`app/config.py` (`Settings(BaseSettings)`) loads `.env` and provides safe defaults for every var so the app imports without a `.env`, but Google OAuth, Fernet, OpenRouter, and Tavily will fail at runtime without real values.

## Required Variables

| Variable | Purpose | Notes |
|---|---|---|
| `APP_ENV` | `development` toggles SQLAlchemy `echo=True` and non-secure cookie | |
| `APP_URL` | passed to `ChatOpenRouter` as `app_url` | |
| `API_PORT` | local dev server port used by `python -m app.dev_server` | defaults to `8000` |
| `SECRET_KEY` | JWT signing + Starlette `SessionMiddleware` secret | |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `JWT_EXPIRY_HOURS` | JWT lifetime | `24` |
| `DATABASE_URL` | SQLAlchemy async engine | **`postgresql+asyncpg://...`** (asyncpg driver) |
| `DATABASE_URL_PSYCOPG` | LangGraph `AsyncPostgresSaver` + Alembic | **`postgresql://...`** (psycopg3 driver) |
| `GOOGLE_CLIENT_ID` | Google OAuth | |
| `GOOGLE_CLIENT_SECRET` | Google OAuth | |
| `GOOGLE_REDIRECT_URI` | OAuth callback | `http://localhost:8000/api/auth/callback` |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting stored Google tokens | |
| `OPENROUTER_API_KEY` | LLM provider | model `qwen/qwen3.6-plus-preview:free` |
| `TAVILY_API_KEY` | web search | |
| `FRONTEND_URL` | CORS origin (`http://localhost:3000`) + OAuth redirect target | |

## Optional (LangSmith tracing)

| Variable | Default |
|---|---|
| `LANGSMITH_TRACING` | `false` |
| `LANGSMITH_PROJECT` | `email-agent` |
| `LANGSMITH_ENDPOINT` | `https://api.smith.langchain.com` |
| `LANGSMITH_API_KEY` | only needed if tracing enabled |

`app/agents/llm.py` sets the `LANGSMITH_*` env vars only when `LANGSMITH_TRACING=true`. There is no direct `langsmith` import in app code; `langsmith` is installed transitively.

## The Two Database URLs (important)

Both `DATABASE_URL` and `DATABASE_URL_PSYCOPG` point to the **same Postgres database** (Neon in production). They exist because asyncpg and psycopg use incompatible connection drivers and query-string conventions.

- **`DATABASE_URL`** — `postgresql+asyncpg://...`
  - Consumed only by **SQLAlchemy** in `app/database.py` for the app's own tables (users, conversations, email_drafts, notifications).
  - asyncpg query params use `ssl=require` and `timeout=10`.
  - `database.py`'s `_build_async_engine_config` pops `ssl`/`timeout` out of the URL string and into typed `connect_args` (asyncpg needs native types, not strings).

- **`DATABASE_URL_PSYCOPG`** — `postgresql://...`
  - Consumed by **LangGraph's `AsyncPostgresSaver`** (`app/checkpointer.py`, via `psycopg_pool.AsyncConnectionPool`).
  - Consumed by **Alembic** (`app/config.py`'s `sync_database_url` property returns it; `alembic/env.py` sets `sqlalchemy.url` from it).
  - psycopg query params use `sslmode=require` and `connect_timeout=10`.

There is **no Firestore, Firebase, or SQLite fallback** in this project.
