from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QProcess, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


RELEASES_API_URL = (
    "https://api.github.com/repos/"
    "airknightjp/bpsr-midi-to-key-player/releases/latest"
)
PRODUCT_DIRECTORY_NAME = "BPSR_MIDI_to_KEY_Player"
EXECUTABLE_NAME = "BPSR_MIDI_to_KEY_Player.exe"
UPDATE_ERROR_FILE_NAME = ".bpsr_update_error.txt"
CHECK_TIMEOUT_MS = 8_000
UPDATE_CHECK_INTERVAL_SECONDS = 60 * 60
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256_PATTERN = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_MANAGED_ENTRIES = (EXECUTABLE_NAME, "_internal", "readme.txt")


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class AvailableUpdate:
    version: str
    tag_name: str
    release_url: str
    asset: ReleaseAsset


def automatic_update_check_due(
    last_check_at: object,
    current_time: int | None = None,
) -> bool:
    try:
        previous = int(last_check_at)
    except (TypeError, ValueError):
        return True
    if previous <= 0:
        return True
    now = int(time.time()) if current_time is None else int(current_time)
    elapsed = now - previous
    return elapsed < 0 or elapsed >= UPDATE_CHECK_INTERVAL_SECONDS


def parse_version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = _VERSION_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer_version(candidate: object, current: object) -> bool:
    candidate_version = parse_version(candidate)
    current_version = parse_version(current)
    return (
        candidate_version is not None
        and current_version is not None
        and candidate_version > current_version
    )


