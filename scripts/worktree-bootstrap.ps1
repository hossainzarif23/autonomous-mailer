# Bootstrap a new git worktree for a parallel coding session.
# Idempotent. Re-running on an existing worktree is safe.
#
# Usage: .\scripts\worktree-bootstrap.ps1 <branch> [-Reinstall] [-DryRun]
# Env overrides: $env:WT_BACKEND_PORT, $env:WT_FRONTEND_PORT, $env:WT_REPO_ROOT, $env:WT_SKIP_INSTALL, $env:WT_SKIP_CODEGRAPH, $env:WT_DIR

[CmdletBinding()]
param(
    [Parameter(Position=0)] [string]$Branch,
    [switch]$Reinstall,
    [switch]$DryRun,
    [switch]$Help
)

# Handle -Help before any mandatory-parameter check fires
if ($Help -or ($args -contains '-h' -or $args -contains '--help')) {
    Get-Content $PSCommandPath | Select-Object -First 7 | ForEach-Object { Write-Host $_ }
    exit 0
}
if (-not $Branch) { Err "usage: $($MyInvocation.MyCommand.Name) <branch> [-Reinstall] [-DryRun] [-Help]" }

$ErrorActionPreference = 'Stop'

function Log($msg)  { Write-Host "[bootstrap] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[bootstrap] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "[bootstrap] $msg" -ForegroundColor Red; exit 1 }

function Invoke-Step([string]$Description, [scriptblock]$Action) {
    if ($DryRun) {
        Write-Host "  [dry-run] $Description"
    } else {
        & $Action
    }
}

# PowerShell's `if (git ...)` evaluates on stdout, not exit code. For "does this ref exist"
# checks, always use this helper instead.
function Test-GitRef([string]$Ref) {
    git show-ref --verify --quiet $Ref | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# ---------- locate repo ----------
if ($env:WT_REPO_ROOT) { $RepoRoot = $env:WT_REPO_ROOT }
else {
    # Always anchor on the PRIMARY worktree (first entry in `git worktree list`),
    # not on whatever worktree the script was launched from. Otherwise an idempotent
    # re-run from inside an existing worktree would try to create a nested worktree.
    $RepoRoot = (git rev-parse --show-toplevel 2>$null)
    if ($RepoRoot) {
        $primaryWt = (git worktree list --porcelain | Select-String -Pattern '^worktree ' | Select-Object -First 1) -replace '^worktree ',''
        if ($primaryWt) {
            $primaryNorm  = ($primaryWt -replace '\\','/').TrimEnd('/')
            $currentNorm  = ($RepoRoot    -replace '\\','/').TrimEnd('/')
            if ($primaryNorm -ne $currentNorm) {
                Write-Verbose "anchoring on primary worktree $primaryWt (script was launched from $RepoRoot)"
                $RepoRoot = $primaryWt
            }
        }
    }
}
if (-not $RepoRoot) { Err "not inside a git repo" }
Set-Location $RepoRoot

$RepoName = Split-Path -Leaf $RepoRoot
$BranchSlug = $Branch -replace '/', '_'
$WtDir = if ($env:WT_DIR) { $env:WT_DIR } else { Join-Path $RepoRoot (Join-Path '.worktrees' $BranchSlug) }

Log "repo:     $RepoRoot"
Log "branch:   $Branch"
Log "worktree: $WtDir"

git check-ignore -q '.worktrees' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0 -and -not $env:WT_DIR) {
    Err ".worktrees/ is not ignored by git; add it to .gitignore before bootstrapping"
}

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
Log "default:  $DefaultBranch"

# ---------- resolve MAIN worktree path explicitly (F3) ----------
# Always read .env from main worktree, not from whatever worktree the script was launched in.
# Prefer the worktree attached to the default branch; fall back to the first entry
# in `git worktree list` (the first entry is always the primary worktree).
$MainWtPath = $null
$firstWt = $null
$wtLines = git worktree list --porcelain
$candidate = $null
for ($i = 0; $i -lt $wtLines.Count; $i++) {
    if ($wtLines[$i] -match '^worktree (.+)$') {
        $candidate = $Matches[1]
        if (-not $firstWt) { $firstWt = $candidate }
    }
    if ($wtLines[$i] -match '^branch (.+)$' -and $Matches[1] -eq "refs/heads/$DefaultBranch") {
        $MainWtPath = $candidate
        break
    }
}
if (-not $MainWtPath) { $MainWtPath = $firstWt }
if (-not $MainWtPath) { Err "could not locate any worktree; refusing to bootstrap" }
Log "main wt:  $MainWtPath"

# ---------- ensure branch exists ----------
$localExists = Test-GitRef "refs/heads/$Branch"
$remoteExists = $false
if (-not $localExists) {
    $remoteOut = git ls-remote --heads origin $Branch 2>$null
    if ($remoteOut -and $remoteOut -match [regex]::Escape($Branch)) {
        $remoteExists = $true
        Log "branch exists on origin, fetching"
        try { Invoke-Step "git fetch origin $Branch" { git fetch origin $Branch 2>$null | Out-Null } } catch { Warn "fetch reported: $_" }
    }
}

# ---------- fetch latest default-branch tip (F18) ----------
# Don't fail if the remote default branch is missing — proceed with local refs
try {
    Invoke-Step "git fetch origin $DefaultBranch" { git fetch origin $DefaultBranch 2>$null | Out-Null }
} catch {
    Warn "fetch of $DefaultBranch from origin failed: $_; proceeding with local refs"
}

# ---------- create or attach worktree (F15: literal match, porcelain parser) ----------
$wtExists = Test-Path $WtDir
$ReuseExistingPorts = $false
# Normalize the path for comparison (git reports forward slashes; we may have backslashes)
$wtDirNormalized = ($WtDir -replace '\\', '/').TrimEnd('/')
$branchAttached = $false
$attachedPath = $null
$wtLinesAttached = git worktree list --porcelain
$candidateAttached = $null
for ($i = 0; $i -lt $wtLinesAttached.Count; $i++) {
    if ($wtLinesAttached[$i] -match '^worktree (.+)$') {
        $candidateAttached = $Matches[1]
    }
    if ($wtLinesAttached[$i] -match '^branch (.+)$' -and $Matches[1] -eq "refs/heads/$Branch") {
        $branchAttached = $true
        $attachedPath = $candidateAttached
        break
    }
}
if ($wtExists) {
    Warn "worktree path already exists: $WtDir"
    $registered = $false
    $wtLines2 = git worktree list --porcelain
    for ($i = 0; $i -lt $wtLines2.Count; $i++) {
        if ($wtLines2[$i] -match '^worktree (.+)$') {
            $listedPath = $Matches[1] -replace '\\', '/'
            if ($listedPath.TrimEnd('/') -eq $wtDirNormalized) {
                $registered = $true
                break
            }
        }
    }
    if ($registered) {
        Log "worktree already registered, reusing"
        $ReuseExistingPorts = $true
    } else {
        Err "path exists but is not a registered worktree; remove it or pick a different branch"
    }
} else {
    if ($branchAttached) {
        # If the branch is already attached somewhere, reuse that worktree rather than
        # creating a new one. This makes the script idempotent when re-run from inside
        # the worktree (or from the main worktree after a previous bootstrap).
        $attachedNormalized = ($attachedPath -replace '\\', '/').TrimEnd('/')
        $wtNormalized      = ($WtDir        -replace '\\', '/').TrimEnd('/')
        if ($attachedNormalized -ne $wtNormalized) {
            Warn "branch $Branch is already attached at $attachedPath; using that worktree (WT_DIR=$WtDir ignored)"
            $WtDir = $attachedPath
        }
        Log "reusing worktree at $WtDir"
        $ReuseExistingPorts = $true
    } elseif ($localExists) {
        try { Invoke-Step "git worktree add $WtDir $Branch" { git worktree add $WtDir $Branch 2>&1 | Out-Null } } catch { Warn "worktree add reported: $_" }
    } elseif ($remoteExists) {
        Log "creating local branch from origin/$Branch"
        try { Invoke-Step "git worktree add $WtDir -b $Branch origin/$Branch" { git worktree add $WtDir -b $Branch "origin/$Branch" 2>&1 | Out-Null } } catch { Warn "worktree add reported: $_" }
    } else {
        # F9+F18: branch from origin/<default>
        $originDefault = "origin/$DefaultBranch"
        if (Test-GitRef "refs/remotes/$originDefault") {
            Log "creating new branch $Branch from $originDefault"
            try { Invoke-Step "git worktree add $WtDir -b $Branch $originDefault" { git worktree add $WtDir -b $Branch $originDefault 2>&1 | Out-Null } } catch { Warn "worktree add reported: $_" }
        } else {
            Warn "no $originDefault; falling back to local $DefaultBranch"
            Log "creating new branch $Branch from $DefaultBranch"
            try { Invoke-Step "git worktree add $WtDir -b $Branch $DefaultBranch" { git worktree add $WtDir -b $Branch $DefaultBranch 2>&1 | Out-Null } } catch { Warn "worktree add reported: $_" }
        }
    }
}

if ($DryRun -and -not (Test-Path $WtDir)) {
    Log "dry-run: worktree dir does not exist yet; skipping in-worktree steps"
    Write-Host ""
    Write-Host "  worktree:  $WtDir (planned)"
    Write-Host "  branch:    $Branch"
    Write-Host ""
    exit 0
}
Set-Location $WtDir

# ---------- copy/create .env files (F3: always prefer MAIN, fall back to examples) ----------
function Copy-Env($src, $fallback, $dst) {
    if ((Test-Path $dst) -and -not $Reinstall) {
        Log "env exists, skipping copy: $dst (use -Reinstall to overwrite)"
        return
    }
    $source = $null
    if (Test-Path $src) {
        $source = $src
    } elseif ($fallback -and (Test-Path $fallback)) {
        $source = $fallback
        Warn "no source env at $src; using example $fallback"
    }

    if ($source) {
        Invoke-Step "Copy-Item $source -> $dst" { Copy-Item $source $dst -Force }
        if (-not $DryRun) { Log "env created: $dst" }
    } else {
        Warn "no source env or example for $dst, skipping"
    }
}
Copy-Env (Join-Path $MainWtPath 'backend\.env')        'backend\.env.example'             'backend\.env'
Copy-Env (Join-Path $MainWtPath 'frontend\.env.local') 'frontend\.env.local.example'      'frontend\.env.local'

# ---------- assign ports (F14: hash-based) ----------
# Stable hash-based port per branch slug, with collision detection.
# Uses .NET's built-in SHA256, takes first 4 bytes interpreted as BIG-ENDIAN uint32
# (so the value is identical to the bash script's `16#${hex:0:8}`).
function Hash-To-Port($slug, [int]$base) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($slug)
    $sha   = [System.Security.Cryptography.SHA256]::Create()
    $hash  = $sha.ComputeHash($bytes)
    $sha.Dispose()
    # First 4 bytes as big-endian uint32 (matches `16#${hex:0:8}` in the bash script).
    $b0 = [uint32]$hash[0]  -shl 24
    $b1 = [uint32]$hash[1]  -shl 16
    $b2 = [uint32]$hash[2]  -shl 8
    $b3 = [uint32]$hash[3]
    $h32 = $b0 -bor $b1 -bor $b2 -bor $b3
    return $base + ($h32 % 50)
}

