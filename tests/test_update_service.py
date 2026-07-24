from __future__ import annotations

import stat
import shutil
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
    _POWERSHELL_UPDATER,
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

    def test_launcher_writes_visible_progress_updater_and_passes_language(
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
            updater_path = Path(arguments[arguments.index("-File") + 1])
            try:
                self.assertTrue(
                    updater_path.read_bytes().startswith(b"\xef\xbb\xbf")
                )
                script = updater_path.read_text(encoding="utf-8-sig")
                self.assertIn("System.Windows.Forms.ProgressBar", script)
                self.assertEqual(script.count("$ProgressForm.Show()"), 1)
                self.assertIn("Set-UpdateProgress 88", script)
                self.assertIn("Get-FileHash", script)
                self.assertIn("$BackupStarted", script)
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
                shutil.rmtree(updater_path.parent, ignore_errors=True)

    def test_updater_preserves_settings_and_restarts_after_progress(self) -> None:
        self.assertNotIn('"settings.json"', _POWERSHELL_UPDATER)
        self.assertNotIn("Split-Path -LiteralPath", _POWERSHELL_UPDATER)
        self.assertIn('$ProgressForm.Show()', _POWERSHELL_UPDATER)
        self.assertIn("$Request.GetResponse()", _POWERSHELL_UPDATER)
        self.assertIn("Wait-Process -Id $ProcessId", _POWERSHELL_UPDATER)
        self.assertIn('$env:BPSR_UPDATE_RESTART = "1"', _POWERSHELL_UPDATER)
        self.assertIn("Start-Process -FilePath $ExecutablePath", _POWERSHELL_UPDATER)
        self.assertIn(
            '$WindowShell.AppActivate("BPSR MIDI to KEY Player")',
            _POWERSHELL_UPDATER,
        )
        self.assertIn("$Attempt -lt 150", _POWERSHELL_UPDATER)


if __name__ == "__main__":
    unittest.main()
