# ==============================================================
# Whisper Transcriber - Robust Installer (Final Version)
# ==============================================================

$ErrorActionPreference = "Stop"

# --------------------------------------------------------------
# Logging helpers (MUST be first)
# --------------------------------------------------------------
function Write-Step {
    param($msg)
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-OK {
    param($msg)
    Write-Host "    OK   $msg" -ForegroundColor Green
}

function Write-Warn {
    param($msg)
    Write-Host "    WARN $msg" -ForegroundColor Yellow
}

function Write-Info {
    param($msg)
    Write-Host "    ...  $msg" -ForegroundColor Gray
}

function Write-Fail {
    param($msg)
    Write-Host "    FAIL $msg" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor White
Write-Host " Whisper Transcriber Setup" -ForegroundColor White
Write-Host "============================================" -ForegroundColor White

# --------------------------------------------------------------
# 1. Detect latest installed Python (py launcher preferred)
# --------------------------------------------------------------
Write-Step "Detecting latest installed Python"

$python = $null
$pythonVersion = $null

try {
    $versions = & py -0p 2>$null

    if ($versions) {
        $bestVer = [version]"0.0.0"
        $bestPath = $null

        foreach ($line in $versions) {
            if ($line -match "-(\d+\.\d+).*?\s+(.*python\.exe)") {
                $ver = [version]$Matches[1]
                $path = $Matches[2]

                if ($ver -gt $bestVer) {
                    $bestVer = $ver
                    $bestPath = $path
                }
            }
        }

        if ($bestPath) {
            $python = $bestPath
            $pythonVersion = $bestVer
            Write-OK "Selected Python $pythonVersion"
        }
    }
} catch {
    Write-Warn "Python Launcher (py) not available"
}

# --------------------------------------------------------------
# Fallback to system python
# --------------------------------------------------------------
if (-not $python) {
    try {
        $v = & python --version 2>&1
        if ($v -match "Python (\d+\.\d+\.\d+)") {
            $python = "python"
            $pythonVersion = $Matches[1]
            Write-OK "Fallback Python $pythonVersion"
        }
    } catch {}
}

# --------------------------------------------------------------
# Install Python if missing
# --------------------------------------------------------------
if (-not $python) {
    Write-Warn "No Python found. Installing Python 3.13..."

    winget install Python.Python.3.13 `
        --silent `
        --accept-package-agreements `
        --accept-source-agreements

    $python = "python"
    Write-OK "Python installed"
}

Write-Info "Using Python: $python"

# --------------------------------------------------------------
# 2. Upgrade pip
# --------------------------------------------------------------
Write-Step "Upgrading pip"
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Fail "pip upgrade failed" }
Write-OK "pip upgraded"

# --------------------------------------------------------------
# 3. GPU detection + CUDA selection
# --------------------------------------------------------------
Write-Step "Detecting GPU + selecting PyTorch build"

$hasGPU = $false

try {
    $gpuName = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
    if ($gpuName) {
        $hasGPU = $true
        Write-OK "GPU detected: $gpuName"
    }
} catch {
    Write-Warn "No NVIDIA GPU detected"
}

# --------------------------------------------------------------
# CUDA options
# --------------------------------------------------------------
$cudaOptions = @(
    [pscustomobject]@{
        label = "CPU only"
        index = "https://download.pytorch.org/whl/cpu"
        note  = "Slow but most compatible"
    },
    [pscustomobject]@{
        label = "CUDA 12.1 (recommended for RTX 5060)"
        index = "https://download.pytorch.org/whl/cu121"
        note  = "Best stability + widest support"
    },
    [pscustomobject]@{
        label = "CUDA 12.4 (newer drivers)"
        index = "https://download.pytorch.org/whl/cu124"
        note  = "Newer optimizations"
    },
    [pscustomobject]@{
        label = "CUDA 12.8 (experimental)"
        index = "https://download.pytorch.org/whl/cu128"
        note  = "Bleeding edge, may break"
    }
)

Write-Host ""
Write-Host "Available PyTorch builds:" -ForegroundColor White
Write-Host ""

for ($i = 0; $i -lt $cudaOptions.Count; $i++) {
    Write-Host "[$i] $($cudaOptions[$i].label)" -ForegroundColor Cyan
    Write-Host "    $($cudaOptions[$i].note)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Recommendation: use option 1 (CUDA 12.1) unless you know better." -ForegroundColor Yellow
Write-Host ""

$selection = Read-Host "Select option [default: 1]"

if ([string]::IsNullOrWhiteSpace($selection)) {
    $selection = 1
}

if ($selection -notmatch '^\d+$' -or [int]$selection -ge $cudaOptions.Count) {
    Write-Warn "Invalid selection → defaulting to CUDA 12.1"
    $selection = 1
}

$cudaIndex = $cudaOptions[$selection].index
$cudaLabel = $cudaOptions[$selection].label

Write-OK "Selected: $cudaLabel"

# --------------------------------------------------------------
# 4. NumPy
# --------------------------------------------------------------
Write-Step "Installing NumPy"
& $python -m pip install numpy
if ($LASTEXITCODE -ne 0) { Write-Fail "NumPy install failed" }
Write-OK "NumPy installed"

# --------------------------------------------------------------
# 5. PyTorch
# --------------------------------------------------------------
Write-Step "Installing PyTorch (this may take a while)"
& $python -m pip install torch --index-url $cudaIndex
if ($LASTEXITCODE -ne 0) { Write-Fail "PyTorch install failed" }
Write-OK "PyTorch installed"

# --------------------------------------------------------------
# 6. Whisper dependencies
# --------------------------------------------------------------
Write-Step "Installing Whisper dependencies"

$packages = @(
    "ctranslate2",
    "faster-whisper",
    "sounddevice",
    "soundfile",
    "pynput"
)

foreach ($p in $packages) {
    Write-Info "Installing $p"
    & $python -m pip install $p
    if ($LASTEXITCODE -ne 0) { Write-Fail "$p install failed" }
    Write-OK "$p installed"
}

# --------------------------------------------------------------
# 7. Verification
# --------------------------------------------------------------
Write-Step "Verifying installation"

$verify = @'
import torch

print("Torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
else:
    print("Running on CPU")
'@

$tmp = "$env:TEMP\verify_whisper.py"
Set-Content -Path $tmp -Value $verify -Encoding UTF8
& $python $tmp
Remove-Item $tmp

# --------------------------------------------------------------
# 8. Create transcripts folder
# --------------------------------------------------------------
Write-Step "Creating transcripts folder"

$root = Split-Path -Parent $PSScriptRoot
$folder = Join-Path $root "transcripts"

if (-not (Test-Path $folder)) {
    New-Item -ItemType Directory -Path $folder | Out-Null
}

Write-OK "Created: $folder"

# --------------------------------------------------------------
# DONE
# --------------------------------------------------------------
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Setup complete!" -ForegroundColor Green
Write-Host " Run: python scripts\transcribe_tts.py" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""