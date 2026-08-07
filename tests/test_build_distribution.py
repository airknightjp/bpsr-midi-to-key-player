from __future__ import annotations

import unittest
from pathlib import Path


class BuildDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.script = (cls.project_root / "build_exe.ps1").read_text(
            encoding="utf-8"
        )

    def test_build_uses_folder_distribution(self) -> None:
        self.assertIn('"--onedir"', self.script)
        self.assertNotIn('"--onefile"', self.script)
        self.assertIn(
            '$OutputDir = "dist\\BPSR_MIDI_to_KEY_Player"',
            self.script,
        )

    def test_build_removes_legacy_single_file_executable(self) -> None:
        self.assertIn(
            '$LegacySingleFileExe = "dist\\BPSR_MIDI_to_KEY_Player.exe"',
            self.script,
        )
        self.assertIn(
            "Remove-Item -LiteralPath $LegacySingleFileExe -Force",
            self.script,
        )

    def test_build_copies_distribution_readme_next_to_executable(self) -> None:
        self.assertIn(
            '$OutputReadme = Join-Path $OutputDir "readme.txt"',
            self.script,
        )
        self.assertIn(
            'Copy-Item -LiteralPath "readme.txt" -Destination $OutputReadme -Force',
            self.script,
        )
        self.assertNotIn('"assets\\fonts;assets\\fonts"', self.script)
        self.assertFalse((self.project_root / "assets" / "fonts").exists())

    def test_build_preserves_the_existing_application_database(self) -> None:
        self.assertIn(
            '$OutputDatabase = Join-Path $OutputDir "bpsr_midi_to_key_player.db"',
            self.script,
        )
        self.assertIn(
            "Copy-Item -LiteralPath $OutputDatabase -Destination $DatabaseBackup -Force",
            self.script,
        )
        self.assertIn(
            "Copy-Item -LiteralPath $DatabaseBackup -Destination $OutputDatabase -Force",
            self.script,
        )
        self.assertIn("} finally {", self.script)

    def test_build_removes_unused_qml_and_widget_runtimes(self) -> None:
        for name in (
            "QtMultimediaWidgets.pyd",
            "qtvirtualkeyboardplugin.dll",
            "Qt6MultimediaWidgets.dll",
            "Qt6VirtualKeyboard.dll",
            "Qt6Quick.dll",
            "Qt6Qml.dll",
            "Qt6QmlMeta.dll",
            "Qt6QmlModels.dll",
            "Qt6QmlWorkerScript.dll",
        ):
            with self.subTest(name=name):
                self.assertIn(name, self.script)
        self.assertIn(
            "Remove-Item -LiteralPath $UnusedRuntimePath -Force",
            self.script,
        )

    def test_current_documentation_requires_the_complete_folder(self) -> None:
        for name in (
            "README.md",
            "README.ja.md",
            "README.en.md",
            "README.zh-CN.md",
            "readme.txt",
        ):
            with self.subTest(name=name):
                text = (self.project_root / name).read_text(encoding="utf-8")
                self.assertIn("_internal", text)
                self.assertIn("BPSR_MIDI_to_KEY_Player.exe", text)


if __name__ == "__main__":
    unittest.main()
