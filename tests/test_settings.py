from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from config import normalized_key_bindings
from settings import AppSettings, consume_settings_error, load_settings, save_settings


@contextmanager
def isolated_settings_directory():
    with tempfile.TemporaryDirectory() as temp_dir:
        settings_dir = Path(temp_dir)
        with patch("settings._application_directory", return_value=settings_dir):
            yield settings_dir


class SettingsTests(unittest.TestCase):
    def test_display_and_shortcut_defaults(self) -> None:
        settings = AppSettings()

        self.assertEqual(settings.ui_scale_percent, 100)
        self.assertEqual(settings.window_width, 900)
        self.assertEqual(settings.keyboard_play_shortcut, "F9")
        self.assertEqual(settings.keyboard_pause_shortcut, "F10")
        self.assertEqual(settings.keyboard_stop_shortcut, "F11")
        self.assertFalse(hasattr(settings, "audio_buffer_frames"))
        self.assertFalse(hasattr(settings, "auto_audio_buffer"))
        self.assertEqual(settings.input_conversion_mode, "midi_file")
        self.assertEqual(settings.sound_playback_mode, "off")
        self.assertEqual(
            settings.panel_order,
            (
                "input_conversion",
                "common_settings",
                "piano_roll",
                "keyboard",
                "player",
            ),
        )

    def test_default_theme_is_sky_blue(self) -> None:
        self.assertEqual(AppSettings().color_theme, "sky_blue")

    def test_new_settings_round_trip(self) -> None:
        with isolated_settings_directory() as settings_dir:
            save_settings(
                AppSettings(
                    countdown_seconds=2,
                    midi_sound_volume=70,
                    sound_source="synth",
                    dry_run=False,
                    countdown_sound=True,
                    game_countdown_sound=True,
                    auto_fit_note_range=True,
                    transpose_semitones=-7,
                    octave_shift=2,
                    humanize_timing=True,
                    chord_optimization=True,
                    chord_strum=True,
                    auto_sustain=True,
                    repeat_prevention=True,
                    playback_speed_percent=135,
                    sound_playback_mode="repeat_one",
                    language="ja",
                    color_theme="orange",
                    always_on_top=True,
                    tray_resident=True,
                    window_opacity=75,
                    ui_scale_percent=150,
                    window_width=1280,
                    window_height=720,
                    last_midi_folder=str(settings_dir / "midis"),
                    keyboard_play_shortcut="Ctrl+P",
                    keyboard_pause_shortcut="Ctrl+R",
                    keyboard_stop_shortcut="Ctrl+S",
                    shortcut_locked=False,
                    midi_input_device="USB MIDI",
                    input_conversion_mode="realtime",
                    key_bindings={60: "q", 61: "w"},
                    sustain_key="space",
                    octave_down_key="[",
                    octave_up_key="]",
                    panel_order=(
                        "player",
                        "keyboard",
                        "piano_roll",
                        "common_settings",
                        "input_conversion",
                    ),
                )
            )

            loaded = load_settings()
            self.assertFalse((settings_dir / "settings.json.tmp").exists())

        self.assertEqual(loaded.color_theme, "orange")
        self.assertEqual(loaded.sound_source, "synth")
        self.assertTrue(loaded.always_on_top)
        self.assertTrue(loaded.tray_resident)
        self.assertEqual(loaded.window_opacity, 75)
        self.assertEqual(loaded.ui_scale_percent, 150)
        self.assertEqual(loaded.window_width, 1280)
        self.assertEqual(loaded.window_height, 720)
        self.assertTrue(loaded.countdown_sound)
        self.assertTrue(loaded.game_countdown_sound)
        self.assertTrue(loaded.auto_fit_note_range)
        self.assertEqual(loaded.transpose_semitones, -7)
        self.assertEqual(loaded.octave_shift, 2)
        self.assertTrue(loaded.humanize_timing)
        self.assertTrue(loaded.chord_optimization)
        self.assertTrue(loaded.chord_strum)
        self.assertTrue(loaded.auto_sustain)
        self.assertTrue(loaded.repeat_prevention)
        self.assertEqual(loaded.playback_speed_percent, 135)
        self.assertEqual(loaded.sound_playback_mode, "repeat_one")
        self.assertTrue(loaded.last_midi_folder.endswith("midis"))
        self.assertEqual(loaded.keyboard_play_shortcut, "Ctrl+P")
        self.assertEqual(loaded.keyboard_pause_shortcut, "Ctrl+R")
        self.assertEqual(loaded.keyboard_stop_shortcut, "Ctrl+S")
        self.assertFalse(loaded.shortcut_locked)
        self.assertEqual(loaded.midi_input_device, "USB MIDI")
        self.assertEqual(loaded.input_conversion_mode, "realtime")
        self.assertEqual(loaded.panel_order[0], "player")
        key_bindings = normalized_key_bindings(loaded.key_bindings)
        self.assertEqual(key_bindings[60], "q")
        self.assertEqual(key_bindings[61], "w")
        self.assertEqual(key_bindings[62], "s")
        self.assertEqual(loaded.sustain_key, "space")
        self.assertEqual(loaded.octave_down_key, "[")
        self.assertEqual(loaded.octave_up_key, "]")

    def test_invalid_panel_order_is_repaired_without_duplicates(self) -> None:
        with isolated_settings_directory() as settings_dir:
            (settings_dir / "settings.json").write_text(
                '{"panel_order": ["player", "player", "unknown", "keyboard"]}',
                encoding="utf-8",
            )

            loaded = load_settings()

        self.assertEqual(loaded.panel_order[:2], ("player", "keyboard"))
        self.assertEqual(len(loaded.panel_order), 5)
        self.assertEqual(len(set(loaded.panel_order)), 5)

    def test_note_shift_settings_are_clamped(self) -> None:
        with isolated_settings_directory() as settings_dir:
            (settings_dir / "settings.json").write_text(
                '{"transpose_semitones": 99, "octave_shift": -99}',
                encoding="utf-8",
            )

            loaded = load_settings()

        self.assertEqual(loaded.transpose_semitones, 12)
        self.assertEqual(loaded.octave_shift, -3)

    def test_unknown_sound_source_uses_piano(self) -> None:
        with isolated_settings_directory() as settings_dir:
            (settings_dir / "settings.json").write_text(
                '{"sound_source":"missing"}',
                encoding="utf-8",
            )

            loaded = load_settings()

        self.assertEqual(loaded.sound_source, "piano")

    def test_legacy_manual_audio_buffer_settings_are_not_preserved(self) -> None:
        with isolated_settings_directory() as settings_dir:
            settings_path = settings_dir / "settings.json"
            settings_path.write_text(
                '{"audio_buffer_frames":512,"auto_audio_buffer":false}',
                encoding="utf-8",
            )

            loaded = load_settings()
            save_settings(loaded)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertFalse(hasattr(loaded, "audio_buffer_frames"))
        self.assertNotIn("audio_buffer_frames", saved)
        self.assertNotIn("auto_audio_buffer", saved)

    def test_previous_default_shortcuts_are_migrated(self) -> None:
        with isolated_settings_directory() as settings_dir:
            (settings_dir / "settings.json").write_text(
                '{"keyboard_play_shortcut":"F5",'
                '"keyboard_pause_shortcut":"F7",'
                '"keyboard_stop_shortcut":"F6"}',
                encoding="utf-8",
            )

            loaded = load_settings()

        self.assertEqual(loaded.keyboard_play_shortcut, "F9")
        self.assertEqual(loaded.keyboard_pause_shortcut, "F10")
        self.assertEqual(loaded.keyboard_stop_shortcut, "F11")

    def test_ten_percent_playback_speed_is_preserved(self) -> None:
        with isolated_settings_directory():
            save_settings(AppSettings(playback_speed_percent=10))

            loaded = load_settings()

        self.assertEqual(loaded.playback_speed_percent, 10)

    def test_unknown_sound_playback_mode_uses_off(self) -> None:
        with isolated_settings_directory() as settings_dir:
            (settings_dir / "settings.json").write_text(
                '{"sound_playback_mode":"unknown"}',
                encoding="utf-8",
            )

            loaded = load_settings()

        self.assertEqual(loaded.sound_playback_mode, "off")

    def test_interrupted_atomic_save_is_recovered(self) -> None:
        with isolated_settings_directory() as settings_dir:
            temporary_path = settings_dir / "settings.json.tmp"
            temporary_path.write_text('{"midi_sound_volume": 42}', encoding="utf-8")

            loaded = load_settings()
            error = consume_settings_error()

            self.assertEqual(loaded.midi_sound_volume, 42)
            self.assertIn("Recovered settings", error)
            self.assertTrue((settings_dir / "settings.json").exists())
            self.assertFalse(temporary_path.exists())

    def test_failed_atomic_replace_removes_temporary_file(self) -> None:
        with isolated_settings_directory() as settings_dir:
            with patch("settings.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    save_settings(AppSettings())

            temporary_path = settings_dir / "settings.json.tmp"
            self.assertFalse(temporary_path.exists())

    def test_frozen_app_uses_executable_directory(self) -> None:
        executable = Path("C:/portable/BPSR_MIDI_to_KEY_Player.exe")
        with (
            patch("settings.sys.frozen", True, create=True),
            patch("settings.sys.executable", str(executable)),
        ):
            from settings import _settings_path

            self.assertEqual(
                _settings_path(),
                executable.parent / "settings.json",
            )

if __name__ == "__main__":
    unittest.main()
