#!/usr/bin/env bash
# Bootstrap a new git worktree for a parallel coding session.
# Idempotent. Re-running on an existing worktree is safe.
#
# Usage: ./scripts/worktree-bootstrap.sh <branch> [--reinstall] [--dry-run]
# Env overrides: WT_BACKEND_PORT, WT_FRONTEND_PORT, WT_REPO_ROOT, WT_SKIP_INSTALL, WT_SKIP_CODEGRAPH, WT_DIR

set -euo pipefail

# ---------- colors (only when output is a TTY) ----------
if [[ -t 1 ]]; then
  RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; NC='\033[0m'
else
  RED=''; GRN=''; YLW=''; NC=''
fi
log()  { printf "${GRN}[bootstrap]${NC} %s\n" "$*"; }
warn() { printf "${YLW}[bootstrap]${NC} %s\n" "$*" >&2; }
err()  { printf "${RED}[bootstrap]${NC} %s\n" "$*" >&2; }
die()  { err "$*"; exit 1; }

# ---------- args ----------
BRANCH="${1:-}"
REINSTALL=0
DRY_RUN=0
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reinstall) REINSTALL=1; shift ;;
    --dry-run)   DRY_RUN=1; shift ;;
    -h|--help)
      sed -n '2,7p' "$0"; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done
[[ -z "$BRANCH" ]] && die "usage: $0 <branch> [--reinstall] [--dry-run]"

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf "  [dry-run] %s\n" "$*"
  else
    eval "$@"
  fi
}

# ---------- locate repo ----------
REPO_ROOT="${WT_REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || true)}"
[[ -z "$REPO_ROOT" ]] && die "not inside a git repo"
# Always anchor on the PRIMARY worktree (first entry in `git worktree list`),
# not on whatever worktree the script was launched from. Otherwise an idempotent
# re-run from inside an existing worktree would try to create a nested worktree.
if [[ -z "${WT_REPO_ROOT:-}" ]]; then
  PRIMARY_WT="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1 || true)"
  if [[ -n "$PRIMARY_WT" && "$PRIMARY_WT" != "$REPO_ROOT" ]]; then
    REPO_ROOT="$PRIMARY_WT"
  fi
fi
cd "$REPO_ROOT"

REPO_NAME="$(basename "$REPO_ROOT")"
BRANCH_SLUG="${BRANCH//\//_}"
WT_DIR_FROM_ENV="${WT_DIR:-}"
WT_DIR="${WT_DIR:-$REPO_ROOT/.worktrees/${BRANCH_SLUG}}"

log "repo:     $REPO_ROOT"
log "branch:   $BRANCH"
log "worktree: $WT_DIR"

if [[ -z "$WT_DIR_FROM_ENV" ]] && ! git check-ignore -q .worktrees 2>/dev/null; then
  die ".worktrees/ is not ignored by git; add it to .gitignore before bootstrapping"
fi

# ---------- discover default branch (F10) ----------
# `set +e` around the symbolic-ref because `pipefail` would otherwise abort
# the script when origin/HEAD is not configured.
set +e
DEFAULT_BRANCH="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
set -e
if [[ -z "$DEFAULT_BRANCH" ]]; then
  if git show-ref --verify --quiet refs/heads/main; then DEFAULT_BRANCH="main"
  elif git show-ref --verify --quiet refs/heads/master; then DEFAULT_BRANCH="master"
  else DEFAULT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"; fi
fi
log "default:  $DEFAULT_BRANCH"

# ---------- resolve MAIN worktree path explicitly (F3) ----------
# Always read .env from main worktree, not from whatever worktree the script was launched in.
# Prefer the worktree attached to the default branch; fall back to the first entry
# in `git worktree list` (the first entry is always the primary worktree).
# Note: worktree paths may contain spaces, so we capture the rest of the line verbatim
# (after the "worktree " / "branch " prefix) rather than using awk's field-splitting.
MAIN_WT_PATH="$(
  first=""
  current=""
  matched=""
  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        current="${line#worktree }"
        if [[ -z "$first" ]]; then first="$current"; fi
        ;;
      "branch "*)
        ref="${line#branch }"
        if [[ -n "$DEFAULT_BRANCH" && "$ref" == "refs/heads/$DEFAULT_BRANCH" ]]; then
          matched="$current"
          break
        fi
        ;;
    esac
  done < <(git worktree list --porcelain)
  if [[ -n "$matched" ]]; then echo "$matched"
  elif [[ -n "$first" ]]; then echo "$first"
  fi
)"
[[ -z "$MAIN_WT_PATH" ]] && die "could not locate any worktree; refusing to bootstrap"
log "main wt:  $MAIN_WT_PATH"

