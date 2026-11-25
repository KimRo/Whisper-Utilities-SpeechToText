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

# pyannote.audio 4.x (speaker labels) requires Python 3.11 or newer
if ($pythonVersion -and ([version]"$pythonVersion" -lt [version]"3.11")) {
    Write-Fail ("Python $pythonVersion is too old: Python 3.11 or newer is required " +
                "(pyannote.audio 4.x). Install a newer one with: winget install Python.Python.3.13 " +
                "and run the installer again.")
}

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
        label = "CUDA 12.6 (recommended)"
        index = "https://download.pytorch.org/whl/cu126"
        note  = "Widest GPU support. Needs a recent NVIDIA driver."
    },
    [pscustomobject]@{
        label = "CUDA 12.8"
        index = "https://download.pytorch.org/whl/cu128"
        note  = "For RTX 50-series (Blackwell) GPUs and newer"
    },
    [pscustomobject]@{
        label = "CUDA 13.0"
        index = "https://download.pytorch.org/whl/cu130"
        note  = "Newest drivers only; does not support older GPUs"
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
Write-Host "Recommendation: use option 1 (CUDA 12.6) unless you know better." -ForegroundColor Yellow
Write-Host ""

$selection = Read-Host "Select option [default: 1]"

if ([string]::IsNullOrWhiteSpace($selection)) {
    $selection = 1
}

if ($selection -notmatch '^\d+$' -or [int]$selection -ge $cudaOptions.Count) {
    Write-Warn "Invalid selection → defaulting to CUDA 12.6"
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
# torch and torchaudio are pinned to the same version: 2.11.0 is published on the
# CPU, cu126, cu128 and cu130 indexes. pyannote.audio 4.x needs torch >= 2.8.
$torchVersion = "2.11.0"

Write-Step "Installing PyTorch $torchVersion (this may take a while)"
& $python -m pip install "torch==$torchVersion" "torchaudio==$torchVersion" --index-url $cudaIndex
if ($LASTEXITCODE -ne 0) { Write-Fail "PyTorch install failed" }
Write-OK "PyTorch installed"

# Constraints file: stops later packages (pyannote.audio) from replacing this
# torch build with a newer CPU-only build from PyPI.
$constraints = Join-Path $env:TEMP "whisper_torch_constraints.txt"
$torchVer = (& $python -c "import torch; print(torch.__version__)").Trim()
$tavVer   = (& $python -c "import torchaudio; print(torchaudio.__version__)").Trim()
@("torch==$torchVer", "torchaudio==$tavVer") | Set-Content -Path $constraints -Encoding ascii

# --------------------------------------------------------------
# 6. Whisper dependencies
# --------------------------------------------------------------
Write-Step "Installing Whisper dependencies"

$packages = @(
    "av<19",                  # PyAV 19 removed an argument faster-whisper 1.2.1 still passes
    "ctranslate2",
    "faster-whisper",
    "sounddevice",
    "soundfile",
    "pynput",
    "PyAudioWPatch",
    "pystray",
    "pyannote.audio==4.1.1"   # speaker diarization (transcribe_speakers.py)
)

foreach ($p in $packages) {
    Write-Info "Installing $p"
    & $python -m pip install $p -c $constraints
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

# Every package the tools need (recording, transcription, speakers, live, tray) in one list
Write-Step "Checking that all packages are in place"
$check = Join-Path (Split-Path -Parent $PSScriptRoot) "requirements_check.py"
& $python $check
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Some packages are missing (see the list above). Run this installer again, or install them with the pip command shown."
}

# --------------------------------------------------------------
# DONE
# --------------------------------------------------------------
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Setup complete!" -ForegroundColor Green
Write-Host " Run: python scripts\transcribe_tts.py" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""