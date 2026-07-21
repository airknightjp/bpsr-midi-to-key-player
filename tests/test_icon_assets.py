from __future__ import annotations

import struct
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_ROOT / "assets"


class IconAssetTests(unittest.TestCase):
    def test_only_current_icon_assets_remain(self) -> None:
        self.assertEqual(
            {path.name for path in ASSETS_DIR.iterdir() if path.is_file()},
            {"app_icon_whale.ico", "app_icon_whale.png"},
        )

    def test_active_files_do_not_reference_the_previous_icon(self) -> None:
        for relative_path in (
            "main.py",
            "build_exe.ps1",
            "BPSR_MIDI_to_KEY_Player.spec",
        ):
            with self.subTest(path=relative_path):
                contents = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
                self.assertNotIn("app_icon_starry_concept", contents)
                self.assertIn("app_icon_whale", contents)

    def test_png_has_alpha_and_ico_contains_multiple_sizes(self) -> None:
        png_data = (ASSETS_DIR / "app_icon_whale.png").read_bytes()
        self.assertEqual(png_data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(png_data[25], 6)

        ico_data = (ASSETS_DIR / "app_icon_whale.ico").read_bytes()
        reserved, icon_type, image_count = struct.unpack("<HHH", ico_data[:6])
        self.assertEqual((reserved, icon_type), (0, 1))
        self.assertGreaterEqual(image_count, 8)


if __name__ == "__main__":
    unittest.main()
