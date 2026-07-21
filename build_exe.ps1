$ErrorActionPreference = "Stop"

$PythonCandidates = @(
    "python",
    "py"
)

$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path $BundledPython) {
    $PythonCandidates = @($BundledPython) + $PythonCandidates
}

$Python = $null
foreach ($Candidate in $PythonCandidates) {
    try {
        & $Candidate --version *> $null
        $Python = $Candidate
        break
    } catch {
    }
}

if (-not $Python) {
    throw "Python was not found. Install Python 3.10+ or run this script from Codex."
}

if (-not (Test-Path ".build_deps\PyInstaller")) {
    & $Python -m pip install --target .build_deps pyinstaller
}

if (-not (Test-Path ".build_deps\PySide6")) {
    & $Python -m pip install --target .build_deps -r requirements.txt
}

$env:PYTHONPATH = (Resolve-Path ".build_deps").Path

$OutputExe = "dist\BPSR_MIDI_to_KEY_Player.exe"
if (Test-Path $OutputExe) {
    Remove-Item -LiteralPath $OutputExe -Force
}

$ArgsList = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--exclude-module",
    "tkinter",
    "--icon",
    "assets\app_icon_whale.ico",
    "--add-data",
    "assets\app_icon_whale.ico;assets",
    "--add-data",
    "assets\app_icon_whale.png;assets",
    "--add-data",
    "assets\app_icon_whale_flipped.png;assets",
    "--add-data",
    "assets\check_white.svg;assets",
    "--name",
    "BPSR_MIDI_to_KEY_Player",
    "main.py"
)

& $Python -c "import sys; from PyInstaller.__main__ import run; run(sys.argv[1:])" @ArgsList

if (-not (Test-Path $OutputExe)) {
    throw "Build failed: $OutputExe was not created."
}

Write-Host ""
Write-Host "Built: $OutputExe"
