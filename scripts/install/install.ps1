# ==============================================================
#  Whisper Transcriber - Install Script
#  Run: powershell -ExecutionPolicy Bypass .\install.ps1
# ==============================================================

$ErrorActionPreference = 'Stop'

function Write-Step { param($msg) Write-Host "" ; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "    OK   $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "    WARN $msg" -ForegroundColor Yellow }
function Write-Info { param($msg) Write-Host "    ...  $msg" -ForegroundColor Gray }
function Write-Fail {
    param($msg)
    Write-Host "    FAIL $msg" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor White
Write-Host "  Whisper Transcriber - Dependency Setup   " -ForegroundColor White
Write-Host "============================================" -ForegroundColor White

# --------------------------------------------------------------
# 1. Python
# --------------------------------------------------------------
Write-Step "Checking Python"

$pythonCmd = $null
foreach ($cmd in @('python', 'python3')) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match 'Python 3\.(\d+)') {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $pythonCmd = $cmd
                Write-OK "$ver"
                break
            } else {
                Write-Warn "$ver found but 3.10+ is required"
            }
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Info 'Python 3.10+ not found - installing via winget...'
    try {
        winget install --id Python.Python.3.13 --source winget --silent --accept-package-agreements --accept-source-agreements
        $machinePath = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
        $userPath    = [System.Environment]::GetEnvironmentVariable('Path', 'User')
        $env:Path    = $machinePath + ';' + $userPath
        $pythonCmd   = 'python'
        Write-OK 'Python 3.13 installed'
    } catch {
        Write-Fail 'Could not install Python. Download from https://python.org and re-run this script.'
    }
}

# --------------------------------------------------------------
# 2. pip
# --------------------------------------------------------------
Write-Step "Upgrading pip"
& $pythonCmd -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { Write-Fail "pip upgrade failed (exit code $LASTEXITCODE)" }
$pipVer = & $pythonCmd -m pip --version
Write-OK "$pipVer"

# --------------------------------------------------------------
# 3. Detect NVIDIA GPU and pick PyTorch CUDA variant
# --------------------------------------------------------------
Write-Step "Checking NVIDIA GPU"

$cudaIndex = 'https://download.pytorch.org/whl/cpu'
$cudaLabel = 'CPU (no GPU detected)'

try {
    $smi = & nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>&1
    if ($smi -match '^(.+),\s*([\d\.]+)') {
        $gpuName     = $Matches[1].Trim()
        $driverVer   = $Matches[2].Trim()
        $driverMajor = [int]($driverVer.Split('.')[0])

        Write-OK "GPU    : $gpuName"
        Write-OK "Driver : $driverVer"

        if ($driverMajor -ge 551) {
            $cudaIndex = 'https://download.pytorch.org/whl/cu124'
            $cudaLabel = 'CUDA 12.4'
            Write-OK 'PyTorch variant: CUDA 12.4'
        } elseif ($driverMajor -ge 528) {
            $cudaIndex = 'https://download.pytorch.org/whl/cu121'
            $cudaLabel = 'CUDA 12.1'
            Write-OK 'PyTorch variant: CUDA 12.1'
        } elseif ($driverMajor -ge 452) {
            $cudaIndex = 'https://download.pytorch.org/whl/cu118'
            $cudaLabel = 'CUDA 11.8'
            Write-Warn 'CUDA 11.8 selected - update drivers for CUDA 12 support'
        } else {
            Write-Warn 'Driver too old for CUDA PyTorch - falling back to CPU'
        }
    }
} catch {
    Write-Warn 'nvidia-smi not found - will install CPU-only PyTorch'
}

Write-Info "PyTorch index: $cudaIndex  ($cudaLabel)"

# --------------------------------------------------------------
# 4. PyTorch
# --------------------------------------------------------------
Write-Step "Installing PyTorch (~2 GB for CUDA variant, please wait)"
& $pythonCmd -m pip install torch --index-url $cudaIndex
if ($LASTEXITCODE -ne 0) { Write-Fail "PyTorch install failed (pip exit code $LASTEXITCODE)" }
$torchVer = & $pythonCmd -c 'import torch; print(torch.__version__)' 2>&1
if ($LASTEXITCODE -ne 0) { Write-Fail "PyTorch installed but import failed: $torchVer" }
Write-OK "torch $torchVer"

# --------------------------------------------------------------
# 5. Python packages
# --------------------------------------------------------------
Write-Step "Installing Python packages"

$packages = @(
    [pscustomobject]@{ name = 'faster-whisper'; imp = 'faster_whisper' },
    [pscustomobject]@{ name = 'sounddevice';    imp = 'sounddevice'    },
    [pscustomobject]@{ name = 'soundfile';      imp = 'soundfile'      },
    [pscustomobject]@{ name = 'pynput';         imp = 'pynput'         },
    [pscustomobject]@{ name = 'numpy';          imp = 'numpy'          }
)

foreach ($pkg in $packages) {
    Write-Info "Installing $($pkg.name)..."
    & $pythonCmd -m pip install $pkg.name --quiet
    if ($LASTEXITCODE -ne 0) { Write-Fail "$($pkg.name) install failed (pip exit code $LASTEXITCODE)" }
    $ver = & $pythonCmd -c "import $($pkg.imp); print(getattr($($pkg.imp), '__version__', 'ok'))" 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Fail "$($pkg.name) import failed: $ver" }
    Write-OK "$($pkg.name) $ver"
}

# --------------------------------------------------------------
# 6. Verify all imports
# --------------------------------------------------------------
Write-Step "Verifying imports"

$verifyPy = @'
import sys
ok = True
for lib in ["torch", "faster_whisper", "sounddevice", "soundfile", "pynput", "numpy"]:
    try:
        __import__(lib)
        print("  OK  " + lib)
    except ImportError as e:
        print("  FAIL " + lib + ": " + str(e))
        ok = False

import torch
if torch.cuda.is_available():
    print("\n  Torch device : CUDA " + str(torch.version.cuda))
    print("  GPU          : " + torch.cuda.get_device_name(0))
else:
    print("\n  Torch device : CPU only")

sys.exit(0 if ok else 1)
'@

$verifyFile = [System.IO.Path]::GetTempFileName() + '.py'
Set-Content -Path $verifyFile -Value $verifyPy -Encoding UTF8
& $pythonCmd $verifyFile
if ($LASTEXITCODE -ne 0) { Write-Warn "One or more imports failed - check output above" }
Remove-Item $verifyFile

# --------------------------------------------------------------
# 7. Create transcripts folder
# --------------------------------------------------------------
Write-Step "Creating transcripts folder"
$transcriptDir = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'transcripts'
if (-not (Test-Path $transcriptDir)) {
    New-Item -ItemType Directory -Path $transcriptDir | Out-Null
}
Write-OK $transcriptDir

# --------------------------------------------------------------
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Setup complete. Run the app with:        " -ForegroundColor Green
Write-Host "  python scripts\transcribe_tts.py         " -ForegroundColor Green
Write-Host "  (first run downloads Whisper ~500 MB)    " -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
