from __future__ import annotations

import unittest

from i18n import COLOR_THEME_NAMES, TEXT, normalize_color_theme


class I18nTests(unittest.TestCase):
    def test_log_tab_uses_short_label_in_every_language(self) -> None:
        self.assertEqual(TEXT["ja"]["playback_log"], "\u30ed\u30b0")
        self.assertEqual(TEXT["en"]["playback_log"], "Log")
        self.assertEqual(TEXT["zh"]["playback_log"], "\u65e5\u5fd7")

    def test_performance_optimization_group_exists_in_every_language(self) -> None:
        self.assertEqual(
            TEXT["ja"]["performance_optimization_settings"],
            "\u6f14\u594f\u6700\u9069\u5316",
        )
        self.assertEqual(
            TEXT["en"]["performance_optimization_settings"],
            "Performance Optimization",
        )
        self.assertEqual(
            TEXT["zh"]["performance_optimization_settings"],
            "\u6f14\u594f\u4f18\u5316",
        )

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

    def test_performance_option_labels_use_current_names(self) -> None:
        expected = {
            "en": ("Chord voicing", "Natural timing", "In-chord onset spread"),
            "ja": (
                "\u548c\u97f3\u914d\u7f6e",
                "\u30bf\u30a4\u30df\u30f3\u30b0\u306e\u81ea\u7136\u5316",
                "\u548c\u97f3\u5185\u306e\u767a\u97f3\u5dee",
            ),
            "zh": (
                "\u548c\u5f26\u914d\u7f6e",
                "\u65f6\u5e8f\u81ea\u7136\u5316",
                "\u548c\u5f26\u5185\u53d1\u97f3\u5dee",
            ),
        }

        for language, labels in expected.items():
            with self.subTest(language=language):
                translations = TEXT[language]
                self.assertEqual(translations["chord_optimization"], labels[0])
                self.assertEqual(translations["humanize_timing"], labels[1])
                self.assertEqual(translations["chord_strum"], labels[2])

    def test_optimization_progress_exists_for_all_languages(self) -> None:
        for translations in TEXT.values():
            self.assertIn("{percent}", translations["optimization_progress"])


if __name__ == "__main__":
    unittest.main()