def parse_latest_release(
    payload: bytes | bytearray | str | dict[str, object],
    current_version: str,
) -> AvailableUpdate | None:
    if isinstance(payload, (bytes, bytearray)):
        data: object = json.loads(bytes(payload).decode("utf-8"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload
    if not isinstance(data, dict):
        raise ValueError("GitHub release response is not an object.")
    if data.get("draft") or data.get("prerelease"):
        return None

    tag_name = data.get("tag_name")
    parsed_version = parse_version(tag_name)
    if parsed_version is None or not is_newer_version(tag_name, current_version):
        return None
    version = ".".join(str(part) for part in parsed_version)

    release_url = _validated_https_url(
        data.get("html_url"),
        allowed_hosts={"github.com"},
    )
    expected_asset_name = f"{PRODUCT_DIRECTORY_NAME}_v{version}.zip"
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise ValueError("GitHub release response has no assets.")

    for raw_asset in assets:
        if not isinstance(raw_asset, dict):
            continue
        if raw_asset.get("name") != expected_asset_name:
            continue
        if raw_asset.get("state") != "uploaded":
            raise ValueError("The update ZIP is not fully uploaded.")
        digest = raw_asset.get("digest")
        digest_match = (
            _SHA256_PATTERN.fullmatch(digest)
            if isinstance(digest, str)
            else None
        )
        if digest_match is None:
            raise ValueError("The update ZIP has no valid SHA-256 digest.")
        size = raw_asset.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError("The update ZIP has an invalid size.")
        download_url = _validated_https_url(
            raw_asset.get("browser_download_url"),
            allowed_hosts={"github.com"},
        )
        return AvailableUpdate(
            version=version,
            tag_name=str(tag_name),
            release_url=release_url,
            asset=ReleaseAsset(
                name=expected_asset_name,
                download_url=download_url,
                size=size,
                sha256=digest_match.group(1).lower(),
            ),
        )
    raise ValueError(f"Release asset {expected_asset_name} was not found.")


def validate_update_archive(path: str | Path) -> str:
    archive_path = Path(path)
    required_files = {
        f"{PRODUCT_DIRECTORY_NAME}/{EXECUTABLE_NAME}",
        f"{PRODUCT_DIRECTORY_NAME}/readme.txt",
    }
    has_internal_file = False
    seen_files: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            member = PurePosixPath(normalized)
            if (
                member.is_absolute()
                or not member.parts
                or any(part in {"", ".", ".."} for part in member.parts)
                or member.parts[0] != PRODUCT_DIRECTORY_NAME
            ):
                raise ValueError("The update ZIP contains an unsafe path.")
            file_type = (info.external_attr >> 16) & 0o170000
            if file_type == stat.S_IFLNK:
                raise ValueError("The update ZIP contains a symbolic link.")
            if info.is_dir():
                continue
            seen_files.add(member.as_posix())
            if (
                len(member.parts) > 2
                and member.parts[1] == "_internal"
            ):
                has_internal_file = True
    if not required_files.issubset(seen_files) or not has_internal_file:
        raise ValueError("The update ZIP does not contain the expected application.")
    return PRODUCT_DIRECTORY_NAME


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def automatic_update_supported() -> bool:
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def read_pending_update_error(install_dir: str | Path | None = None) -> str:
    directory = Path(install_dir) if install_dir is not None else application_directory()
    error_path = directory / UPDATE_ERROR_FILE_NAME
    try:
        message = error_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError:
        return ""
    try:
        error_path.unlink()
    except OSError:
        pass
    return message


def launch_update_installer(
    update: AvailableUpdate,
    install_dir: str | Path | None = None,
    process_id: int | None = None,
    language: str = "en",
) -> bool:
    if not automatic_update_supported():
        return False
    download_url = _validated_https_url(
        update.asset.download_url,
        allowed_hosts={"github.com"},
    )
    if update.asset.size <= 0:
        raise ValueError("The update ZIP has an invalid size.")
    if re.fullmatch(r"[0-9a-fA-F]{64}", update.asset.sha256) is None:
        raise ValueError("The update ZIP has no valid SHA-256 digest.")
    destination = (
        Path(install_dir).resolve()
        if install_dir is not None
        else application_directory()
    )
    _verify_directory_is_writable(destination)

    update_root = Path(
        tempfile.mkdtemp(prefix="BPSR_MIDI_to_KEY_Player_update_")
    )
    updater_path = update_root / "apply_update.ps1"
    updater_path.write_text(
        _POWERSHELL_UPDATER,
        encoding="utf-8-sig",
        newline="\n",
    )
    arguments = [
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(updater_path),
        "-ProcessId",
        str(process_id if process_id is not None else os.getpid()),
        "-InstallDir",
        str(destination),
        "-DownloadUrl",
        download_url,
        "-ExpectedSize",
        str(update.asset.size),
        "-ExpectedSha256",
        update.asset.sha256.lower(),
        "-ArchiveName",
        update.asset.name,
        "-ExecutableName",
        EXECUTABLE_NAME,
        "-ProductDirectoryName",
        PRODUCT_DIRECTORY_NAME,
        "-ErrorFileName",
        UPDATE_ERROR_FILE_NAME,
        "-Language",
        language if language in {"en", "ja", "zh"} else "en",
    ]
    result = QProcess.startDetached(
        "powershell.exe",
        arguments,
        str(destination),
    )
    started = bool(result[0]) if isinstance(result, tuple) else bool(result)
    if not started:
        shutil.rmtree(update_root, ignore_errors=True)
    return started


class UpdateService(QObject):
    checkCompleted = Signal(object)
    checkFailed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._check_reply: QNetworkReply | None = None

    def check_for_updates(self, current_version: str) -> bool:
        if self._check_reply is not None:
            return False
        request = self._request(RELEASES_API_URL, CHECK_TIMEOUT_MS)
        reply = self._network.get(request)
        self._check_reply = reply
        reply.finished.connect(
            lambda: self._finish_check(reply, current_version)
        )
        return True

    @staticmethod
    def _request(url: str, timeout_ms: int) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(
            b"User-Agent",
            b"BPSR-MIDI-to-KEY-Player",
        )
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setTransferTimeout(timeout_ms)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        return request

    def _finish_check(
        self,
        reply: QNetworkReply,
        current_version: str,
    ) -> None:
        if reply is not self._check_reply:
            return
        self._check_reply = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise RuntimeError(reply.errorString())
            update = parse_latest_release(
                bytes(reply.readAll()),
                current_version,
            )
            self.checkCompleted.emit(update)
        except Exception as exc:
            self.checkFailed.emit(str(exc))
        finally:
            reply.deleteLater()

def _validated_https_url(
    value: object,
    allowed_hosts: set[str],
) -> str:
    if not isinstance(value, str):
        raise ValueError("GitHub release response contains an invalid URL.")
    parsed = urlparse(value)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() not in allowed_hosts
    ):
        raise ValueError("GitHub release response contains an untrusted URL.")
    return value


def _verify_directory_is_writable(directory: Path) -> None:
    if not directory.is_dir():
        raise ValueError("The application directory does not exist.")
    probe = directory / f".bpsr_update_write_test_{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise PermissionError(
            "The application directory is not writable."
        ) from exc


