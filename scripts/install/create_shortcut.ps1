# Creates a "Meeting Recorder" shortcut (Desktop + Start Menu) that opens the
# recorder GUI and starts recording immediately with the default devices.
#
#   -Tray    start minimized to the system tray
#   -Remove  delete the shortcuts again

param(
    [switch]$Tray,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

function Write-OK   { param($m) Write-Host "OK   $m" -ForegroundColor Green }
function Write-Info { param($m) Write-Host "...  $m" -ForegroundColor DarkGray }
function Write-Fail { param($m) Write-Host "FAIL $m" -ForegroundColor Red; exit 1 }

$scripts  = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $scripts
$name     = "Meeting Recorder.lnk"
$targets  = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) $name),
    (Join-Path ([Environment]::GetFolderPath("Programs")) $name)
)

if ($Remove) {
    foreach ($t in $targets) {
        if (Test-Path $t) { Remove-Item $t -Force; Write-OK "Removed $t" }
    }
    exit 0
}

# pythonw.exe = Python without a console window
$pythonw = $null
$cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($cmd) { $pythonw = $cmd.Source }
if (-not $pythonw) {
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) {
        $candidate = Join-Path (Split-Path -Parent $py.Source) "pythonw.exe"
        if (Test-Path $candidate) { $pythonw = $candidate }
    }
}
if (-not $pythonw) { Write-Fail "pythonw.exe not found. Install Python first (scripts\install.bat)." }

$gui = Join-Path $scripts "record_meeting_gui.py"
if (-not (Test-Path $gui)) { Write-Fail "Not found: $gui" }

$arguments = "`"$gui`" --autostart"
if ($Tray) { $arguments += " --tray" }

$shell = New-Object -ComObject WScript.Shell
foreach ($t in $targets) {
    $lnk = $shell.CreateShortcut($t)
    $lnk.TargetPath       = $pythonw
    $lnk.Arguments        = $arguments
    $lnk.WorkingDirectory = $repoRoot
    $lnk.Description      = "Record a meeting (microphone + system audio) with default settings"
    $lnk.IconLocation     = "$env:SystemRoot\System32\mmres.dll,0"
    $lnk.Save()
    Write-OK "Created $t"
}
Write-Info "Target: $pythonw $arguments"
