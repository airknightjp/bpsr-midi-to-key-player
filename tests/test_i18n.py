from __future__ import annotations

import unittest

from i18n import COLOR_THEME_NAMES, TEXT, normalize_color_theme


class I18nTests(unittest.TestCase):
    def test_file_menu_and_exit_labels_exist_for_all_languages(self) -> None:
        expected = {
            "en": ("File", "Exit"),
            "ja": ("\u30d5\u30a1\u30a4\u30eb", "\u7d42\u4e86"),
            "zh": ("\u6587\u4ef6", "\u9000\u51fa"),
        }

        for language, labels in expected.items():
            with self.subTest(language=language):
                translations = TEXT[language]
                self.assertEqual(translations["menu_midi"], labels[0])
                self.assertEqual(translations["exit"], labels[1])

    def test_disabled_button_text_uses_locked_wording(self) -> None:
        self.assertEqual(TEXT["en"]["disabled"], "Locked")
        self.assertEqual(TEXT["ja"]["disabled"], "\u30ed\u30c3\u30af\u4e2d")
        self.assertEqual(TEXT["zh"]["disabled"], "\u5df2\u9501\u5b9a")

    def test_log_messages_are_english_for_all_languages(self) -> None:
        expected = {
            "folder_loaded_log": "Loaded folder {folder}: {count} MIDI files",
            "loaded_log": "Loaded {name}: {event_count} events, {duration:.2f}s, channels {channels}",
            "key_playback_started": "Key playback started ({mode})",
            "sound_playback_stopped": "MIDI sound playback stopped",
            "dry_run_mode": "test mode",
            "real_keyboard_output": "real keyboard output",
        }

        for language, translations in TEXT.items():
            with self.subTest(language=language):
                for key, value in expected.items():
                    self.assertEqual(translations[key], value)

    def test_color_theme_names_include_pink_for_all_languages(self) -> None:
        for language, theme_names in COLOR_THEME_NAMES.items():
            with self.subTest(language=language):
                self.assertIn("pink", theme_names)
                self.assertIn("sky_blue", theme_names)
                self.assertNotIn("original", theme_names)

    def test_pink_color_theme_is_valid(self) -> None:
        self.assertEqual(normalize_color_theme("pink"), "pink")

    def test_sky_blue_color_theme_is_valid_and_default(self) -> None:
        self.assertEqual(normalize_color_theme("sky_blue"), "sky_blue")
        self.assertEqual(normalize_color_theme("missing"), "sky_blue")

    def test_track_channel_compact_labels_exist_for_all_languages(self) -> None:
        expected = {
            "en": ("Track (T) / Channel (C)", "T1 - C16"),
            "ja": (
                "\u30c8\u30e9\u30c3\u30af(T)\uff0f\u30c1\u30e3\u30f3\u30cd\u30eb(C)",
                "T1 - C16",
            ),
            "zh": (
                "\u97f3\u8f68(T)\uff0f\u901a\u9053(C)",
                "T1 - C16",
            ),
        }

        for language, labels in expected.items():
            with self.subTest(language=language):
                translations = TEXT[language]
                self.assertEqual(translations["channels"], labels[0])
                self.assertEqual(
                    translations["track_channel"].format(track=1, channel=16),
                    labels[1],
                )

    def test_note_range_column_label_exists_for_all_languages(self) -> None:
        self.assertEqual(TEXT["en"]["note_range"], "Range")
        self.assertEqual(TEXT["ja"]["note_range"], "\u97f3\u57df")
        self.assertEqual(TEXT["zh"]["note_range"], "\u97f3\u57df")

    def test_waiting_status_exists_for_all_languages(self) -> None:
        for translations in TEXT.values():
            self.assertEqual(translations["waiting"], "waiting..")


if __name__ == "__main__":
    unittest.main()