$existingApiPort = $null
$existingFrontendPort = $null
if (Test-Path 'backend\.env') {
    $line = Select-String -Path 'backend\.env' -Pattern '^API_PORT=' | Select-Object -First 1
    if ($line) { $existingApiPort = ($line -split '=', 2)[1].Trim() }
}
if (Test-Path 'frontend\.env.local') {
    $line = Select-String -Path 'frontend\.env.local' -Pattern '^PORT=' | Select-Object -First 1
    if ($line) { $existingFrontendPort = ($line -split '=', 2)[1].Trim() }
}

if ($env:WT_BACKEND_PORT)                    { $BackendPort  = [int]$env:WT_BACKEND_PORT }
elseif ($ReuseExistingPorts -and $existingApiPort) { $BackendPort  = [int]$existingApiPort; Log "reusing existing API_PORT=$BackendPort from .env" }
else                                         { $BackendPort  = Hash-To-Port $BranchSlug 8000 }
if ($env:WT_FRONTEND_PORT)                   { $FrontendPort = [int]$env:WT_FRONTEND_PORT }
elseif ($ReuseExistingPorts -and $existingFrontendPort) { $FrontendPort = [int]$existingFrontendPort; Log "reusing existing PORT=$FrontendPort from .env" }
else                                         { $FrontendPort = Hash-To-Port $BranchSlug 3000 }
Log "ports:    backend=$BackendPort  frontend=$FrontendPort"

