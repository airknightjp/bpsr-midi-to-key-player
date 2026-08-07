from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app_database import ApplicationDatabase, DATABASE_FILE_NAME
from config import normalized_key_bindings
from settings import AppSettings, database_path, load_settings, save_settings


@contextmanager
def isolated_settings_directory():
    with tempfile.TemporaryDirectory() as temp_dir:
        settings_dir = Path(temp_dir)
        with patch("settings._application_directory", return_value=settings_dir):
            yield settings_dir


def save_raw_settings(settings_dir: Path, payload: dict[str, object]) -> None:
    ApplicationDatabase(settings_dir / DATABASE_FILE_NAME).save_settings(payload)


def load_raw_settings(settings_dir: Path) -> dict[str, object]:
    return ApplicationDatabase(settings_dir / DATABASE_FILE_NAME).load_settings()


class SettingsTests(unittest.TestCase):
    def test_display_and_shortcut_defaults(self) -> None:
        settings = AppSettings()

        self.assertEqual(settings.countdown_seconds, 0)
        self.assertEqual(settings.ui_scale_percent, 100)
        self.assertEqual(settings.window_width, 900)
        self.assertEqual(settings.midi_column_widths, (630, 180, 80))
        self.assertEqual(settings.playlist_name_width, 240)
        self.assertEqual(settings.keyboard_play_shortcut, "F9")
        self.assertEqual(settings.keyboard_pause_shortcut, "F10")
        self.assertEqual(settings.keyboard_stop_shortcut, "F11")
        self.assertFalse(hasattr(settings, "auto_audio_buffer"))
        self.assertFalse(hasattr(settings, "automatic_audio_buffer_frames"))
        self.assertFalse(hasattr(settings, "minimum_stable_qt_frames"))
        self.assertFalse(hasattr(settings, "qt_audio_environment"))
        self.assertFalse(hasattr(settings, "audio_tuning_profiles"))
        self.assertFalse(hasattr(settings, "qt_frames_retest_after"))
        self.assertEqual(settings.audio_qt_frames, 1_024)
        self.assertEqual(settings.audio_buffer_frames, 512)
        self.assertEqual(settings.audio_response_frames, 256)
        self.assertEqual(settings.audio_chunk_frames, 1_024)
        self.assertEqual(settings.audio_fallback_interval_ms, 4)
        self.assertEqual(settings.input_conversion_mode, "midi_file")
        self.assertEqual(settings.sound_playback_mode, "off")
        self.assertEqual(settings.arrangement_quality, "beta")
        self.assertTrue(settings.use_piano_arrangement)
        self.assertTrue(settings.play_sound)
        self.assertFalse(settings.hide_release_notes_on_startup)
        self.assertFalse(settings.run_as_administrator)
        self.assertEqual(settings.last_update_check_at, 0)
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
        self.assertEqual(
            settings.section_visibility,
            {
                "input_conversion": True,
                "common_settings": True,
                "piano_roll": True,
                "keyboard": True,
                "player": True,
            },
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
                    arrangement_quality="beta",
                    use_piano_arrangement=False,
                    play_sound=False,
                    countdown_sound=True,
                    game_countdown_sound=True,
                    auto_fit_note_range=True,
                    transpose_semitones=-7,
                    octave_shift=2,
                    humanize_timing=True,
                    chord_strum=True,
                    chord_optimization=True,
                    auto_sustain=True,
                    repeat_prevention=True,
                    playback_speed_percent=135,
                    sound_playback_mode="repeat_one",
                    language="ja",
                    color_theme="orange",
                    always_on_top=True,
                    tray_resident=True,
                    run_as_administrator=True,
                    hide_release_notes_on_startup=True,
                    window_opacity=75,
                    ui_scale_percent=150,
                    window_width=1280,
                    window_height=720,
                    midi_column_widths=(720, 240, 96),
                    playlist_name_width=320,
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
                    audio_qt_frames=512,
                    audio_buffer_frames=256,
                    audio_response_frames=128,
                    audio_chunk_frames=512,
                    audio_fallback_interval_ms=8,
                    last_update_check_at=1_789_123_456,
                    panel_order=(
                        "player",
                        "keyboard",
                        "piano_roll",
                        "common_settings",
                        "input_conversion",
                    ),
                    section_visibility={
                        "input_conversion": True,
                        "common_settings": False,
                        "piano_roll": False,
                        "keyboard": True,
                        "player": False,
                    },
                )
            )

            saved_payload = load_raw_settings(settings_dir)
            loaded = load_settings()
            self.assertTrue((settings_dir / DATABASE_FILE_NAME).exists())

        self.assertFalse(saved_payload["play_sound"])
        self.assertNotIn("dry_run", saved_payload)
        self.assertTrue(saved_payload["chord_optimization"])
        self.assertNotIn("melody_priority", saved_payload)
        self.assertNotIn("automatic_audio_buffer_frames", saved_payload)
        self.assertNotIn("minimum_stable_qt_frames", saved_payload)
        self.assertNotIn("qt_audio_environment", saved_payload)
        self.assertEqual(loaded.color_theme, "orange")
        self.assertEqual(loaded.sound_source, "synth")
        self.assertEqual(loaded.arrangement_quality, "beta")
        self.assertFalse(loaded.use_piano_arrangement)
        self.assertTrue(loaded.always_on_top)
        self.assertTrue(loaded.tray_resident)
        self.assertTrue(loaded.run_as_administrator)
        self.assertTrue(loaded.hide_release_notes_on_startup)
        self.assertEqual(loaded.window_opacity, 75)
        self.assertEqual(loaded.ui_scale_percent, 150)
        self.assertEqual(loaded.window_width, 1280)
        self.assertEqual(loaded.window_height, 720)
        self.assertEqual(loaded.midi_column_widths, (720, 240, 96))
        self.assertEqual(loaded.playlist_name_width, 320)
        self.assertTrue(loaded.countdown_sound)
        self.assertTrue(loaded.game_countdown_sound)
        self.assertFalse(loaded.play_sound)
        self.assertTrue(loaded.auto_fit_note_range)
        self.assertEqual(loaded.transpose_semitones, -7)
        self.assertEqual(loaded.octave_shift, 2)
        self.assertTrue(loaded.humanize_timing)
        self.assertTrue(loaded.chord_strum)
        self.assertTrue(loaded.chord_optimization)
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
        self.assertEqual(
            loaded.section_visibility,
            {
                "input_conversion": True,
                "common_settings": False,
                "piano_roll": False,
                "keyboard": True,
                "player": False,
            },
        )
        key_bindings = normalized_key_bindings(loaded.key_bindings)
        self.assertEqual(key_bindings[60], "q")
        self.assertEqual(key_bindings[61], "w")
        self.assertEqual(key_bindings[62], "s")
        self.assertEqual(loaded.sustain_key, "space")
        self.assertEqual(loaded.octave_down_key, "[")
        self.assertEqual(loaded.octave_up_key, "]")
        self.assertEqual(loaded.audio_qt_frames, 512)
        self.assertEqual(loaded.audio_buffer_frames, 256)
        self.assertEqual(loaded.audio_response_frames, 128)
        self.assertEqual(loaded.audio_chunk_frames, 512)
        self.assertEqual(loaded.audio_fallback_interval_ms, 8)
        self.assertEqual(loaded.last_update_check_at, 1_789_123_456)

    def test_midi_column_widths_are_clamped_or_reset_when_loaded(self) -> None:
        with isolated_settings_directory() as settings_dir:
            save_raw_settings(
                settings_dir,
                {"midi_column_widths": [10, 180, 5000, 90]},
            )
            clamped = load_settings()
            save_raw_settings(settings_dir, {"midi_column_widths": [630, 180]})
            reset = load_settings()

        self.assertEqual(clamped.midi_column_widths, (40, 180, 2000))
        self.assertEqual(reset.midi_column_widths, (630, 180, 80))

    def test_legacy_audio_learning_keys_are_discarded(self) -> None:
        with isolated_settings_directory() as settings_dir:
            save_raw_settings(
                settings_dir,
                {
                    "minimum_stable_qt_frames": 333,
                    "qt_audio_environment": "old-device",
                    "automatic_audio_buffer_frames": 2048,
                    "qt_frames_retest_after": 1_800_000_000,
                },
            )

            loaded = load_settings()
            save_settings(loaded)
            saved = load_raw_settings(settings_dir)

        self.assertFalse(hasattr(loaded, "audio_tuning_profiles"))
        self.assertNotIn("minimum_stable_qt_frames", saved)
        self.assertNotIn("qt_audio_environment", saved)
        self.assertNotIn("automatic_audio_buffer_frames", saved)
        self.assertNotIn("qt_frames_retest_after", saved)
        self.assertNotIn("audio_tuning_profiles", saved)

    def test_invalid_panel_order_is_repaired_without_duplicates(self) -> None:
        with isolated_settings_directory() as settings_dir:
            save_raw_settings(
                settings_dir,
                {"panel_order": ["player", "player", "unknown", "keyboard"]},
            )

            loaded = load_settings()

        self.assertEqual(loaded.panel_order[:2], ("player", "keyboard"))
        self.assertEqual(len(loaded.panel_order), 5)
        self.assertEqual(len(set(loaded.panel_order)), 5)

    def test_invalid_section_visibility_values_use_visible_defaults(self) -> None:
        with isolated_settings_directory() as settings_dir:
            save_raw_settings(
                settings_dir,
                {
                    "section_visibility": {
                        "input_conversion": False,
                        "common_settings": "false",
                        "piano_roll": True,
                        "unknown": False,
                    }
                },
            )

            loaded = load_settings()

        self.assertEqual(
            loaded.section_visibility,
            {
                "input_conversion": False,
                "common_settings": True,
                "piano_roll": True,
                "keyboard": True,
                "player": True,
            },
        )

    def test_note_shift_settings_are_clamped(self) -> None:
        with isolated_settings_directory() as settings_dir:
            save_raw_settings(
                settings_dir,
                {"transpose_semitones": 99, "octave_shift": -99},
            )

            loaded = load_settings()

        self.assertEqual(loaded.transpose_semitones, 12)
        self.assertEqual(loaded.octave_shift, -3)

    def test_unknown_sound_source_uses_piano(self) -> None:
        with isolated_settings_directory() as settings_dir:
            save_raw_settings(settings_dir, {"sound_source": "missing"})

            loaded = load_settings()

        self.assertEqual(loaded.sound_source, "piano")

    def test_manual_audio_buffer_setting_is_preserved(self) -> None:
        with isolated_settings_directory() as settings_dir:
            save_raw_settings(
                settings_dir,
                {"audio_buffer_frames": 512, "auto_audio_buffer": False},
            )

            loaded = load_settings()
            save_settings(loaded)
            saved = load_raw_settings(settings_dir)

        self.assertEqual(loaded.audio_buffer_frames, 512)
        self.assertEqual(saved["audio_buffer_frames"], 512)
        self.assertNotIn("auto_audio_buffer", saved)

    def test_previous_default_shortcuts_are_migrated(self) -> None:
        with isolated_settings_directory() as settings_dir:
            save_raw_settings(
                settings_dir,
                {
                    "keyboard_play_shortcut": "F5",
                    "keyboard_pause_shortcut": "F7",
                    "keyboard_stop_shortcut": "F6",
                },
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
            save_raw_settings(settings_dir, {"sound_playback_mode": "unknown"})

            loaded = load_settings()

        self.assertEqual(loaded.sound_playback_mode, "off")

    def test_frozen_app_uses_executable_directory(self) -> None:
        executable = Path("C:/portable/BPSR_MIDI_to_KEY_Player.exe")
        with (
            patch("settings.sys.frozen", True, create=True),
            patch("settings.sys.executable", str(executable)),
        ):
            self.assertEqual(
                database_path(),
                executable.parent / DATABASE_FILE_NAME,
            )

if __name__ == "__main__":
    unittest.main()
