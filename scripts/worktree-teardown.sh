#!/usr/bin/env bash
# Tear down a worktree session. Removes the worktree, deletes the local branch.
# Refuses if there are uncommitted changes or the branch is unmerged, unless --force is passed.
#
# Usage: ./scripts/worktree-teardown.sh <branch> [--force] [--dry-run]

set -euo pipefail

if [[ -t 1 ]]; then
  RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; NC='\033[0m'
else
  RED=''; GRN=''; YLW=''; NC=''
fi
log()  { printf "${GRN}[teardown]${NC} %s\n" "$*"; }
warn() { printf "${YLW}[teardown]${NC} %s\n" "$*" >&2; }
err()  { printf "${RED}[teardown]${NC} %s\n" "$*" >&2; }
die()  { err "$*"; exit 1; }

BRANCH="${1:-}"
FORCE=0
DRY_RUN=0
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force|-f) FORCE=1; shift ;;
    --dry-run)  DRY_RUN=1; shift ;;
    -h|--help)
      sed -n '2,5p' "$0"; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done
[[ -z "$BRANCH" ]] && die "usage: $0 <branch> [--force] [--dry-run]"

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf "  [dry-run] %s\n" "$*"
  else
    eval "$@"
  fi
}

REPO_ROOT="${WT_REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || true)}"
[[ -z "$REPO_ROOT" ]] && die "not inside a git repo"
# Anchor on the primary worktree so the script works from anywhere in the repo
if [[ -z "${WT_REPO_ROOT:-}" ]]; then
  PRIMARY_WT="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1 || true)"
  if [[ -n "$PRIMARY_WT" && "$PRIMARY_WT" != "$REPO_ROOT" ]]; then
    REPO_ROOT="$PRIMARY_WT"
  fi
fi
cd "$REPO_ROOT"

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

# ---------- find worktree path ----------
# Note: worktree paths may contain spaces, so we read each line verbatim
# rather than relying on awk's whitespace field-splitting.
WT_PATH=""
current=""
while IFS= read -r line; do
  case "$line" in
    "worktree "*) current="${line#worktree }" ;;
    "branch "*)
      ref="${line#branch }"
      if [[ "$ref" == "refs/heads/$BRANCH" ]]; then
        WT_PATH="$current"
        break
      fi
      ;;
  esac
done < <(git worktree list --porcelain)
[[ -z "$WT_PATH" ]] && die "no worktree found for branch $BRANCH"
log "worktree: $WT_PATH"

# ---------- safety: uncommitted changes ----------
if [[ -d "$WT_PATH" ]]; then
  pushd "$WT_PATH" >/dev/null
  if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet HEAD 2>/dev/null; then
    if [[ $FORCE -eq 0 ]]; then
      die "uncommitted changes in $WT_PATH; commit/stash them or pass --force"
    else
      warn "uncommitted changes present, --force set, proceeding"
    fi
  fi
  # F16: list all untracked paths in the error, not just the first
  UNTRACKED="$(git ls-files --others --exclude-standard)"
  if [[ -n "$UNTRACKED" ]] && [[ $FORCE -eq 0 ]]; then
    die "untracked files in $WT_PATH; remove them or pass --force. Files: $(printf '\n    %s' $UNTRACKED)"
  fi
  popd >/dev/null
fi

# ---------- safety: branch merge status (F10) ----------
if [[ $FORCE -eq 0 ]]; then
  MERGED=0
  if git show-ref --verify --quiet "refs/heads/$DEFAULT_BRANCH"; then
    if git branch --merged "$DEFAULT_BRANCH" 2>/dev/null | grep -qw "$BRANCH"; then
      MERGED=1
    fi
  fi
  if [[ $MERGED -eq 0 ]]; then
    die "branch $BRANCH is not merged into $DEFAULT_BRANCH; pass --force to delete anyway"
  fi
fi

# ---------- try to stop dev server on assigned ports (F5: cross-platform) ----------
# Strategy: try ss, then netstat, then no-op with a clear warning.
stop_port() {
  local port="$1"
  local pids=""
  if command -v ss >/dev/null 2>&1; then
    # On Linux/Git-Bash with iproute2, ss gives us the owning pid via -p
    pids="$(ss -tlnp 2>/dev/null | awk -v p=":$port" '$4 ~ p { print }' | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)"
  fi
  if [[ -z "$pids" ]] && command -v netstat >/dev/null 2>&1; then
    # netstat -ano on Windows Git-Bash gives the PID in the last column
    pids="$(netstat -ano 2>/dev/null | awk -v p=":$port" '$2 ~ p { print $5 }' | grep -E '^[0-9]+$' | sort -u || true)"
  fi
  if [[ -n "$pids" ]]; then
    log "stopping processes on port $port (PIDs: $pids)"
    run "kill $pids 2>/dev/null || true"
    sleep 1
    run "kill -9 $pids 2>/dev/null || true"
  else
    warn "could not determine PID for port $port (no ss/netstat with -p support); you may need to stop the dev server manually"
  fi
}

if [[ -d "$WT_PATH" ]]; then
  for envfile in "$WT_PATH/backend/.env" "$WT_PATH/frontend/.env.local"; do
    [[ -f "$envfile" ]] || continue
    port=$(grep -E '^(API_PORT|PORT)=' "$envfile" 2>/dev/null | head -1 | cut -d= -f2 || true)
    if [[ -n "$port" ]]; then
      stop_port "$port"
    fi
  done
fi

# ---------- remove worktree ----------
log "removing worktree"
run "git worktree remove --force '$WT_PATH'" || {
  warn "git worktree remove failed; removing dir manually"
  run "rm -rf '$WT_PATH'"
  run "git worktree prune"
}

# ---------- delete branch ----------
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  log "deleting branch $BRANCH"
  run "git branch -D '$BRANCH'"
else
  log "branch $BRANCH already gone"
fi

[[ $DRY_RUN -eq 1 ]] && log "DRY RUN — no changes made" && exit 0
log "done."
printf "  verify: git worktree list  (should not show $WT_PATH)\n"
printf "  verify: git branch        (should not show $BRANCH)\n"