# ---------- ensure branch exists ----------
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  log "branch exists locally"
elif git ls-remote --heads origin "$BRANCH" 2>/dev/null | grep -q "$BRANCH"; then
  log "branch exists on origin, fetching"
  run "git fetch origin '$BRANCH'" || warn "fetch failed; will create local branch"
fi

# ---------- fetch latest default-branch tip (F18) ----------
run "git fetch origin '$DEFAULT_BRANCH'" || warn "fetch of $DEFAULT_BRANCH failed; proceeding with local refs"

# ---------- create or attach worktree ----------
WT_EXISTS=0
REUSE_EXISTING_PORTS=0
if [[ -d "$WT_DIR" ]]; then
  WT_EXISTS=1
  warn "worktree path already exists: $WT_DIR"
  # Detect if already a registered worktree (porcelain parser — F8)
  REGISTERED=0
  while IFS= read -r line; do
    if [[ "$line" == "worktree "* ]]; then
      [[ "${line#worktree }" == "$WT_DIR" ]] && REGISTERED=1
    fi
  done < <(git worktree list --porcelain)
  if [[ $REGISTERED -eq 1 ]]; then
    log "worktree already registered, reusing"
    REUSE_EXISTING_PORTS=1
  else
    die "path exists but is not a registered worktree; remove it or pick a different branch"
  fi
fi

if [[ $WT_EXISTS -eq 0 ]]; then
  # Check if branch is already attached somewhere (porcelain parser — F8)
  BRANCH_ATTACHED_PATH=""
  current=""
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) current="${line#worktree }" ;;
      "branch "*)
        ref="${line#branch }"
        if [[ "$ref" == "refs/heads/$BRANCH" ]]; then
          BRANCH_ATTACHED_PATH="$current"
          break
        fi
        ;;
    esac
  done < <(git worktree list --porcelain)
  if [[ -n "$BRANCH_ATTACHED_PATH" ]]; then
    # If the branch is already attached somewhere, reuse that worktree rather than
    # creating a new one. This makes the script idempotent when re-run from inside
    # the worktree (or from the main worktree after a previous bootstrap).
    if [[ "$BRANCH_ATTACHED_PATH" != "$WT_DIR" ]]; then
      warn "branch $BRANCH is already attached at $BRANCH_ATTACHED_PATH; using that worktree (WT_DIR=$WT_DIR ignored)"
      WT_DIR="$BRANCH_ATTACHED_PATH"
    fi
    log "reusing worktree at $WT_DIR"
    REUSE_EXISTING_PORTS=1
  elif git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    run "git worktree add '$WT_DIR' '$BRANCH'"
  elif git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    log "creating local branch from origin/$BRANCH"
    run "git worktree add '$WT_DIR' -b '$BRANCH' 'origin/$BRANCH'"
  else
    # F9: branch from origin/<default>, not from wherever the script was run
    if git show-ref --verify --quiet "refs/remotes/origin/$DEFAULT_BRANCH"; then
      log "creating new branch $BRANCH from origin/$DEFAULT_BRANCH"
      run "git worktree add '$WT_DIR' -b '$BRANCH' 'origin/$DEFAULT_BRANCH'"
    else
      warn "no origin/$DEFAULT_BRANCH; falling back to local $DEFAULT_BRANCH"
      log "creating new branch $BRANCH from $DEFAULT_BRANCH"
      run "git worktree add '$WT_DIR' -b '$BRANCH' '$DEFAULT_BRANCH'"
    fi
  fi
fi

# Skip the in-worktree steps during dry-run (the worktree dir does not exist yet)
if [[ $DRY_RUN -eq 1 && ! -d "$WT_DIR" ]]; then
  log "dry-run: worktree dir does not exist yet; skipping in-worktree steps"
  exit 0
fi
cd "$WT_DIR" || die "could not cd into $WT_DIR"

