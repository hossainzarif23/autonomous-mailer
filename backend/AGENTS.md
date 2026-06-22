# AGENTS.md

## Project Overview
- **Area:** Backend API for the Autonomous Email Agent.
- **Goal:** provide a FastAPI service for Google OAuth, Gmail integration, LangChain/LangGraph agent orchestration, SSE streaming, human-in-the-loop approval resume, and Postgres persistence.
- **Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic, PostgreSQL (asyncpg/psycopg), Authlib (Google OAuth), `google-api-python-client` (Gmail), LangChain v1 + LangGraph v1 (`langgraph-checkpoint-postgres`), `langchain-openrouter` (LLM), Tavily (web search). Python 3.11+.

For full product context, read [../README.md](../README.md). For repo-wide rules, read [../AGENTS.md](../AGENTS.md).
For the detailed backend architecture, read [docs/architecture.md](docs/architecture.md). For environment variables, read [docs/environment.md](docs/environment.md).

## Commands
Run from `backend/` with the venv active (PowerShell). This project uses **pip + venv**, not uv/poetry.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env          # then fill in real values (see docs/environment.md)
alembic upgrade head                 # requires DATABASE_URL_PSYCOPG
python -m app.dev_server
```

Verification:
- **Compile check:** `python -m compileall app` (the README's documented check)
- **Tests:** `python -m unittest discover -s tests` (stdlib `unittest`; pytest is NOT installed)
- **Health:** `GET http://localhost:8000/health`

Notes:
- There is **no lint command** — ruff is not installed and no ruff config exists. Do not run `uv run ruff check .`.
- There is **no pyproject.toml / uv.lock**. Do not run `uv sync` or `uv run ...`.
- The FastAPI app object is `app.main:app`.

## Conventions
- `from __future__ import annotations` at the top of essentially every module; PEP 604 unions (`str | None`) everywhere.
- Fully async: routers, services, tools are `async def`; DB via `AsyncSession`; Gmail calls via `asyncio.to_thread`.
- Dependency injection: `Depends(get_db)` for the session, `Depends(get_current_user)` for the authed `User`, `request.app.state.checkpointer` for the LangGraph checkpointer.
- Pydantic v2 for schemas; SQLAlchemy 2.0 typed `Mapped`/`mapped_column` for models.
- Memoized agent factories rebuild only when the checkpointer identity changes (it is created during lifespan startup).
- LangGraph: coordinator thread = `conversation_id`; sub-agent threads are user-scoped (`mail_reader_{user_id}`, etc.). State updates use `Command(update=...)`. HITL via `HumanInTheLoopMiddleware(interrupt_on={"send_email": ...})`; resume via `Command(resume={"decisions": [...]})`.
- Uniform error shape `{"error": <ClassName>, "detail": ...}` from `main.py` global handlers.
- SSE framing: `text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `data: {json}\n\n`.
- Notifications are dual-path: persisted `Notification` rows (list/read API) + in-memory queue broadcast (live SSE).
- Google OAuth tokens are Fernet-encrypted at rest in the `users` table.

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
- Use `get_valid_access_token(user_id, db)` to always obtain a non-expired Gmail access token (it auto-refreshes).

## Don't
- Do not move auth, Gmail, or orchestration logic into the Next.js frontend.
- Do not run `uv ...` or `ruff check .` — neither uv nor ruff is set up in this repo.
- Do not assume pytest is available — use stdlib `unittest`.
- Do not perform the Gmail send (non-idempotent side effect) before the LangGraph `interrupt()` resumes.
- Do not let sub-agents share the coordinator's conversation-scoped thread; use user-scoped thread IDs.
- Do not rely on `Base.metadata.create_all` as the schema source of truth in production — use Alembic migrations.

## When Stuck
- Verify exact env values in `backend/.env` before debugging auth/Gmail/DB failures (see [docs/environment.md](docs/environment.md) for the full list and the two-DB-URL distinction).
- For OpenRouter model issues, confirm the current model ID in `app/agents/llm.py`.
- Prefer the local LangChain/LangGraph skills first. If they leave uncertainty about current APIs, consult the LangChain docs MCP server at `https://docs.langchain.com/mcp`.

## Required Skills
- **Use `fastapi`** for API structure, dependency patterns, modern FastAPI conventions, and Pydantic usage.
- **Use `postgres-best-practices`** for schema design, indexing strategies, query optimization, migrations, and common pitfalls.
- **Use `langchain-fundamentals`** for agent creation, tool definitions, structured output, model integration, and orchestration patterns.
- **Use `langchain-middleware`** for human-in-the-loop approval flows, tool-call interception, and `Command(resume=...)` patterns.
- **Use `langchain-dependencies`** for package setup, provider package selection, and versioning.
- **Use `langgraph-fundamentals`** for graph structure, state schema design, `Command`/`Send` routing, and streaming modes.
- **Use `langgraph-human-in-the-loop`** for `interrupt()`/resume behavior, approval boundary design, and idempotency-before-interrupt rules.
- **Use `langgraph-persistence`** for checkpointing configuration, thread scoping, and resumable workflow behavior.
- **Use `langsmith-trace`** for tracing, trace inspection, and runtime debugging.

MCP server (fallback reference only, after the skills above): the LangChain docs MCP server at `https://docs.langchain.com/mcp`.

## Related Docs
- [docs/architecture.md](docs/architecture.md) — full backend architecture (routers, agents, services, models, flows, thread scoping).
- [docs/environment.md](docs/environment.md) — all env vars and the `DATABASE_URL` vs `DATABASE_URL_PSYCOPG` distinction.
- [../README.md](../README.md) — product purpose, status, API overview.
- [../IMPLEMENTATION_PLAN_V2.md](../IMPLEMENTATION_PLAN_V2.md) — original phased build plan.
- [../frontend/AGENTS.md](../frontend/AGENTS.md) — frontend contract (auth cookie, SSE event names, content blocks).
