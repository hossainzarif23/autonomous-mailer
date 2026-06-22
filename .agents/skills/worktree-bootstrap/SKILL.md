---
name: worktree-bootstrap
description: Create or tear down an isolated git worktree session for parallel coding work on this repo. Use whenever the user mentions "new worktree", "create a worktree", "parallel session", "isolated branch", "branch session", "bootstrap a branch", "set up a new session", "spin up a dev env", "I need to work on X in isolation", "session for branch X", "open a sibling session", "parallel agent on this branch", "tear down worktree", "cleanup worktree", "remove worktree", "delete branch worktree", or asks to work on a feature/fix in isolation from the main checkout. Runs the project's bootstrap/teardown scripts which create the worktree at `.worktrees/<branch-slug>`, copy env files from the main worktree, symlink `backend/venv` to the main worktree's `backend/venv` (falls back to a fresh venv if the main one is missing), run `npm install`, assign stable hash-based dev-server ports, patch `NEXT_PUBLIC_API_URL` so the frontend talks to the right backend, probe port availability, smoke-test the install, and remove the inherited `.codegraph/` (the opencode plugin reindexes on first query) — or, on teardown, stop the dev server, remove the worktree, and delete the local branch with safety checks. Idempotent. Works on both Bash and PowerShell. Read docs/worktree-workflows/guideline.md first for full context on shared vs per-worktree state, port scheme, and coordination rules.
---

# Worktree Bootstrap

Isolate coding work into a git worktree so multiple sessions can run in parallel without colliding on files, dependencies, ports, or database state. The scripts in `scripts/` do the heavy lifting; this skill is the entry point that picks the right script, passes the right arguments, and verifies the result.

## When to use

- User says they want to start a new feature/fix session on a separate branch
- User says "parallel session", "isolated branch", "new worktree", "worktree for this branch"
- User wants to clean up after merging: "tear down worktree", "remove the session", "delete the branch worktree"
- A different coding agent (Claude, Cursor, Aider) is being started in a sibling window and needs the same environment

Do NOT use this skill for:
- Quick throwaway edits on `main` (just work in the main worktree)
- Branch management that does not involve worktrees (use plain `git` commands)

## Read first

1. `docs/worktree-workflows/guideline.md` — the full protocol. Covers what is shared vs per-worktree, port scheme, why `.codegraph/` is re-indexed, and the session-end WIP commit convention.
2. `git worktree list` — to see what already exists before creating another.
3. `git status` in the main worktree — to confirm clean state before branching off.

## Bootstrap workflow

Goal: turn a branch name into a fully working, isolated dev environment.

1. **Detect platform.** Bash on Unix/macOS/Git-Bash, PowerShell on Windows. Pick the script:
   - Bash: `./scripts/worktree-bootstrap.sh <branch>`
   - PowerShell: `.\scripts\worktree-bootstrap.ps1 <branch>`
2. **Confirm branch name with the user** if it is not already specified. Follow the project convention `<type>/<short-slug>` where type ∈ `feat | fix | chore | refactor | docs | test`. Example: `feat/chat-streaming`.
3. **Run the script.** It will:
   - create `<repo>/.worktrees/<branch-slug>/` as a new worktree attached to `<branch>` (or attach to an existing branch if it already exists). The new branch is forked from `origin/<default-branch>` so it always tracks the latest.
   - copy `backend/.env` and `frontend/.env.local` from the **main worktree** (not whatever worktree the script was launched in)
   - assign backend port and frontend port from a stable hash of the branch slug, with collision detection against currently-bound ports; reuse the existing port from `.env` if this worktree is being re-bootstrapped (idempotent)
   - patch `API_PORT` in `backend/.env`, `PORT` and `NEXT_PUBLIC_API_URL` in `frontend/.env.local`
   - symlink `backend/venv` to the main worktree's `backend/venv` (falls back to a fresh venv if the main one is missing)
   - run `npm install` in `frontend/`
   - run `codegraph reindex` (or print a manual fallback if the CLI is missing)
   - print a summary: worktree path, branch, assigned ports, and the commands to start the dev servers
   - remove the inherited `.codegraph/` directory (the opencode plugin reindexes on first query)
   - probe DB connectivity (warns if unreachable, does not fail)
   - smoke-test: `python -c "import app.main"` and `npm run lint`
   - print a summary: worktree path, branch, assigned ports, browser-profile warning, and pointers to the per-package AGENTS.md for the exact dev-server commands
   - run `npm install` in `frontend/`
   - run `codegraph reindex` (or print a manual fallback if the CLI is missing)
   - print a summary: worktree path, branch, assigned ports, and the commands to start the dev servers
