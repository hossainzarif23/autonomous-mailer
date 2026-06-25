---
name: worktree-bootstrap
description: Create or tear down an isolated git worktree session for parallel coding work on this repo. Use whenever the user mentions "new worktree", "create a worktree", "parallel session", "isolated branch", "branch session", "bootstrap a branch", "set up a new session", "spin up a dev env", "I need to work on X in isolation", "session for branch X", "open a sibling session", "parallel agent on this branch", "tear down worktree", "cleanup worktree", "remove worktree", "delete branch worktree", or asks to work on a feature/fix in isolation from the main checkout. Runs the project's bootstrap/teardown scripts which create the worktree at `.worktrees/<branch-slug>`, copy env files from the main worktree or env examples, link `backend/venv` to the main worktree's `backend/venv` when available, run `npm install`, assign stable hash-based dev-server ports, patch backend/frontend URL env vars, initialize CodeGraph, smoke-test the install, and safely remove registered `.worktrees/` worktrees on teardown. Idempotent. Works on both Bash and PowerShell. Read docs/worktree-workflows/guideline.md first for full context.
---

# Worktree Bootstrap

Isolate coding work into a git worktree so multiple sessions can run in parallel without colliding on files, dependencies, ports, or database state. This skill complements `superpowers:using-git-worktrees`: use that skill for isolation policy and this skill for this repo's concrete setup and teardown scripts.

## When to use

- User says they want to start a new feature/fix session on a separate branch.
- User says "parallel session", "isolated branch", "new worktree", "worktree for this branch".
- User wants to clean up after merging: "tear down worktree", "remove the session", "delete the branch worktree".
- A different coding agent is being started in a sibling window and needs the same environment.

Do not use this skill for quick throwaway edits on `main` or branch management that does not involve worktrees.

## Read first

1. `docs/worktree-workflows/guideline.md` for the full protocol.
2. `git worktree list` to see what already exists.
3. `git status` in the main worktree to confirm the baseline.

## Bootstrap workflow

Goal: turn a branch name into a working, isolated dev environment.

1. Detect platform:
   - Bash: `./scripts/worktree-bootstrap.sh <branch>`
   - PowerShell: `.\scripts\worktree-bootstrap.ps1 <branch>`
2. Confirm branch name with the user if it is not already specified. Follow `<type>/<short-slug>` where type is `feat`, `fix`, `chore`, `refactor`, `docs`, or `test`.
3. Run the script. It will:
   - verify `.worktrees/` is ignored when using the default project-local location.
   - create or reuse `<repo>/.worktrees/<branch-slug>/` attached to `<branch>`.
   - fork new branches from `origin/<default-branch>` when available.
   - copy `backend/.env` and `frontend/.env.local` from the main worktree, falling back to `backend/.env.example` and `frontend/.env.local.example`.
   - assign backend/frontend ports from a stable hash of the branch slug, with override env vars.
   - patch `API_PORT`, `APP_URL`, `GOOGLE_REDIRECT_URI`, and `FRONTEND_URL` in `backend/.env`.
   - patch `PORT` and `NEXT_PUBLIC_API_URL` in `frontend/.env.local`.
   - link `backend/venv` to the main worktree's `backend/venv`, or create a fresh venv if the main one is missing.
   - run `npm install` in `frontend/`.
   - remove stale inherited `.codegraph/` and run `codegraph init` unless `WT_SKIP_CODEGRAPH=1`.
   - probe DB connectivity and warn if unreachable.
   - smoke-test `python -c "import app.main"` and `npm run lint`.
4. Verify the result from inside the new worktree:
   - `git worktree list` shows the new entry under `.worktrees/`.
   - main and new worktree `git status` are clean aside from ignored env/dependency files.
   - `backend/.env` contains `API_PORT`, `APP_URL`, `GOOGLE_REDIRECT_URI`, and `FRONTEND_URL` for the assigned ports.
   - `frontend/.env.local` contains `PORT` and `NEXT_PUBLIC_API_URL`.
   - `backend/venv`, `frontend/node_modules/`, and `.codegraph/` exist unless their setup was explicitly skipped or unavailable.
5. Smoke-test the dev servers if needed. Use separate browser profiles or incognito windows per worktree because auth cookies are scoped to `localhost`.

## Environment overrides

- `WT_BACKEND_PORT`, `WT_FRONTEND_PORT`: pin specific ports.
- `WT_REPO_ROOT`: point at a specific repo root.
- `WT_SKIP_INSTALL=1`: skip backend/frontend dependency setup.
- `WT_SKIP_CODEGRAPH=1`: skip CodeGraph setup.
- `WT_DIR`: override the worktree path. The default is `<repo>/.worktrees/<branch-slug>`.

## Teardown workflow

Goal: safely remove a worktree and its local branch after the work is merged or explicitly abandoned.

1. Confirm the PR has been merged, or get explicit confirmation that the user wants to abandon the branch.
2. Run teardown without force first:
   - Bash: `./scripts/worktree-teardown.sh <branch>`
   - PowerShell: `.\scripts\worktree-teardown.ps1 <branch>`
3. The script refuses if:
   - there are uncommitted or untracked changes.
   - the branch is not merged into the default branch and force was not supplied.
   - the target is outside this repo's `.worktrees/` directory.
   - the target is the primary/default worktree.
4. Use `--force` / `-Force` only after explicit user confirmation to discard changes or abandon unmerged commits. Force does not bypass the `.worktrees/` path fence.
5. Dev servers are not stopped by default. Pass `--stop-servers` or `-StopServers` only when you want the script to stop processes that it can tie to the worktree path.
6. Verify with `git worktree list` and `git branch`.

## What this skill does not do

- It does not create PRs, push branches, merge to `main`, or delete remote branches.
- It does not run migrations automatically. The DB is shared across worktrees.
- It does not manage OAuth cookies or browser profiles.
- It does not manually delete arbitrary filesystem paths. Teardown is fenced to registered worktrees under this repo's `.worktrees/`.

## Failure modes and recovery

| Symptom | Cause | Fix |
|---|---|---|
| `path exists but is not a registered worktree` | leftover directory at target path | inspect the path manually; do not delete blindly |
| `port already in use` | another process is bound to the assigned port | stop the known process manually or choose override ports |
| CodeGraph symbols look wrong | stale index | delete `.codegraph/` in the worktree and run `codegraph init` |
| `npm install` / `pip install` fails | dependency or env issue | inspect the bootstrap logs, then re-run with `--reinstall` / `-Reinstall` |
| Teardown refuses uncommitted changes | real uncommitted work | commit, stash, or get explicit approval to force-discard |
| Teardown refuses unmerged branch | branch is not merged | merge first, or get explicit approval to abandon |