# ---------- copy/create .env files (F3: always prefer MAIN, fall back to examples) ----------
copy_env() {
  local src="$1" fallback="$2" dst="$3"
  if [[ -f "$dst" && $REINSTALL -eq 0 ]]; then
    log "env exists, skipping copy: $dst (use --reinstall to overwrite)"
    return
  fi
  local source=""
  if [[ -f "$src" ]]; then
    source="$src"
  elif [[ -n "$fallback" && -f "$fallback" ]]; then
    source="$fallback"
    warn "no source env at $src; using example $fallback"
  fi

  if [[ -n "$source" ]]; then
    run "cp '$source' '$dst'"
    [[ $DRY_RUN -eq 0 ]] && log "env created: $dst"
  else
    warn "no source env or example for $dst, skipping"
  fi
}
copy_env "$MAIN_WT_PATH/backend/.env"        "backend/.env.example"        "backend/.env"
copy_env "$MAIN_WT_PATH/frontend/.env.local" "frontend/.env.local.example" "frontend/.env.local"

# ---------- assign ports (F14: hash-based) ----------
# Stable hash-based port per branch slug, with collision detection.
# SHA256 is available on every Unix and on Git-Bash. Take the first 4 bytes
# as a uint32, mod 50, add the base. This is identical across platforms.
hash_to_port() {
  local slug="$1" base="$2"
  local hex
  hex="$(printf '%s' "$slug" | sha256sum | cut -d' ' -f1)"
  # First 4 bytes = first 8 hex chars
  local h32
  h32="$((16#${hex:0:8}))"
  echo $(( base + (h32 % 50) ))
}

# Read existing port from .env if this worktree is being re-bootstrapped (idempotent)
EXISTING_API_PORT=""
EXISTING_FRONTEND_PORT=""
if [[ -f "backend/.env" ]]; then
  EXISTING_API_PORT="$(grep -E '^API_PORT=' "backend/.env" 2>/dev/null | head -1 | cut -d= -f2 || true)"
fi
if [[ -f "frontend/.env.local" ]]; then
  EXISTING_FRONTEND_PORT="$(grep -E '^PORT=' "frontend/.env.local" 2>/dev/null | head -1 | cut -d= -f2 || true)"
fi

if [[ -n "${WT_BACKEND_PORT:-}" ]]; then
  BACKEND_PORT="$WT_BACKEND_PORT"
elif [[ $REUSE_EXISTING_PORTS -eq 1 && -n "$EXISTING_API_PORT" ]]; then
  BACKEND_PORT="$EXISTING_API_PORT"
  log "reusing existing API_PORT=$BACKEND_PORT from .env"
else
  BACKEND_PORT="$(hash_to_port "$BRANCH_SLUG" 8000)"
fi
if [[ -n "${WT_FRONTEND_PORT:-}" ]]; then
  FRONTEND_PORT="$WT_FRONTEND_PORT"
elif [[ $REUSE_EXISTING_PORTS -eq 1 && -n "$EXISTING_FRONTEND_PORT" ]]; then
  FRONTEND_PORT="$EXISTING_FRONTEND_PORT"
  log "reusing existing PORT=$FRONTEND_PORT from .env"
else
  FRONTEND_PORT="$(hash_to_port "$BRANCH_SLUG" 3000)"
fi
log "ports:    backend=$BACKEND_PORT  frontend=$FRONTEND_PORT"

# ---------- probe assigned ports (F17) ----------
probe_port() {
  local port="$1" name="$2"
  if command -v ss >/dev/null 2>&1; then
    if ss -tln 2>/dev/null | grep -qE ":${port}\b"; then
      warn "port $port ($name) is already bound; the dev server may fail to start"
      return 1
    fi
  elif command -v netstat >/dev/null 2>&1; then
    if netstat -an 2>/dev/null | grep -qE "[:.]${port} "; then
      warn "port $port ($name) is already bound; the dev server may fail to start"
      return 1
    fi
  fi
  return 0
}
probe_port "$BACKEND_PORT"  "backend"  || true
probe_port "$FRONTEND_PORT" "frontend" || true