# ---------- probe assigned ports (F17) ----------
function Test-Port-Bound([int]$port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
        return ($null -ne $conn)
    } catch {
        try {
            $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
            $listener.Start()
            $listener.Stop()
            return $false
        } catch { return $true }
    }
}
if (Test-Port-Bound $BackendPort)  { Warn "port $BackendPort (backend) is already bound; the dev server may fail to start" }
if (Test-Port-Bound $FrontendPort) { Warn "port $FrontendPort (frontend) is already bound; the dev server may fail to start" }

# patch .env files with assigned ports
function Patch-EnvVar($file, $key, $value) {
    if (-not (Test-Path $file)) { return }
    $content = Get-Content $file -Raw
    if ($content -match "(?m)^${key}=.*$") {
        $newContent = $content -replace "(?m)^${key}=.*$", "${key}=${value}"
        Invoke-Step "Set-Content $file (patch $key)" { Set-Content -Path $file -Value $newContent -NoNewline }
        if (-not $DryRun) { Log "patched ${key}=${value} in $file" }
    } else {
        Invoke-Step "Add-Content $file ($key)" { Add-Content -Path $file -Value "`n${key}=${value}`n" }
        if (-not $DryRun) { Log "appended ${key}=${value} to $file" }
    }
}
Patch-EnvVar 'backend\.env'        'API_PORT' $BackendPort
Patch-EnvVar 'backend\.env'        'APP_URL' "http://localhost:${BackendPort}"
Patch-EnvVar 'backend\.env'        'GOOGLE_REDIRECT_URI' "http://localhost:${BackendPort}/api/auth/callback"
Patch-EnvVar 'backend\.env'        'FRONTEND_URL' "http://localhost:${FrontendPort}"
Patch-EnvVar 'frontend\.env.local' 'PORT'     $FrontendPort
Patch-EnvVar 'frontend\.env.local' 'NEXT_PUBLIC_API_URL' "http://localhost:${BackendPort}/api"

