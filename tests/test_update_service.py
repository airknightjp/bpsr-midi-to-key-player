from __future__ import annotations

import os
import stat
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from update_service import (
    AvailableUpdate,
    EXECUTABLE_NAME,
    PRODUCT_DIRECTORY_NAME,
    ReleaseAsset,
    UPDATE_ERROR_FILE_NAME,
    UPDATE_CHECK_INTERVAL_SECONDS,
    UPDATE_SUPERVISOR_DIRECTORY_NAME,
    UPDATE_SUPERVISOR_FILE_NAME,
    UPDATE_WORKER_FILE_NAME,
    _POWERSHELL_UPDATE_SUPERVISOR,
    _POWERSHELL_UPDATE_WORKER,
    automatic_update_check_due,
    is_newer_version,
    launch_update_installer,
    parse_latest_release,
    read_pending_update_error,
    validate_update_archive,
)


def release_payload(
    version: str = "1.3.2",
    *,
    digest: str = "sha256:" + ("a" * 64),
    draft: bool = False,
    prerelease: bool = False,
) -> dict[str, object]:
    asset_name = f"{PRODUCT_DIRECTORY_NAME}_v{version}.zip"
    return {
        "tag_name": f"v{version}",
        "html_url": (
            "https://github.com/airknightjp/"
            f"bpsr-midi-to-key-player/releases/tag/v{version}"
        ),
        "draft": draft,
        "prerelease": prerelease,
        "assets": [
            {
                "name": asset_name,
                "state": "uploaded",
                "size": 12345,
                "digest": digest,
                "browser_download_url": (
                    "https://github.com/airknightjp/"
                    "bpsr-midi-to-key-player/releases/download/"
                    f"v{version}/{asset_name}"
                ),
            }
        ],
    }


def write_valid_update_archive(path: Path) -> None:
    root = PRODUCT_DIRECTORY_NAME
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{root}/{EXECUTABLE_NAME}", b"exe")
        archive.writestr(f"{root}/readme.txt", b"readme")
        archive.writestr(f"{root}/_internal/runtime.bin", b"runtime")


def available_update(version: str = "1.3.2") -> AvailableUpdate:
    asset_name = f"{PRODUCT_DIRECTORY_NAME}_v{version}.zip"
    return AvailableUpdate(
        version=version,
        tag_name=f"v{version}",
        release_url=(
            "https://github.com/airknightjp/"
            f"bpsr-midi-to-key-player/releases/tag/v{version}"
        ),
        asset=ReleaseAsset(
            name=asset_name,
            download_url=(
                "https://github.com/airknightjp/"
                "bpsr-midi-to-key-player/releases/download/"
                f"v{version}/{asset_name}"
            ),
            size=12345,
            sha256="a" * 64,
        ),
    )


