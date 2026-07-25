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

if (
    -not (Test-Path ".build_deps\PySide6") -or
    -not (Test-Path ".build_deps\numpy")
) {
    & $Python -m pip install --target .build_deps -r requirements.txt
}

$env:PYTHONPATH = (Resolve-Path ".build_deps").Path

$OutputDir = "dist\BPSR_MIDI_to_KEY_Player"
$OutputExe = Join-Path $OutputDir "BPSR_MIDI_to_KEY_Player.exe"
$OutputReadme = Join-Path $OutputDir "readme.txt"
$LegacySingleFileExe = "dist\BPSR_MIDI_to_KEY_Player.exe"
if (Test-Path $OutputDir) {
    Remove-Item -LiteralPath $OutputDir -Recurse -Force
}
if (Test-Path $LegacySingleFileExe) {
    Remove-Item -LiteralPath $LegacySingleFileExe -Force
}

$ArgsList = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--contents-directory",
    "_internal",
    "--windowed",
    "--icon",
    "assets\app_icon_whale.ico",
    "--add-data",
    "assets\app_icon_whale.ico;assets",
    "--add-data",
    "assets\app_icon_whale.png;assets",
    "--add-data",
    "assets\whale_slider_frame_0.png;assets",
    "--add-data",
    "assets\whale_slider_frame_1.png;assets",
    "--add-data",
    "assets\whale_slider_frame_2.png;assets",
    "--add-data",
    "assets\check_white.svg;assets",
    "--name",
    "BPSR_MIDI_to_KEY_Player",
    "main.py"
)

& $Python -c "import sys; from PyInstaller.__main__ import run; run(sys.argv[1:])" @ArgsList

$SpecPath = "BPSR_MIDI_to_KEY_Player.spec"
if (Test-Path $SpecPath) {
    $SpecContent = [System.IO.File]::ReadAllText($SpecPath).Replace("`r`n", "`n")
    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($SpecPath, $SpecContent, $Utf8NoBom)
}

if (-not (Test-Path $OutputExe)) {
    throw "Build failed: $OutputExe was not created."
}

$UnusedRuntimePaths = @(
    (Join-Path $OutputDir "_internal\PySide6\QtMultimediaWidgets.pyd"),
    (Join-Path $OutputDir "_internal\PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll"),
    (Join-Path $OutputDir "_internal\Qt6MultimediaWidgets.dll"),
    (Join-Path $OutputDir "_internal\Qt6VirtualKeyboard.dll"),
    (Join-Path $OutputDir "_internal\Qt6Quick.dll"),
    (Join-Path $OutputDir "_internal\Qt6Qml.dll"),
    (Join-Path $OutputDir "_internal\Qt6QmlMeta.dll"),
    (Join-Path $OutputDir "_internal\Qt6QmlModels.dll"),
    (Join-Path $OutputDir "_internal\Qt6QmlWorkerScript.dll")
)
foreach ($UnusedRuntimePath in $UnusedRuntimePaths) {
    if (Test-Path -LiteralPath $UnusedRuntimePath) {
        Remove-Item -LiteralPath $UnusedRuntimePath -Force
    }
}

Copy-Item -LiteralPath "readme.txt" -Destination $OutputReadme -Force
if (-not (Test-Path $OutputReadme)) {
    throw "Build failed: $OutputReadme was not created."
}

Write-Host ""
Write-Host "Built folder: $OutputDir"
Write-Host "Launch: $OutputExe"
