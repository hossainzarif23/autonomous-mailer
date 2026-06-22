# Tear down a worktree session. Removes the worktree, deletes the local branch.
# Refuses if there are uncommitted changes or the branch is unmerged, unless -Force is passed.
#
# Usage: .\scripts\worktree-teardown.ps1 <branch> [-Force] [-DryRun] [-Help]

[CmdletBinding()]
param(
    [Parameter(Position=0)] [string]$Branch,
    [switch]$Force,
    [switch]$DryRun,
    [switch]$Help
)

# Handle -Help before any mandatory-parameter check fires
if ($Help -or ($args -contains '-h' -or $args -contains '--help')) {
    Get-Content $PSCommandPath | Select-Object -First 5 | ForEach-Object { Write-Host $_ }
    exit 0
}
if (-not $Branch) { Err "usage: $($MyInvocation.MyCommand.Name) <branch> [-Force] [-DryRun] [-Help]" }

$ErrorActionPreference = 'Stop'

function Log($msg)  { Write-Host "[teardown] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[teardown] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "[teardown] $msg" -ForegroundColor Red; exit 1 }

function Invoke-Step([string]$Description, [scriptblock]$Action) {
    if ($DryRun) { Write-Host "  [dry-run] $Description" }
    else { & $Action }
}

# PowerShell's `if (git ...)` evaluates on stdout, not exit code. For "does this ref exist"
# checks, always use this helper instead.
function Test-GitRef([string]$Ref) {
    git show-ref --verify --quiet $Ref | Out-Null
    return ($LASTEXITCODE -eq 0)
}

if ($env:WT_REPO_ROOT) { $RepoRoot = $env:WT_REPO_ROOT }
else {
    # Anchor on the primary worktree so the script works from anywhere in the repo
    $RepoRoot = (git rev-parse --show-toplevel 2>$null)
    if ($RepoRoot) {
        $primaryWt = (git worktree list --porcelain | Select-String -Pattern '^worktree ' | Select-Object -First 1) -replace '^worktree ',''
        if ($primaryWt) {
            $primaryNorm = ($primaryWt -replace '\\','/').TrimEnd('/')
            $currentNorm = ($RepoRoot    -replace '\\','/').TrimEnd('/')
            if ($primaryNorm -ne $currentNorm) { $RepoRoot = $primaryWt }
        }
    }
}
if (-not $RepoRoot) { Err "not inside a git repo" }
Set-Location $RepoRoot

# ---------- discover default branch (F10) ----------
$DefaultBranch = $null
try {
    $originHead = git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>$null
    if ($originHead) { $DefaultBranch = $originHead -replace '^origin/', '' }
} catch {}
if (-not $DefaultBranch) {
    if (Test-GitRef 'refs/heads/main')   { $DefaultBranch = 'main' }
    elseif (Test-GitRef 'refs/heads/master') { $DefaultBranch = 'master' }
    else { $DefaultBranch = (git rev-parse --abbrev-ref HEAD) }
}

# ---------- find worktree path ----------
$WtPath = $null
$lines = git worktree list --porcelain
$candidate = $null
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^worktree (.+)$') { $candidate = $Matches[1] }
    if ($lines[$i] -match ('^branch refs/heads/' + [regex]::Escape($Branch) + '$')) {
        $WtPath = $candidate
        break
    }
}
if (-not $WtPath) { Err "no worktree found for branch $Branch" }
Log "worktree: $WtPath"

# ---------- safety: uncommitted changes ----------
if (Test-Path $WtPath) {
    Push-Location $WtPath
    $status = git status --porcelain
    # F28: name the variable for what it actually means
    $hasChanges = ($LASTEXITCODE -eq 0) -and ($null -ne $status) -and ($status.Count -gt 0)
    if ($hasChanges) {
        if (-not $Force) {
            # F16: list every untracked path in the error
            $untracked = git ls-files --others --exclude-standard
            $list = ($untracked | ForEach-Object { "    $_" }) -join "`n"
            Pop-Location
            Err "uncommitted/untracked changes in $WtPath. Files:`n$list`nCommit/stash/clean them or pass -Force"
        } else {
            Warn "uncommitted/untracked changes present, -Force set, proceeding"
        }
    }
    Pop-Location
}

# ---------- safety: branch merge status (F10) ----------
if (-not $Force) {
    $defaultRef = "refs/heads/$DefaultBranch"
    if (Test-GitRef $defaultRef) {
        $mergedList = git branch --merged $DefaultBranch 2>$null
        $isMerged = $false
        foreach ($line in $mergedList) {
            $trimmed = $line.Trim() -replace '^\*\s*', ''
            if ($trimmed -eq $Branch) { $isMerged = $true; break }
        }
        if (-not $isMerged) {
            Err "branch $Branch is not merged into $DefaultBranch; pass -Force to delete anyway"
        }
    } else {
        Warn "$DefaultBranch branch not found locally; skipping merge check"
    }
}

# ---------- try to stop dev server on assigned ports (F5) ----------
function Stop-Port([int]$port) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
        if ($conns) {
            $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($pid in $pids) {
                Log "stopping process on port $port (PID $pid)"
                Invoke-Step "Stop-Process -Id $pid -Force" { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }
            }
        }
    } catch {
        Warn "could not enumerate port $port via Get-NetTCPConnection: $_"
    }
}

if (Test-Path $WtPath) {
    foreach ($envfile in @('backend\.env', 'frontend\.env.local')) {
        $full = Join-Path $WtPath $envfile
        if (-not (Test-Path $full)) { continue }
        $line = Select-String -Path $full -Pattern '^(API_PORT|PORT)=' | Select-Object -First 1
        if ($line) {
            $port = ($line -split '=', 2)[1].Trim()
            if ($port -match '^\d+$') { Stop-Port ([int]$port) }
        }
    }
}

# ---------- remove worktree ----------
Log "removing worktree"
$removed = $false
if (-not $DryRun) {
    try {
        git worktree remove --force $WtPath 2>&1 | Out-Null
        $removed = ($LASTEXITCODE -eq 0)
    } catch {}
}
if (-not $DryRun -and -not $removed) {
    Warn "git worktree remove failed; removing dir manually"
    Remove-Item -Recurse -Force $WtPath
    git worktree prune | Out-Null
}
if ($DryRun) { Write-Host "  [dry-run] git worktree remove --force $WtPath" }

# ---------- delete branch ----------
$branchExists = Test-GitRef "refs/heads/$Branch"
if ($branchExists) {
    Log "deleting branch $Branch"
    Invoke-Step "git branch -D $Branch" { git branch -D $Branch | Out-Null }
} else {
    Log "branch $Branch already gone"
}

if ($DryRun) { Log "DRY RUN - no changes made"; exit 0 }
Log "done."
Write-Host "  verify: git worktree list  (should not show $WtPath)"
Write-Host "  verify: git branch        (should not show $Branch)"
