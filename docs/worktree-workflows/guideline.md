# Parallel Worktree Workflow

Run multiple coding sessions on this repo without trampling each other. One session means one registered git worktree under `.worktrees/`, with isolated source files, env files, frontend dependencies, dev-server ports, and CodeGraph index.

This repo's `worktree-bootstrap` skill complements `superpowers:using-git-worktrees`: use the Superpowers skill for isolation policy, then use these scripts for this project's concrete setup and teardown.

## Bootstrap

```bash
./scripts/worktree-bootstrap.sh feat/my-branch
```

PowerShell:

```powershell
.\scripts\worktree-bootstrap.ps1 feat/my-branch
```

The bootstrap script:

- verifies `.worktrees/` is ignored when using the default location.
- creates or reuses `.worktrees/<branch-slug>/`.
- branches from `origin/<default-branch>` when available.
- copies `backend/.env` and `frontend/.env.local` from the main worktree, falling back to `backend/.env.example` and `frontend/.env.local.example`.
- assigns stable hash-based backend/frontend ports.
- patches backend env: `API_PORT`, `APP_URL`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL`.
- patches frontend env: `PORT`, `NEXT_PUBLIC_API_URL`.
- links `backend/venv` to the main worktree's venv when available, or creates a fresh venv.
- runs `npm install` in `frontend/`.
- removes stale inherited `.codegraph/` and runs `codegraph init` unless `WT_SKIP_CODEGRAPH=1`.
- probes DB connectivity and runs smoke checks.

## Verification

After bootstrap, verify:

```bash
git worktree list
git status
```

Inside the new worktree, check:

- `backend/.env` has the assigned backend port and URL values.
- `frontend/.env.local` has the assigned frontend port and backend API URL.
- `backend/venv`, `frontend/node_modules/`, and `.codegraph/` exist unless explicitly skipped or unavailable.
- Backend compile and frontend lint/build checks are run as appropriate for the task.

Use a separate browser profile or incognito window per active worktree. Auth cookies are scoped to `localhost`, so sharing a browser across worktrees can send stale cookies to the wrong backend.

## Port Scheme

Ports are derived from a stable hash of the branch slug:

- Backend: `8000 + (sha256(branch-slug)[0:4] % 50)`
- Frontend: `3000 + (sha256(branch-slug)[0:4] % 50)`

Override with `WT_BACKEND_PORT` and `WT_FRONTEND_PORT`.

## Shared vs Per-Worktree State

| State | Shared | Per-worktree | Notes |
|---|---:|---:|---|
| Source files | no | yes | branch isolation |
| `backend/.env`, `frontend/.env.local` | copied | yes | patched per worktree |
| `backend/venv` | linked when possible | yes | main venv is source of truth |
| `frontend/node_modules` | no | yes | installed per worktree |
| `.codegraph/` | no | yes | initialized per worktree |
| `.git/` common data | yes | no | git worktree mechanism |
| Postgres DB | yes | no | coordinate migrations manually |
| Browser cookies | no | yes | use separate profiles |

## Teardown

Run teardown without force first:

```bash
./scripts/worktree-teardown.sh feat/my-branch
```

PowerShell:

```powershell
.\scripts\worktree-teardown.ps1 feat/my-branch
```

The teardown scripts are intentionally conservative:

- They refuse uncommitted or untracked changes unless `--force` / `-Force` is supplied.
- They refuse unmerged branches unless force is supplied.
- They refuse to remove the default branch.
- They refuse to remove the primary worktree.
- They refuse any target outside this repo's `.worktrees/` directory.
- They do not manually delete directories if `git worktree remove` fails.
- They do not stop dev servers by default.

Use force only after explicit confirmation that unmerged commits or local changes may be discarded:

```bash
./scripts/worktree-teardown.sh feat/my-branch --force
```

PowerShell:

```powershell
.\scripts\worktree-teardown.ps1 feat/my-branch -Force
```

To stop dev servers, opt in:

```bash
./scripts/worktree-teardown.sh feat/my-branch --stop-servers
```

PowerShell:

```powershell
.\scripts\worktree-teardown.ps1 feat/my-branch -StopServers
```

Even with stop-server mode enabled, the script only stops a process when its command or executable path can be tied to the worktree path.

## Session-End Protocol

Before pausing, handing off, or tearing down:

1. Run `git status`.
2. Leave the tree clean, or make an intentional WIP commit with `wip(<scope>): <what is half-done>`.
3. Summarize branch name, worktree path, ports, last commit SHA, and remaining work.
4. Coordinate migrations because all worktrees share one database.

## Troubleshooting

- `path exists but is not a registered worktree`: inspect the leftover directory manually; do not delete it blindly.
- `port already in use`: stop the known process manually or choose override ports.
- CodeGraph symbols look stale: delete `.codegraph/` in the worktree and run `codegraph init`.
- OAuth redirects to the wrong port: check `backend/.env` values for `GOOGLE_REDIRECT_URI` and `FRONTEND_URL`.
- Frontend calls the wrong backend: check `frontend/.env.local` for `NEXT_PUBLIC_API_URL`.