# ---------- install deps ----------
if ($env:WT_SKIP_INSTALL -eq "1") {
    Warn "skipping installs (WT_SKIP_INSTALL=1)"
} else {
    $MainVenv = Join-Path $MainWtPath 'backend\venv'
    $WorktreeVenv = 'backend\venv'
    $venvExisted = (Test-Path $WorktreeVenv) -or (Test-Path -PathType Leaf $WorktreeVenv -ErrorAction SilentlyContinue)
    $venvIsLink = ($venvExisted -and (Get-Item $WorktreeVenv -ErrorAction SilentlyContinue).LinkType -eq 'SymbolicLink')

    if (Test-Path $MainVenv) {
        if (($venvExisted -or $venvIsLink) -and -not $Reinstall) {
            Log "backend venv link exists, skipping (use -Reinstall to force)"
        } else {
            if ($venvExisted -and -not $venvIsLink) {
                Invoke-Step "Remove-Item -Recurse $WorktreeVenv" { Remove-Item -Recurse -Force $WorktreeVenv }
            }
            Log "linking backend\venv -> $MainVenv (junction; works without elevation on Windows)"
            Invoke-Step "New-Item Junction $WorktreeVenv -> $MainVenv" {
                New-Item -ItemType Junction -Path $WorktreeVenv -Target $MainVenv | Out-Null
            }
        }
    } elseif (Test-Path 'backend\requirements.txt') {
        if (-not (Test-Path $WorktreeVenv) -or $Reinstall) {
            Log "creating backend\venv (no main venv to link)"
            Invoke-Step "python -m venv $WorktreeVenv" { python -m venv $WorktreeVenv }
            $logPath = Join-Path $WtDir '.wt-bootstrap-pip.log'
            Invoke-Step "pip install (log: $logPath)" {
                & "$WorktreeVenv\Scripts\python.exe" -m pip install --upgrade pip 2>&1 | Out-Null
                & "$WorktreeVenv\Scripts\pip.exe" install -r 'backend\requirements.txt' 2>&1 | Out-Null
            }
            if (-not $DryRun) { Log "backend deps installed" }
        }
    }
    if ((Test-Path 'frontend\package.json') -and ((-not (Test-Path 'frontend\node_modules')) -or $Reinstall)) {
        Log "running npm install in frontend/"
        $logPath = Join-Path $WtDir '.wt-bootstrap-npm.log'
        Invoke-Step "npm install (log: $logPath)" {
            Push-Location frontend
            npm install 2>&1 | Out-Null
            Pop-Location
        }
        if (-not $DryRun) { Log "frontend deps installed" }
    } elseif (Test-Path 'frontend\node_modules') {
        Log "frontend/node_modules exists, skipping (use -Reinstall to force)"
    }
}