4. **Verify the result.** From inside the new worktree:
   - `git worktree list` shows the new entry at `.worktrees/<branch-slug>`
   - `git status` in the main worktree is clean (`.worktrees/` is in `.gitignore`)
   - `git status` in the new worktree is clean
   - `backend/.env` contains the expected `API_PORT=...`
   - `frontend/.env.local` contains the expected `PORT=...` and `NEXT_PUBLIC_API_URL=http://localhost:<backend-port>/api`
   - `backend/venv` is a symlink/junction to the main venv; `frontend/node_modules/` exists
5. **Smoke-test** by starting the dev servers and hitting a health endpoint if one exists. Read `backend/AGENTS.md` and `frontend/AGENTS.md` for the exact dev-server commands.
6. **Report** to the user: worktree path, branch, ports, and "ready to work". Remind the user to use a separate browser profile (or incognito) per worktree to avoid cookie collisions.

### Idempotency

Re-running the bootstrap script on an existing worktree is safe. It detects the existing worktree, skips worktree creation, and only re-runs the steps that are missing or out of date. To force a clean re-install, pass `--reinstall` (Bash) or `-Reinstall` (PowerShell).

### Environment overrides

The scripts honor these env vars:
- `WT_BACKEND_PORT`, `WT_FRONTEND_PORT` — pin specific ports
- `WT_REPO_ROOT` — point at a different repo root (useful in CI or subshells)
- `WT_SKIP_INSTALL=1` — skip pip + npm (faster, for repos that just need env files)
- `WT_SKIP_CODEGRAPH=1` — skip the reindex step
- `WT_DIR` — override the worktree path (default: `../<repo>-<branch-slug>`)

## Teardown workflow

Goal: safely remove a worktree + its branch after the work is merged or abandoned.

1. **Confirm the PR has been merged** (or the user explicitly wants to abandon the work). Teardown deletes the local branch; once gone, the commits are only reachable from the remote.
2. **Detect platform** and pick the script:
   - Bash: `./scripts/worktree-teardown.sh <branch> --force`
   - PowerShell: `.\scripts\worktree-teardown.ps1 <branch> -Force`
3. **The script will refuse by default if:**
   - there are uncommitted or untracked changes in the worktree
   - the branch is not merged into `main` or `master`
4. **If refused, do not pass `--force` blindly.** Read the error, ask the user:
   - uncommitted changes → "I see uncommitted work. Want me to commit it as a WIP first, or pass --force to discard?"
   - unmerged branch → "Branch is not merged. Has the PR been merged remotely, or do you want to force-delete?"
5. **Run with `--force`** only after the user confirms.
6. **Verify** with `git worktree list` and `git branch` that the entries are gone.

## Coordination with other agents

This skill is designed so multiple coding agents (Claude Code, Cursor, Aider, opencode) can each invoke the bootstrap script and end up with isolated, non-conflicting environments. The script's only shared input is the git repo itself, and that is mediated by git worktrees.

If two agents try to bootstrap the same branch at the same time, the second will attach to the existing worktree (idempotent) and the first one's session is unaffected. This is safe.

If two agents try to bootstrap different branches at the same time, the second will pick the next port pair automatically. No coordination needed.

## What this skill does NOT do

- It does not create PRs, push branches, or merge to `main`. That is the user's call.
- It does not run migrations automatically. The DB and `alembic_version` row are shared across all worktrees; run `alembic upgrade head` manually in the worktree, and coordinate with other active sessions before running it.
- It does not manage OAuth cookies or browser profiles. Each agent's session must use its own browser profile (or incognito) — the auth cookie is scoped to `localhost`, so a stale cookie from another worktree can decode cryptographically but the user record may not exist in the current session's view.
- It does not delete remote branches. Run `git push origin --delete <branch>` separately if needed.

## Failure modes & recovery

| Symptom                                              | Cause                                  | Fix                                                                                  |
|------------------------------------------------------|----------------------------------------|--------------------------------------------------------------------------------------|
| `path exists but is not a registered worktree`       | leftover dir at target path            | `rm -rf` the dir, or pick a different branch                                         |
| `port already in use`                                | stale process from another worktree    | find via `git worktree list`, run teardown on the stale branch                       |
| CodeGraph symbols look wrong                         | index is stale                         | `codegraph reindex` in the worktree, or set `WT_SKIP_CODEGRAPH=1` and accept staleness |
| `npm install` / `pip install` fails in new worktree  | env file not copied or stale           | re-run with `--reinstall` (Bash) / `-Reinstall` (PowerShell)                          |
| `branch already used by worktree`                    | another worktree is on this branch     | `git worktree list` to find it; either reuse that worktree or pick a different branch |
| Teardown refuses: uncommitted changes                | real uncommitted work in the worktree  | commit as WIP (`wip(<scope>): ...`) or `--force` to discard                          |
| Teardown refuses: branch not merged                  | PR not merged yet                      | merge the PR, then re-run; or `--force` to abandon    