# patch .env files with assigned ports
patch_env_var() {
  local file="$1" key="$2" value="$3"
  [[ ! -f "$file" ]] && return
  if grep -qE "^${key}=" "$file"; then
    run "sed -i.bak -E 's|^${key}=.*|${key}=${value}|' '$file' && rm -f '$file.bak'"
    [[ $DRY_RUN -eq 0 ]] && log "patched ${key}=${value} in $file"
  else
    run "printf '\n%s=%s\n' '$key' '$value' >> '$file'"
    [[ $DRY_RUN -eq 0 ]] && log "appended ${key}=${value} to $file"
  fi
}
patch_env_var "backend/.env" "API_PORT" "$BACKEND_PORT"
patch_env_var "backend/.env" "APP_URL" "http://localhost:${BACKEND_PORT}"
patch_env_var "backend/.env" "GOOGLE_REDIRECT_URI" "http://localhost:${BACKEND_PORT}/api/auth/callback"
patch_env_var "backend/.env" "FRONTEND_URL" "http://localhost:${FRONTEND_PORT}"
patch_env_var "frontend/.env.local" "PORT" "$FRONTEND_PORT"

# F2: patch NEXT_PUBLIC_API_URL so frontend calls THIS backend, not the main worktree's
patch_env_var "frontend/.env.local" "NEXT_PUBLIC_API_URL" "http://localhost:${BACKEND_PORT}/api"

# ---------- install deps ----------
if [[ "${WT_SKIP_INSTALL:-0}" == "1" ]]; then
  warn "skipping installs (WT_SKIP_INSTALL=1)"
else
  # F6: prefer venv symlink to main, fall back to fresh venv.
  # The canonical venv location in this repo is `backend/venv/` (per backend/AGENTS.md),
  # so we link/work from that name in the worktree as well.
  MAIN_VENV="$MAIN_WT_PATH/backend/venv"
  WORKTREE_VENV="backend/venv"
  if [[ -d "$MAIN_VENV" ]]; then
    if [[ -e "$WORKTREE_VENV" || -L "$WORKTREE_VENV" ]] && [[ $REINSTALL -eq 0 ]]; then
      log "backend venv link exists, skipping (use --reinstall to force)"
    else
      if [[ -d "$WORKTREE_VENV" ]] && [[ ! -L "$WORKTREE_VENV" ]]; then
        run "rm -rf '$WORKTREE_VENV'"
      fi
      log "linking backend/venv -> $MAIN_VENV"
      run "ln -s '$MAIN_VENV' '$WORKTREE_VENV'"
    fi
  elif [[ -f "backend/requirements.txt" ]]; then
    if [[ ! -d "$WORKTREE_VENV" ]] || [[ $REINSTALL -eq 1 ]]; then
      log "creating backend/venv (no main venv to link)"
      run "python -m venv '$WORKTREE_VENV'"
      run "'$WORKTREE_VENV/bin/python' -m pip install --upgrade pip >> '.wt-bootstrap-pip.log' 2>&1"
      run "'$WORKTREE_VENV/bin/pip' install -r backend/requirements.txt >> '.wt-bootstrap-pip.log' 2>&1"
      [[ $DRY_RUN -eq 0 ]] && log "backend deps installed"
    fi
  fi
  if [[ -f "frontend/package.json" ]]; then
    if [[ ! -d "frontend/node_modules" ]] || [[ $REINSTALL -eq 1 ]]; then
      log "running npm install in frontend/"
      run "cd frontend && npm install"
      [[ $DRY_RUN -eq 0 ]] && log "frontend deps installed"
    else
      log "frontend/node_modules exists, skipping (use --reinstall to force)"
    fi
  fi
fi

# ---------- CodeGraph (F7) ----------
if [[ "${WT_SKIP_CODEGRAPH:-0}" == "1" ]]; then
  warn "skipping CodeGraph setup (WT_SKIP_CODEGRAPH=1)"
else
  if [[ -d ".codegraph" ]]; then
    run "rm -rf '.codegraph'"
    [[ $DRY_RUN -eq 0 ]] && log "removed inherited .codegraph/"
  fi
  if command -v codegraph >/dev/null 2>&1; then
    run "codegraph init >/dev/null"
    [[ $DRY_RUN -eq 0 ]] && log "codegraph: initialized"
  else
    warn "codegraph CLI not found; run 'codegraph init' in the worktree when available"
  fi
fi