# ---------- CodeGraph (F7) ----------
if ($env:WT_SKIP_CODEGRAPH -eq "1") {
    Warn "skipping CodeGraph setup (WT_SKIP_CODEGRAPH=1)"
} else {
    if (Test-Path '.codegraph') {
        Invoke-Step "Remove-Item -Recurse .codegraph" { Remove-Item -Recurse -Force '.codegraph' }
        if (-not $DryRun) { Log "removed inherited .codegraph/" }
    }
    if (Get-Command codegraph -ErrorAction SilentlyContinue) {
        Invoke-Step "codegraph init" { codegraph init | Out-Null }
        if (-not $DryRun) { Log "codegraph: initialized" }
    } else {
        Warn "codegraph CLI not found; run 'codegraph init' in the worktree when available"
    }
}

# ---------- DB connectivity check (F13) ----------
if ((Test-Path 'backend\.env') -and -not $DryRun) {
    $venvPy = 'backend\venv\Scripts\python.exe'
    $py = if (Test-Path $venvPy) { $venvPy } else { 'python' }
    # Write the check script to a temp file and run it with redirected output so
    # PowerShell does not treat python's stderr writes as terminating errors.
    $dbScript = @'
import os, sys
def load_env(path):
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass
load_env(os.path.join(os.getcwd(), "backend", ".env"))
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
'@
    $dbScriptPath = Join-Path $WtDir '.wt-db-check.py'
    $dbOutPath    = Join-Path $WtDir '.wt-db-check.out'
    $dbScript | Set-Content -Path $dbScriptPath -NoNewline
    # Run via cmd /c with explicit redirection so PowerShell's error stream is clean
    cmd /c "chcp 65001 >nul 2>&1 & `"$py`" `"$dbScriptPath`" 1> `"$dbOutPath`" 2>&1" | Out-Null
    $LASTEXITCODE = $LASTEXITCODE
    $dbOut = (Get-Content $dbOutPath -Raw -ErrorAction SilentlyContinue)
    Remove-Item -Force $dbScriptPath, $dbOutPath -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -eq 0) {
        Log "db:       ok ($($dbOut.Trim()))"
    } else {
        Warn "db:       unreachable - $($dbOut.Trim())"
        Warn "          the dev server may fail to start. Check DATABASE_URL_PSYCOPG in backend/.env"
    }
}

# ---------- smoke test after install (F12) ----------
# These are best-effort checks; failure does not abort the bootstrap. A failure
# usually means the dev environment is missing a config (no ESLint config, no
# venv python). The user can still start the dev server; they should see the
# log if they want to know more.
if (($env:WT_SKIP_INSTALL -ne "1") -and -not $DryRun) {
    $venvPy = 'backend\venv\Scripts\python.exe'
    if (Test-Path $venvPy -PathType Leaf) {
        $smokeLog = Join-Path $WtDir '.wt-smoke-backend.log'
        cmd /c "`"$venvPy`" -c `"import app.main`" 1> `"$smokeLog`" 2>&1" | Out-Null
        $rc = $LASTEXITCODE
        if ($rc -ne 0) {
            Warn "smoke:    backend import check failed (see $smokeLog) - dev server may still work"
        } else { Log "smoke:    backend import OK" }
    }
    if ((Test-Path 'frontend\node_modules') -and (Test-Path 'frontend\package.json')) {
        $smokeLog = Join-Path $WtDir '.wt-smoke-frontend.log'
        Push-Location frontend
        cmd /c "npm run lint 1> `"$smokeLog`" 2>&1" | Out-Null
        $rc = $LASTEXITCODE
        Pop-Location
        if ($rc -ne 0) {
            Warn "smoke:    frontend lint check failed (see $smokeLog) - often means no ESLint config"
        } else { Log "smoke:    frontend lint OK" }
    }
}

# ---------- summary ----------
if ($DryRun) { Log "DRY RUN - no changes made"; exit 0 }
Log "ready."
Write-Host ""
Write-Host "  worktree:  $WtDir"
Write-Host "  branch:    $Branch"
Write-Host "  backend:   http://localhost:$BackendPort"
Write-Host "  frontend:  http://localhost:$FrontendPort"
Write-Host ""
Write-Host "  IMPORTANT - use a separate browser profile (or incognito) per worktree."
Write-Host "  The auth cookie is scoped to localhost; a stale cookie from another worktree"
Write-Host "  can decode but the user record may not exist in this session's view."
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    cd $WtDir"
Write-Host "    Read backend/AGENTS.md and frontend/AGENTS.md for the exact dev-server commands."
Write-Host ""
