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

## Superpowers Workflow
Use the original superpowers workflow for this development. Superpowers is a methodology, not a loose checklist. The agent must check for relevant skills before every task, and applicable skills are mandatory.

Follow this sequence for feature work:

1. **Brainstorm before code.** Use `brainstorming` when the request is still a rough idea or design problem. Ask targeted questions, explore alternatives, present the design in readable sections, and get human approval before implementation planning.
2. **Create an isolated workspace after design approval.** Use `civil-agent-worktree-bootstrap` together with `using-git-worktrees` before implementation work. For this repository, do not stop at bare `git worktree add`; bootstrap the new worktree with the project-local skill so `.env`, untracked `docs/` context, copied Kenmore artifacts, and QMD isolation are set up correctly before implementation begins.
3. **Write the implementation plan from the approved design.** Use `writing-plans`. Save the plan under `docs/superpowers/plans/`. The plan must break work into 2-5 minute tasks with exact files, concrete code or command snippets, and verification steps. Get human approval before executing the implementation plan.
4. **Execute the written plan with subagents.** Always use `subagent-driven-development` to execute implementation plans: dispatch a fresh subagent per task, then perform the required two-stage review for spec compliance and code quality. Do not silently fall back to inline execution.

   If subagents cannot be created or used, stop before implementation and report the exact blocker, such as missing subagent tooling, unavailable plugin/runtime support, failed subagent creation, or permission/configuration limits. Explain why that prevents following `subagent-driven-development`, then ask whether to proceed with `executing-plans` as an explicit fallback. Only use `executing-plans` after the user approves that fallback.

   Development subagent model policy for this work: use GPT-5.4-mini with medium reasoning for all subagents.

   After each subagent returns its final report, integrate only the necessary findings into the main thread and close the completed subagent thread immediately.
5. **Use TDD during implementation.** Use `test-driven-development` for behavior changes: write the failing test, see it fail, write the minimum implementation, see it pass, refactor, and commit. If production code was written before the test, delete or revert it and restart the red/green cycle.
6. **Review between tasks.** Under `subagent-driven-development`, every task must pass spec-compliance review before code-quality review. Open review issues block progress until fixed. Use `requesting-code-review` only when an additional human-facing or external review is needed.
7. **Finish the branch deliberately.** Use `finishing-a-development-branch` when planned tasks are complete. Run fresh verification, then present the options to merge, open a PR, keep the branch, or discard the worktree.

Use `systematic-debugging` for bugs and failing tests. Use `verification-before-completion` before any claim that work is complete, fixed, passing, or ready for PR. Evidence comes before status claims.

For behavior changes, use the Superpowers workflow. For narrow mechanical edits, apply the smallest safe change and still run relevant verification.

## Pointers
- Read `frontend/AGENTS.md` for frontend-local commands, UI constraints, and component guidance; `frontend/docs/architecture.md` and `frontend/docs/environment.md` for frontend detail.
- Read `backend/AGENTS.md` for backend-local commands, API constraints, and LangChain/LangGraph integration guidance; `backend/docs/architecture.md` and `backend/docs/environment.md` for backend detail.
- Read `README.md` for the full product, API, and env-var reference.
- Keep deep, evolving knowledge in the `docs/` directories rather than growing the AGENTS.md files.