_POWERSHELL_UPDATER = r'''param(
    [Parameter(Mandatory = $true)][int]$ProcessId,
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [Parameter(Mandatory = $true)][string]$DownloadUrl,
    [Parameter(Mandatory = $true)][long]$ExpectedSize,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$ArchiveName,
    [Parameter(Mandatory = $true)][string]$ExecutableName,
    [Parameter(Mandatory = $true)][string]$ProductDirectoryName,
    [Parameter(Mandatory = $true)][string]$ErrorFileName,
    [Parameter(Mandatory = $true)][string]$Language
)

$ErrorActionPreference = "Stop"
$UpdateRoot = [IO.Path]::GetDirectoryName($MyInvocation.MyCommand.Path)
$ZipPath = Join-Path $UpdateRoot $ArchiveName
$StagingDir = Join-Path $UpdateRoot "staging"
$BackupDir = Join-Path $InstallDir (".bpsr_update_backup_" + $ProcessId)
$ExecutablePath = Join-Path $InstallDir $ExecutableName
$ErrorFilePath = Join-Path $InstallDir $ErrorFileName
$ManagedEntries = @($ExecutableName, "_internal", "readme.txt")
$BackupStarted = $false
$Headless = $env:BPSR_UPDATE_HEADLESS -eq "1"
$ProgressForm = $null
$ProgressLabel = $null
$ProgressBar = $null

if (-not $Headless) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
}

$Texts = switch ($Language) {
    "ja" {
        @{
            Title = "BPSR MIDI to KEY Player - アップデート"
            Downloading = "更新ファイルをダウンロードしています..."
            Verifying = "更新ファイルを検証しています..."
            Waiting = "アプリの終了を待っています..."
            Extracting = "更新ファイルを展開しています..."
            Backup = "現在のバージョンをバックアップしています..."
            Installing = "新しいバージョンを適用しています..."
            Restarting = "更新が完了しました。再起動しています..."
            Failed = "更新に失敗しました。以前のバージョンへ戻しています..."
        }
    }
    "zh" {
        @{
            Title = "BPSR MIDI to KEY Player - 软件更新"
            Downloading = "正在下载更新文件..."
            Verifying = "正在验证更新文件..."
            Waiting = "正在等待应用退出..."
            Extracting = "正在解压更新文件..."
            Backup = "正在备份当前版本..."
            Installing = "正在安装新版本..."
            Restarting = "更新完成，正在重新启动..."
            Failed = "更新失败，正在恢复以前的版本..."
        }
    }
    default {
        @{
            Title = "BPSR MIDI to KEY Player - Update"
            Downloading = "Downloading the update..."
            Verifying = "Verifying the update..."
            Waiting = "Waiting for the app to close..."
            Extracting = "Extracting the update..."
            Backup = "Backing up the current version..."
            Installing = "Installing the new version..."
            Restarting = "Update complete. Restarting..."
            Failed = "Update failed. Restoring the previous version..."
        }
    }
}

if (-not $Headless) {
    $ProgressForm = New-Object System.Windows.Forms.Form
    $ProgressForm.Text = $Texts.Title
    $ProgressForm.StartPosition = "CenterScreen"
    $ProgressForm.ClientSize = New-Object System.Drawing.Size(430, 100)
    $ProgressForm.FormBorderStyle = "FixedDialog"
    $ProgressForm.MaximizeBox = $false
    $ProgressForm.MinimizeBox = $false
    $ProgressForm.ControlBox = $false
    $ProgressForm.TopMost = $true

    $ProgressLabel = New-Object System.Windows.Forms.Label
    $ProgressLabel.AutoSize = $false
    $ProgressLabel.Location = New-Object System.Drawing.Point(18, 16)
    $ProgressLabel.Size = New-Object System.Drawing.Size(394, 24)
    $ProgressForm.Controls.Add($ProgressLabel)

    $ProgressBar = New-Object System.Windows.Forms.ProgressBar
    $ProgressBar.Location = New-Object System.Drawing.Point(18, 52)
    $ProgressBar.Size = New-Object System.Drawing.Size(394, 22)
    $ProgressBar.Minimum = 0
    $ProgressBar.Maximum = 100
    $ProgressForm.Controls.Add($ProgressBar)
    $ProgressForm.Show()
}

function Set-UpdateProgress {
    param([int]$Value, [string]$Message)
    if ($null -ne $ProgressForm) {
        $ProgressBar.Value = [Math]::Max(0, [Math]::Min(100, $Value))
        $ProgressLabel.Text = $Message
        [System.Windows.Forms.Application]::DoEvents()
    }
}

try {
    Set-UpdateProgress 0 $Texts.Downloading
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Request = [Net.HttpWebRequest]::Create($DownloadUrl)
    $Request.UserAgent = "BPSR-MIDI-to-KEY-Player"
    $Request.AllowAutoRedirect = $true
    $Request.Timeout = 30000
    $Request.ReadWriteTimeout = 120000
    $Response = $Request.GetResponse()
    try {
        $InputStream = $Response.GetResponseStream()
        $OutputStream = [IO.File]::Create($ZipPath)
        try {
            $Buffer = New-Object byte[] 65536
            [long]$Downloaded = 0
            [long]$LastProgressTick = 0
            while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputStream.Write($Buffer, 0, $Read)
                $Downloaded += $Read
                $NowTick = [Environment]::TickCount64
                if (
                    $ExpectedSize -gt 0 -and
                    ($NowTick - $LastProgressTick -ge 100 -or $Downloaded -eq $ExpectedSize)
                ) {
                    $Percent = [Math]::Min(100, [Math]::Floor($Downloaded * 100 / $ExpectedSize))
                    Set-UpdateProgress ([Math]::Floor($Percent * 0.45)) (
                        $Texts.Downloading + " " + $Percent + "%"
                    )
                    $LastProgressTick = $NowTick
                }
            }
        }
        finally {
            if ($null -ne $OutputStream) {
                $OutputStream.Dispose()
            }
            if ($null -ne $InputStream) {
                $InputStream.Dispose()
            }
        }
    }
    finally {
        if ($null -ne $Response) {
            $Response.Dispose()
        }
    }

    Set-UpdateProgress 48 $Texts.Verifying
    $ActualSize = (Get-Item -LiteralPath $ZipPath).Length
    if ($ActualSize -ne $ExpectedSize) {
        throw "The downloaded update ZIP has an unexpected size."
    }
    $ActualSha256 = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash
    if ($ActualSha256 -ne $ExpectedSha256) {
        throw "The downloaded update ZIP failed SHA-256 verification."
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $StagingRoot = [IO.Path]::GetFullPath(
            $StagingDir + [IO.Path]::DirectorySeparatorChar
        )
        $HasExecutable = $false
        $HasReadme = $false
        $HasInternalFile = $false
        foreach ($Entry in $Archive.Entries) {
            $Name = $Entry.FullName.Replace("\", "/")
            $IsDirectory = $Name.EndsWith("/")
            $PathName = $Name.TrimEnd("/")
            $Parts = $PathName.Split("/")
            $InvalidPart = $false
            foreach ($Part in $Parts) {
                if ($Part -eq "" -or $Part -eq "." -or $Part -eq "..") {
                    $InvalidPart = $true
                }
            }
            if (
                [IO.Path]::IsPathRooted($Name) -or
                $Parts.Count -eq 0 -or
                $Parts[0] -ne $ProductDirectoryName -or
                $InvalidPart
            ) {
                throw "The update ZIP contains an unsafe path."
            }
            $TargetPath = [IO.Path]::GetFullPath((Join-Path $StagingDir $PathName))
            if (-not $TargetPath.StartsWith(
                $StagingRoot,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw "The update ZIP contains an unsafe path."
            }
            $FileType = ($Entry.ExternalAttributes -shr 16) -band 0xF000
            if ($FileType -eq 0xA000) {
                throw "The update ZIP contains a symbolic link."
            }
            if ($IsDirectory) {
                continue
            }
            if ($Name -eq ($ProductDirectoryName + "/" + $ExecutableName)) {
                $HasExecutable = $true
            }
            if ($Name -eq ($ProductDirectoryName + "/readme.txt")) {
                $HasReadme = $true
            }
            if ($Parts.Count -gt 2 -and $Parts[1] -eq "_internal") {
                $HasInternalFile = $true
            }
        }
        if (-not $HasExecutable -or -not $HasReadme -or -not $HasInternalFile) {
            throw "The update ZIP does not contain the expected application."
        }
    }
    finally {
        if ($null -ne $Archive) {
            $Archive.Dispose()
        }
    }

    Set-UpdateProgress 55 $Texts.Waiting
    Wait-Process -Id $ProcessId -ErrorAction SilentlyContinue
    Set-UpdateProgress 62 $Texts.Extracting
    Remove-Item -LiteralPath $StagingDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $StagingDir | Out-Null
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $StagingDir -Force

    $PayloadDir = Join-Path $StagingDir $ProductDirectoryName
    if (
        -not (Test-Path -LiteralPath (Join-Path $PayloadDir $ExecutableName)) -or
        -not (Test-Path -LiteralPath (Join-Path $PayloadDir "_internal"))
    ) {
        throw "The extracted update package is invalid."
    }

    Set-UpdateProgress 76 $Texts.Backup
    Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
    $BackupStarted = $true
    foreach ($Entry in $ManagedEntries) {
        $CurrentPath = Join-Path $InstallDir $Entry
        if (Test-Path -LiteralPath $CurrentPath) {
            Move-Item -LiteralPath $CurrentPath -Destination $BackupDir
        }
    }

    Set-UpdateProgress 88 $Texts.Installing
    foreach ($Entry in $ManagedEntries) {
        $NewPath = Join-Path $PayloadDir $Entry
        if (Test-Path -LiteralPath $NewPath) {
            Move-Item -LiteralPath $NewPath -Destination $InstallDir
        }
    }
    if (-not (Test-Path -LiteralPath $ExecutablePath)) {
        throw "The updated executable was not installed."
    }

    Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ErrorFilePath -Force -ErrorAction SilentlyContinue
    Set-UpdateProgress 100 $Texts.Restarting
    Start-Sleep -Milliseconds 300
}
catch {
    $FailureMessage = $_.Exception.Message
    try {
        if ($BackupStarted) {
            foreach ($Entry in $ManagedEntries) {
                $FailedPath = Join-Path $InstallDir $Entry
                Remove-Item -LiteralPath $FailedPath -Recurse -Force -ErrorAction SilentlyContinue
            }
            foreach ($Entry in $ManagedEntries) {
                $BackupPath = Join-Path $BackupDir $Entry
                if (Test-Path -LiteralPath $BackupPath) {
                    Move-Item -LiteralPath $BackupPath -Destination $InstallDir
                }
            }
        }
    }
    catch {
    }
    Set-UpdateProgress 100 $Texts.Failed
    $Message = "Automatic update failed: " + $FailureMessage
    try {
        Set-Content -LiteralPath $ErrorFilePath -Value $Message -Encoding UTF8
    }
    catch {
    }
    Start-Sleep -Milliseconds 1000
}
finally {
    Wait-Process -Id $ProcessId -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StagingDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
    if ($null -ne $ProgressForm) {
        $ProgressForm.Close()
        $ProgressForm.Dispose()
    }
    if (Test-Path -LiteralPath $ExecutablePath) {
        $env:BPSR_UPDATE_RESTART = "1"
        Start-Process -FilePath $ExecutablePath -WorkingDirectory $InstallDir | Out-Null
        if (-not $Headless) {
            try {
                $WindowShell = New-Object -ComObject WScript.Shell
                for ($Attempt = 0; $Attempt -lt 150; $Attempt++) {
                    Start-Sleep -Milliseconds 100
                    if ($WindowShell.AppActivate("BPSR MIDI to KEY Player")) {
                        break
                    }
                }
            }
            catch {
            }
        }
    }
}
'''
