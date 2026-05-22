# ==============================================================
#  Whisper Transcriber - Safe Uninstall Script
#  (Does NOT remove Python or pip)
#  Run: powershell -ExecutionPolicy Bypass .\uninstall.ps1
# ==============================================================

$ErrorActionPreference = 'Continue'

function Write-Step { param($msg) Write-Host "" ; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "    OK   $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "    WARN $msg" -ForegroundColor Yellow }
function Write-Info { param($msg) Write-Host "    ...  $msg" -ForegroundColor Gray }

Write-Host ""
Write-Host "============================================" -ForegroundColor White
Write-Host "  Whisper Transcriber - Safe Uninstall     " -ForegroundColor White
Write-Host "============================================" -ForegroundColor White

# --------------------------------------------------------------
# 1. Detect Python (required, but NOT modified)
# --------------------------------------------------------------
Write-Step "Detecting Python (will NOT be modified)"

$pythonCmd = $null

foreach ($cmd in @('python', 'python3')) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = $cmd
            Write-OK "$ver"
            break
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Warn "Python not found - cannot uninstall packages automatically"
    exit 0
}

# --------------------------------------------------------------
# 2. Uninstall Python packages ONLY
# --------------------------------------------------------------
Write-Step "Removing installed Python packages"

$packages = @(
    'faster-whisper',
    'ctranslate2',
    'torch',
    'sounddevice',
    'soundfile',
    'pynput',
    'numpy'
)

foreach ($pkg in $packages) {
    Write-Info "Uninstalling $pkg..."
    & $pythonCmd -m pip uninstall -y $pkg

    if ($LASTEXITCODE -eq 0) {
        Write-OK "$pkg removed"
    } else {
        Write-Warn "$pkg not found (skipped)"
    }
}

# --------------------------------------------------------------
# 3. Clear pip cache (safe, optional cleanup)
# --------------------------------------------------------------
Write-Step "Clearing pip cache"

try {
    & $pythonCmd -m pip cache purge | Out-Null
    Write-OK "pip cache cleared"
} catch {
    Write-Warn "Could not clear pip cache"
}

# --------------------------------------------------------------
# 4. Remove transcripts folder (optional)
# --------------------------------------------------------------
Write-Step "Transcripts folder cleanup"

$transcriptDir = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'transcripts'

if (Test-Path $transcriptDir) {
    $confirm = Read-Host "Delete transcripts folder? (y/N)"

    if ($confirm -match '^(y|yes)$') {
        Remove-Item $transcriptDir -Recurse -Force
        Write-OK "Deleted transcripts folder"
    } else {
        Write-Info "Kept transcripts folder"
    }
} else {
    Write-Info "No transcripts folder found"
}

# --------------------------------------------------------------
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Uninstall complete (Python preserved)    " -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""