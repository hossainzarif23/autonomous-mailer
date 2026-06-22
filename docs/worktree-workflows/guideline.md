# Parallel Worktree Workflow

Run multiple coding sessions on this repo without trampling each other. One worktree per session, isolated working dir, shared infrastructure where it is safe.

## When to use

- Starting a new feature/fix session that should not touch `main` directly.
- Running two agents in parallel on different branches.
- Handing a branch off to another session (yours or another agent).

If you are doing a quick throwaway edit on `main`, do not bother — just work in the main worktree.

## TL;DR

```bash
# bootstrap a new session worktree
./scripts/worktree-bootstrap.sh feat/my-branch

# later, when PR is merged
./scripts/worktree-teardown.sh feat/my-branch --force
```

PowerShell equivalents: `.\scripts\worktree-bootstrap.ps1 feat/my-branch` and `.\scripts\worktree-teardown.ps1 feat/my-branch --force`.

## Core principle

Each session = one git worktree = one isolated working dir. The worktree owns its source files, its `node_modules` / `venv`, its build artifacts, and its dev server ports. The repo itself (`.git/`, the working tree) is shared only at the git level — file system state inside the worktree is fully isolated.

## Step-by-step: bootstrap

1. **Pick a branch name.** Convention: `<type>/<short-slug>` where type ∈ `feat | fix | chore | refactor | docs | test`. Example: `feat/chat-streaming`, `fix/oauth-redirect`.
2. **Run the bootstrap script.** `./scripts/worktree-bootstrap.sh <branch>` (or `.ps1` on Windows). The script:
   - runs `git worktree add .worktrees/<branch-slug> -b <branch> origin/<default-branch>` (or attaches to existing branch)
   - resolves the **main** worktree path explicitly and copies `.env` files from there (`backend/.env`, `frontend/.env.local`)
   - symlinks `backend/venv` to the main worktree's `backend/venv` (falls back to a fresh venv if missing)
   - runs `npm install` in `frontend/`
   - assigns unique dev-server ports via a stable hash of the branch slug (see Port Scheme), with collision detection
   - patches `API_PORT` in `backend/.env`, `PORT` and `NEXT_PUBLIC_API_URL` in `frontend/.env.local` (so the frontend talks to **this** worktree's backend, not the main one)
   - removes the inherited `.codegraph/` directory (the opencode plugin reindexes on first query)
   - probes DB connectivity and warns if unreachable
   - smoke-tests the install: `python -c "import app.main"` and `npm run lint`
   - prints a summary: worktree path, branch, ports, browser-profile warning, and pointers to the per-package AGENTS.md
3. **Verify.** Open the worktree, run `python -m compileall app` (backend) and `npm run lint` (frontend). Smoke-test the dev server boots.
4. **Work.** Commit on the new branch. Do not push to `main` directly from a worktree session.

Idempotency: re-running the script on an existing worktree is safe — it skips steps that are already done and reports status.

## Step-by-step: teardown

When the PR is merged (or you want to abandon the branch):

1. **Merge the PR first.** Worktree teardown deletes local state; once gone, the branch is also deleted, so make sure remote has the merge.
2. **Run teardown.** `./scripts/worktree-teardown.sh <branch> --force`. The script:
   - refuses if there are uncommitted changes unless `--force` is passed
   - refuses if the branch is not merged into `main` and `--force` is not passed
   - stops the dev server if it is running on the assigned ports
   - runs `git worktree remove --force <path>`
   - runs `git branch -D <branch>` (only if merged, or `--force`)
   - prunes `node_modules` / `venv` / build artifacts (already gone with the worktree dir, but verifies)
3. **Verify.** `git worktree list` should no longer show the removed path.

## Port scheme

Avoid port collisions when multiple sessions boot dev servers simultaneously.

Ports are derived from a stable hash of the branch slug:

- Backend: `8000 + (crc32(branch-slug) % 50)`
- Frontend: `3000 + (crc32(branch-slug) % 50)`

The bootstrap script auto-assigns the next available pair by counting current worktrees. Override with `WT_BACKEND_PORT=... WT_FRONTEND_PORT=... ./scripts/worktree-bootstrap.sh <branch>`.

This means the same branch always gets the same port pair across re-bootstraps (idempotent) and across team members (predictable). The bootstrap script also probes the assigned ports and warns if they are already bound. Override with `WT_BACKEND_PORT=... WT_FRONTEND_PORT=... ./scripts/worktree-bootstrap.sh <branch>`.

The port pair is written to the worktree's `backend/.env` (`API_PORT`) and `frontend/.env.local` (`PORT` and `NEXT_PUBLIC_API_URL`).

## Cookie / auth state

The auth cookie (`access_token`) is `httpOnly`, signed with `JWT_SECRET` from `backend/.env`, and scoped to `Domain=localhost`. That means:

- The same browser will send the cookie to **any** backend on `localhost:80xx`.
- If the cookie was issued by backend A (port 8000) but the browser now hits backend B (port 8001) for `/api/auth/me`, backend B will decode it (same `JWT_SECRET` because the `.env` is copied from main) and look up the `user_id`. The user record may or may not exist in B's database view.
- The same `JWT_SECRET` is also why two backends cannot issue distinguishable cookies.

**Workaround:** use a **separate browser profile** (or a private/incognito window) per worktree. Each profile keeps its own cookie jar. Do not share a browser across two active worktree sessions.

## Database

**Shared, single instance. No per-session isolation.**

This project is pre-MVP with no real users, so a single Postgres database is used by every session. The Alembic `alembic_version` row is shared — run migrations serially across sessions, not in parallel. If two sessions both run `alembic upgrade head` at the same time, the second will see "no new migrations" or a lock; both are safe (idempotent) but coordinate to avoid confusion.

LangGraph checkpoint tables are also shared. Conversation `thread_id`s are stable across sessions — see `backend/AGENTS.md` for thread-scoping rules.

When the product graduates to multi-user / production: revisit this. For now, simpler is correct.

## CodeGraph

`.codegraph/` holds a branch-aware index of the repo. Sharing it across worktrees returns stale symbol data after a branch switch.

**Policy:** re-index per worktree, no symlink. The bootstrap script removes the inherited `.codegraph/` directory from the new worktree. The opencode plugin (not a CLI) detects the missing index and reindexes on first query in the new session.

## What is shared vs per-worktree

| State                        | Shared | Per-worktree | Why                                         |
|------------------------------|--------|--------------|---------------------------------------------|
| Source files                 | no     | yes          | branch isolation                            |
| `.env`, `.env.local`         | copy   | yes          | may carry session-specific overrides        |
| `backend/venv`               | symlink | yes (shared via main) | venv contents are read-only in worktrees; main venv is the source of truth |
| `frontend/node_modules`      | no     | yes          | writable, large, version-pinned per Node    |
| Build artifacts (`.next/`, `__pycache__/`, `dist/`) | no | yes   | generated, ignored by git                  |
| `.codegraph/`                | no     | yes          | branch-aware index, must re-index           |
| `.git/`                      | yes    | no           | git worktree mechanism                      |
| Postgres DB                  | yes    | no           | pre-MVP, no isolation needed                |
| OAuth cookies / browser state| no     | yes          | per-session, never share across sessions    |
| LangSmith traces             | yes    | no           | trace by thread_id, not worktree            |

## Session-end protocol

Before stopping a session or handing off:

1. `git status` — leave the tree clean or make an intentional WIP commit.
2. WIP commit message format: `wip(<scope>): <what is half-done>`. Do not push WIP commits unless asked.
3. If you are pausing for the user, summarize: branch name, worktree path, ports, last commit SHA, what is left.
4. Do not merge your own PR if other sessions are active on overlapping paths — let the user merge.

## Coordination across sessions

Two sessions on the same repo can collide in three ways:

1. **File edits** — different worktrees, different branches, no collision possible at the FS level. Only collide if both push to the same target branch.
2. **Migrations** — shared DB, shared `alembic_version`. Coordinate: one session writes migrations, the other rebases and re-runs.
3. **Ports** — auto-assigned by script, collisions avoided by counting worktrees.

No other shared mutable state exists (no S3, no Redis, no external services in pre-MVP). If you add one, document it here.

## Troubleshooting

- **"branch already used by worktree"** — `git worktree list` to find the existing worktree. Re-run bootstrap against the existing worktree (it will detect and skip creation).
- **"port already in use"** — another process bound the port. Check `git worktree list` to see if a stale worktree is still holding it. `git worktree remove` the stale one or kill the process.
- **CodeGraph symbols look wrong** — index is stale. Open a query in the worktree; the opencode plugin detects the missing `.codegraph/` and rebuilds. To force a clean rebuild, delete `.codegraph/` in the worktree and run a query.
- **Dashboard flickers between "Loading your workspace" and the dashboard** — almost always a stale auth cookie from a different worktree in the same browser. Use a separate browser profile (or incognito) for each active worktree. See "Cookie / auth state" above.
- **`npm install` or `pip install` fails in new worktree** — check the source `.env` was copied correctly; some packages need env-driven config. Re-run the script with `--reinstall` (Bash) or `-Reinstall` (PowerShell) to wipe and reinstall.
- **Want to share `.env` across all worktrees literally** — symlink it instead of copying. Out of scope for the script, but `New-Item -ItemType SymbolicLink` or `ln -s` does it.