# ---------- DB connectivity check (F13) ----------
if [[ -f "backend/.env" ]]; then
  set +e
  # Choose a python: prefer the linked/shared venv, else fall back to system python
  if [[ -x "backend/venv/bin/python" ]]; then
    DB_PY="backend/venv/bin/python"
  else
    set +e
    DB_PY="$(command -v python)"
    if [[ -z "$DB_PY" ]]; then
      DB_PY="$(command -v python3)"
    fi
    set -e
  fi
  if [[ -n "$DB_PY" ]]; then
    DB_CHECK_OUT="$(cd backend && "$DB_PY" -c '
import os, sys
def load_env(path):
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value.strip().strip(chr(34)).strip(chr(39)))
    except FileNotFoundError:
        pass
load_env(os.path.join(os.getcwd(), ".env"))
try:
    import psycopg
except ImportError:
    print("psycopg not installed; skipping DB check")
    sys.exit(0)
dsn = os.environ.get("DATABASE_URL_PSYCOPG") or os.environ.get("DATABASE_URL")
if not dsn:
    print("no DATABASE_URL_PSYCOPG/DATABASE_URL in env; skipping")
    sys.exit(0)
dsn = dsn.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")
try:
    with psycopg.connect(dsn, connect_timeout=5) as c:
        c.close()
    print("DB OK")
except Exception as e:
    print(f"DB UNREACHABLE: {e}")
    sys.exit(1)
' 2>&1)"
    DB_CHECK_RC=$?
    if [[ $DB_CHECK_RC -eq 0 ]]; then
      log "db:       ok ($DB_CHECK_OUT)"
    else
      warn "db:       unreachable - $DB_CHECK_OUT"
      warn "          the dev server may fail to start. Check DATABASE_URL_PSYCOPG in backend/.env"
    fi
  else
    warn "no python on PATH; skipping DB check"
  fi
  set -e
fi

# ---------- smoke test after install (F12) ----------
if [[ "${WT_SKIP_INSTALL:-0}" != "1" ]] && [[ $DRY_RUN -eq 0 ]]; then
  if [[ -d "backend/venv" || -L "backend/venv" ]]; then
    SMOKE_PY=""
    if [[ -x "backend/venv/bin/python" ]]; then
      SMOKE_PY="backend/venv/bin/python"
    else
      set +e
      SMOKE_PY="$(command -v python)"
      if [[ -z "$SMOKE_PY" ]]; then
        SMOKE_PY="$(command -v python3)"
      fi
      set -e
    fi
    if [[ -n "$SMOKE_PY" ]]; then
      set +e
      (cd backend && "$SMOKE_PY" -c "import app.main" 2>"$WT_DIR/.wt-smoke-backend.log")
      SMOKE_RC=$?
      set -e
      if [[ $SMOKE_RC -ne 0 ]]; then
        warn "smoke:    backend import check failed (see $WT_DIR/.wt-smoke-backend.log) - dev server may still work"
      else
        log "smoke:    backend import OK"
      fi
    fi
  fi
  if [[ -d "frontend/node_modules" ]] && [[ -f "frontend/package.json" ]]; then
    set +e
    (cd frontend && npm run lint >"$WT_DIR/.wt-smoke-frontend.log" 2>&1)
    SMOKE_RC=$?
    set -e
    if [[ $SMOKE_RC -ne 0 ]]; then
      warn "smoke:    frontend lint check failed (see $WT_DIR/.wt-smoke-frontend.log) - often means no ESLint config"
    else
      log "smoke:    frontend lint OK"
    fi
  fi
fi

# ---------- summary ----------
[[ $DRY_RUN -eq 1 ]] && log "DRY RUN — no changes made" && exit 0

log "ready."
printf "\n"
printf "  worktree:  %s\n" "$WT_DIR"
printf "  branch:    %s\n" "$BRANCH"
printf "  backend:   http://localhost:%s\n" "$BACKEND_PORT"
printf "  frontend:  http://localhost:%s\n" "$FRONTEND_PORT"
printf "\n"
printf "  %s\n" "IMPORTANT — use a separate browser profile (or incognito) per worktree."
printf "  %s\n" "The auth cookie is scoped to localhost; a stale cookie from another worktree"
printf "  %s\n" "can decode but the user record may not exist in this session's view."
printf "\n"
printf "  Next steps:\n"
printf "    cd %s\n" "$WT_DIR"
printf "    Read backend/AGENTS.md and frontend/AGENTS.md for the exact dev-server commands.\n"
printf "\n"
