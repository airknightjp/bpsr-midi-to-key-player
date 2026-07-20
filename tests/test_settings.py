from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from settings import AppSettings, consume_settings_error, load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_default_theme_is_sky_blue(self) -> None:
        self.assertEqual(AppSettings().color_theme, "sky_blue")

    def test_new_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"APPDATA": temp_dir}):
                save_settings(
                    AppSettings(
                        countdown_seconds=2,
                        midi_sound_volume=70,
                        dry_run=False,
                        countdown_sound=True,
                        game_countdown_sound=True,
                        auto_fit_note_range=True,
                        transpose_semitones=-7,
                        octave_shift=2,
                        humanize_timing=True,
                        chord_strum=True,
                        repeat_prevention=True,
                        playback_speed_percent=135,
                        language="ja",
                        color_theme="orange",
                        always_on_top=True,
                        tray_resident=True,
                        window_opacity=75,
                        window_height=720,
                        last_midi_folder=str(Path(temp_dir) / "midis"),
                        keyboard_play_shortcut="Ctrl+P",
                        keyboard_stop_shortcut="Ctrl+S",
                        shortcut_locked=False,
                        midi_input_device="USB MIDI",
                        key_bindings={60: "q", 61: "w"},
                    )
                )

                loaded = load_settings()
                settings_dir = Path(temp_dir) / "BPSR_MIDI_to_KEY_Player"
                self.assertFalse((settings_dir / "settings.json.tmp").exists())

        self.assertEqual(loaded.color_theme, "orange")
        self.assertTrue(loaded.always_on_top)
        self.assertTrue(loaded.tray_resident)
        self.assertEqual(loaded.window_opacity, 75)
        self.assertEqual(loaded.window_height, 720)
        self.assertTrue(loaded.countdown_sound)
        self.assertTrue(loaded.game_countdown_sound)
        self.assertTrue(loaded.auto_fit_note_range)
        self.assertEqual(loaded.transpose_semitones, -7)
        self.assertEqual(loaded.octave_shift, 2)
        self.assertTrue(loaded.humanize_timing)
        self.assertTrue(loaded.chord_strum)
        self.assertTrue(loaded.repeat_prevention)
        self.assertEqual(loaded.playback_speed_percent, 135)
        self.assertTrue(loaded.last_midi_folder.endswith("midis"))
        self.assertEqual(loaded.keyboard_play_shortcut, "Ctrl+P")
        self.assertEqual(loaded.keyboard_stop_shortcut, "Ctrl+S")
        self.assertFalse(loaded.shortcut_locked)
        self.assertEqual(loaded.midi_input_device, "USB MIDI")
        self.assertEqual(loaded.resolved_key_bindings()[60], "q")
        self.assertEqual(loaded.resolved_key_bindings()[61], "w")
        self.assertEqual(loaded.resolved_key_bindings()[62], "s")

    def test_note_shift_settings_are_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"APPDATA": temp_dir}):
                settings_dir = Path(temp_dir) / "BPSR_MIDI_to_KEY_Player"
                settings_dir.mkdir()
                (settings_dir / "settings.json").write_text(
                    '{"transpose_semitones": 99, "octave_shift": -99}',
                    encoding="utf-8",
                )

                loaded = load_settings()

        self.assertEqual(loaded.transpose_semitones, 12)
        self.assertEqual(loaded.octave_shift, -3)

    def test_interrupted_atomic_save_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"APPDATA": temp_dir}):
                settings_dir = Path(temp_dir) / "BPSR_MIDI_to_KEY_Player"
                settings_dir.mkdir()
                temporary_path = settings_dir / "settings.json.tmp"
                temporary_path.write_text('{"midi_sound_volume": 42}', encoding="utf-8")

                loaded = load_settings()
                error = consume_settings_error()

                self.assertEqual(loaded.midi_sound_volume, 42)
                self.assertIn("Recovered settings", error)
                self.assertTrue((settings_dir / "settings.json").exists())
                self.assertFalse(temporary_path.exists())

    def test_failed_atomic_replace_removes_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"APPDATA": temp_dir}):
                with patch("settings.os.replace", side_effect=OSError("disk error")):
                    with self.assertRaises(OSError):
                        save_settings(AppSettings())

                temporary_path = (
                    Path(temp_dir)
                    / "BPSR_MIDI_to_KEY_Player"
                    / "settings.json.tmp"
                )
                self.assertFalse(temporary_path.exists())

if __name__ == "__main__":
    unittest.main()