class UpdateServiceTests(unittest.TestCase):
    def test_automatic_update_check_is_due_once_per_hour(self) -> None:
        checked_at = 1_789_123_456

        self.assertFalse(
            automatic_update_check_due(
                checked_at,
                checked_at + UPDATE_CHECK_INTERVAL_SECONDS - 1,
            )
        )
        self.assertTrue(
            automatic_update_check_due(
                checked_at,
                checked_at + UPDATE_CHECK_INTERVAL_SECONDS,
            )
        )
        self.assertTrue(automatic_update_check_due(0, checked_at))
        self.assertTrue(automatic_update_check_due("invalid", checked_at))

    def test_semantic_version_comparison(self) -> None:
        self.assertTrue(is_newer_version("v1.3.2", "1.3.1"))
        self.assertTrue(is_newer_version("2.0.0", "v1.99.99"))
        self.assertFalse(is_newer_version("1.3.1", "1.3.1"))
        self.assertFalse(is_newer_version("1.3", "1.3.1"))

    def test_latest_release_requires_exact_verified_zip(self) -> None:
        update = parse_latest_release(release_payload(), "1.3.1")

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.version, "1.3.2")
        self.assertEqual(
            update.asset.name,
            "BPSR_MIDI_to_KEY_Player_v1.3.2.zip",
        )
        self.assertEqual(update.asset.sha256, "a" * 64)

    def test_latest_release_ignores_non_updates(self) -> None:
        self.assertIsNone(parse_latest_release(release_payload("1.3.1"), "1.3.1"))
        self.assertIsNone(
            parse_latest_release(release_payload(draft=True), "1.3.1")
        )
        self.assertIsNone(
            parse_latest_release(release_payload(prerelease=True), "1.3.1")
        )

    def test_latest_release_rejects_missing_digest(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            parse_latest_release(release_payload(digest=""), "1.3.1")

    def test_latest_release_rejects_untrusted_download_host(self) -> None:
        payload = release_payload()
        assets = payload["assets"]
        assert isinstance(assets, list)
        asset = assets[0]
        assert isinstance(asset, dict)
        asset["browser_download_url"] = "https://example.com/update.zip"

        with self.assertRaisesRegex(ValueError, "untrusted URL"):
            parse_latest_release(payload, "1.3.1")

    def test_archive_validation_accepts_expected_onedir_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "update.zip"
            write_valid_update_archive(archive_path)

            self.assertEqual(
                validate_update_archive(archive_path),
                PRODUCT_DIRECTORY_NAME,
            )

    def test_archive_validation_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "update.zip"
            write_valid_update_archive(archive_path)
            with zipfile.ZipFile(archive_path, "a") as archive:
                archive.writestr(
                    f"{PRODUCT_DIRECTORY_NAME}/../outside.txt",
                    b"unsafe",
                )

            with self.assertRaisesRegex(ValueError, "unsafe path"):
                validate_update_archive(archive_path)

    def test_archive_validation_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "update.zip"
            write_valid_update_archive(archive_path)
            link = zipfile.ZipInfo(
                f"{PRODUCT_DIRECTORY_NAME}/_internal/link"
            )
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive_path, "a") as archive:
                archive.writestr(link, "runtime.bin")

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                validate_update_archive(archive_path)

    def test_pending_update_error_is_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            error_path = Path(temp_dir) / UPDATE_ERROR_FILE_NAME
            error_path.write_text("update failed", encoding="utf-8")

            self.assertEqual(
                read_pending_update_error(temp_dir),
                "update failed",
            )
            self.assertFalse(error_path.exists())
            self.assertEqual(read_pending_update_error(temp_dir), "")

    def test_launcher_writes_supervisor_and_visible_worker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            install_dir = directory / "app"
            install_dir.mkdir()
            with (
                patch(
                    "update_service.automatic_update_supported",
                    return_value=True,
                ),
                patch(
                    "update_service.QProcess.startDetached",
                    return_value=(True, 100),
                ) as start_detached,
            ):
                self.assertTrue(
                    launch_update_installer(
                        available_update(),
                        install_dir=install_dir,
                        process_id=99,
                        language="ja",
                    )
                )

            arguments = start_detached.call_args.args[1]
            supervisor_path = Path(
                arguments[arguments.index("-File") + 1]
            )
            worker_path = Path(
                arguments[arguments.index("-WorkerPath") + 1]
            )
            update_root = Path(
                arguments[arguments.index("-UpdateRoot") + 1]
            )
            try:
                self.assertTrue(
                    supervisor_path.read_bytes().startswith(b"\xef\xbb\xbf")
                )
                self.assertTrue(
                    worker_path.read_bytes().startswith(b"\xef\xbb\xbf")
                )
                self.assertEqual(
                    supervisor_path,
                    install_dir
                    / UPDATE_SUPERVISOR_DIRECTORY_NAME
                    / UPDATE_SUPERVISOR_FILE_NAME,
                )
                self.assertEqual(worker_path.parent, update_root)
                self.assertEqual(worker_path.name, UPDATE_WORKER_FILE_NAME)
                worker_script = worker_path.read_text(encoding="utf-8-sig")
                self.assertIn(
                    "System.Windows.Forms.ProgressBar",
                    worker_script,
                )
                self.assertEqual(
                    worker_script.count("$ProgressForm.Show()"),
                    1,
                )
                self.assertIn("Set-UpdateProgress 88", worker_script)
                self.assertIn("Get-FileHash", worker_script)
                supervisor_script = supervisor_path.read_text(
                    encoding="utf-8-sig"
                )
                self.assertIn(
                    "$WorkerProcess.WaitForExit(500)",
                    supervisor_script,
                )
                self.assertEqual(
                    arguments[arguments.index("-Language") + 1],
                    "ja",
                )
                self.assertEqual(
                    arguments[arguments.index("-ExpectedSize") + 1],
                    "12345",
                )
                self.assertEqual(
                    arguments[arguments.index("-ExpectedSha256") + 1],
                    "a" * 64,
                )
            finally:
                shutil.rmtree(update_root, ignore_errors=True)

    def test_worker_only_downloads_verifies_and_replaces_payload(self) -> None:
        self.assertNotIn('"settings.json"', _POWERSHELL_UPDATE_WORKER)
        self.assertIn('$ProgressForm.Show()', _POWERSHELL_UPDATE_WORKER)
        self.assertIn("$Request.GetResponse()", _POWERSHELL_UPDATE_WORKER)
        self.assertIn("Get-FileHash", _POWERSHELL_UPDATE_WORKER)
        self.assertIn(
            "Wait-Process -Id $ProcessId",
            _POWERSHELL_UPDATE_WORKER,
        )
        self.assertIn(
            "[IO.File]::WriteAllText(",
            _POWERSHELL_UPDATE_WORKER,
        )
        self.assertNotIn(
            "Start-UpdatedApplication",
            _POWERSHELL_UPDATE_WORKER,
        )
        self.assertNotIn(
            "Restore-UpdateBackup",
            _POWERSHELL_UPDATE_WORKER,
        )
        self.assertNotIn(
            "Remove-UpdateWorkingDirectory",
            _POWERSHELL_UPDATE_WORKER,
        )

    def test_supervisor_monitors_rolls_back_cleans_and_restarts(self) -> None:
        self.assertNotIn('"settings.json"', _POWERSHELL_UPDATE_SUPERVISOR)
        self.assertNotIn(
            "$Request.GetResponse()",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            "$WorkerProcess.WaitForExit(500)",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            "$NoProgressTimeoutSeconds",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            "$MaximumRuntimeSeconds",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            "$WorkerProcess.Kill()",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            "Restore-UpdateBackup",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            "Remove-UpdateWorkingDirectory",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            "$Attempt -lt 40",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            '$env:BPSR_UPDATE_RESTART = "1"',
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            "Start-Process `\n        -FilePath $ExecutablePath",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            '$WindowShell.AppActivate("BPSR MIDI to KEY Player")',
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertIn(
            "$Attempt -lt 150",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertNotIn(
            '"-EncodedCommand"',
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertNotIn(
            '$ProgressForm.Show()',
            _POWERSHELL_UPDATE_SUPERVISOR,
        )

    def test_failed_detached_start_removes_temporary_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            install_dir = directory / "app"
            install_dir.mkdir()
            update_root = directory / "worker"
            update_root.mkdir()
            with (
                patch(
                    "update_service.automatic_update_supported",
                    return_value=True,
                ),
                patch(
                    "update_service.tempfile.mkdtemp",
                    return_value=str(update_root),
                ),
                patch(
                    "update_service.QProcess.startDetached",
                    return_value=(False, 0),
                ),
            ):
                self.assertFalse(
                    launch_update_installer(
                        available_update(),
                        install_dir=install_dir,
                        process_id=99,
                    )
                )

            self.assertFalse(update_root.exists())
            self.assertTrue(
                (
                    install_dir
                    / UPDATE_SUPERVISOR_DIRECTORY_NAME
                    / UPDATE_SUPERVISOR_FILE_NAME
                ).is_file()
            )

    def test_supervisor_does_not_launch_a_second_cleanup_process(
        self,
    ) -> None:
        self.assertIn(
            "$null = Remove-UpdateWorkingDirectory",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )
        self.assertEqual(
            _POWERSHELL_UPDATE_SUPERVISOR.count(
                "Start-Process `\n        -FilePath $ExecutablePath"
            ),
            1,
        )
        self.assertNotIn(
            "EncodedCommand",
            _POWERSHELL_UPDATE_SUPERVISOR,
        )

    @unittest.skipUnless(os.name == "nt", "Windows updater test")
    def test_supervisor_stops_stalled_worker_rolls_back_and_cleans(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            install_dir = directory / "app"
            install_dir.mkdir()
            executable_path = install_dir / EXECUTABLE_NAME
            executable_path.write_bytes(b"old executable")
            internal_dir = install_dir / "_internal"
            internal_dir.mkdir()
            (internal_dir / "runtime.bin").write_bytes(b"old runtime")
            (install_dir / "readme.txt").write_text(
                "old readme",
                encoding="utf-8",
            )

            update_root = directory / "update"
            update_root.mkdir()
            worker_path = update_root / UPDATE_WORKER_FILE_NAME
            worker_path.write_text(
                r'''
$InstallDir = $env:BPSR_UPDATE_INSTALL_DIR
$ProcessId = [int]$env:BPSR_UPDATE_PROCESS_ID
$BackupDir = Join-Path $InstallDir (".bpsr_update_backup_" + $ProcessId)
Set-Content -LiteralPath (Join-Path $InstallDir "worker_pid.txt") -Value $PID
New-Item -ItemType Directory -Path $BackupDir | Out-Null
foreach ($Entry in @("BPSR_MIDI_to_KEY_Player.exe", "_internal", "readme.txt")) {
    Move-Item `
        -LiteralPath (Join-Path $InstallDir $Entry) `
        -Destination $BackupDir
}
[IO.File]::WriteAllText($env:BPSR_UPDATE_PROGRESS_FILE, "started")
Start-Sleep -Seconds 30
''',
                encoding="utf-8-sig",
                newline="\n",
            )
            supervisor_dir = (
                install_dir / UPDATE_SUPERVISOR_DIRECTORY_NAME
            )
            supervisor_dir.mkdir()
            supervisor_path = (
                supervisor_dir / UPDATE_SUPERVISOR_FILE_NAME
            )
            supervisor_path.write_text(
                _POWERSHELL_UPDATE_SUPERVISOR,
                encoding="utf-8-sig",
                newline="\n",
            )
            environment = os.environ.copy()
            environment["BPSR_UPDATE_HEADLESS"] = "1"
            command = [
                "powershell.exe",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(supervisor_path),
                "-WorkerPath",
                str(worker_path),
                "-UpdateRoot",
                str(update_root),
                "-ProcessId",
                str(os.getpid()),
                "-InstallDir",
                str(install_dir),
                "-DownloadUrl",
                "https://github.com/example/update.zip",
                "-ExpectedSize",
                "1",
                "-ExpectedSha256",
                "a" * 64,
                "-ArchiveName",
                "update.zip",
                "-ExecutableName",
                EXECUTABLE_NAME,
                "-ProductDirectoryName",
                PRODUCT_DIRECTORY_NAME,
                "-ErrorFileName",
                UPDATE_ERROR_FILE_NAME,
                "-Language",
                "en",
                "-NoProgressTimeoutSeconds",
                "1",
                "-MaximumRuntimeSeconds",
                "10",
            ]
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
                env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            worker_pid_path = install_dir / "worker_pid.txt"
            worker_pid = int(worker_pid_path.read_text().strip())
            try:
                worker_check = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-Command",
                        (
                            "if (Get-Process -Id "
                            f"{worker_pid} "
                            "-ErrorAction SilentlyContinue) { exit 1 }"
                        ),
                    ],
                    check=False,
                    capture_output=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(worker_check.returncode, 0)
                self.assertFalse(update_root.exists())
                self.assertEqual(
                    executable_path.read_bytes(),
                    b"old executable",
                )
                self.assertEqual(
                    (internal_dir / "runtime.bin").read_bytes(),
                    b"old runtime",
                )
                self.assertEqual(
                    (install_dir / "readme.txt").read_text(
                        encoding="utf-8"
                    ),
                    "old readme",
                )
                self.assertIn(
                    "made no progress",
                    (
                        install_dir / UPDATE_ERROR_FILE_NAME
                    ).read_text(encoding="utf-8-sig"),
                )
            finally:
                subprocess.run(
                    [
                        "taskkill.exe",
                        "/PID",
                        str(worker_pid),
                        "/T",
                        "/F",
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )


if __name__ == "__main__":
    unittest.main()
