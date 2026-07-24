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
