from __future__ import annotations

import unittest

from i18n import COLOR_THEME_NAMES, TEXT, normalize_color_theme


class I18nTests(unittest.TestCase):
    def test_conversion_sound_labels_exist_in_every_language(self) -> None:
        self.assertEqual(TEXT["en"]["conversion_sound"], "Play sound")
        self.assertEqual(
            TEXT["ja"]["conversion_sound"],
            "\u97f3\u3092\u9cf4\u3089\u3059",
        )
        self.assertEqual(
            TEXT["zh"]["conversion_sound"],
            "\u64ad\u653e\u58f0\u97f3",
        )

    def test_file_menu_and_exit_labels_exist_for_all_languages(self) -> None:
        expected = {
            "en": ("File", "Save Settings", "Exit"),
            "ja": (
                "\u30d5\u30a1\u30a4\u30eb",
                "\u8a2d\u5b9a\u3092\u4fdd\u5b58",
                "\u7d42\u4e86",
            ),
            "zh": (
                "\u6587\u4ef6",
                "\u4fdd\u5b58\u8bbe\u7f6e",
                "\u9000\u51fa",
            ),
        }

        for language, labels in expected.items():
            with self.subTest(language=language):
                translations = TEXT[language]
                self.assertEqual(translations["menu_midi"], labels[0])
                self.assertEqual(translations["save_settings"], labels[1])
                self.assertEqual(translations["exit"], labels[2])

    def test_release_notes_labels_exist_for_all_languages(self) -> None:
        expected = {
            "en": (
                "Release Notes",
                "Don't show again",
                "in-app software synthesizer",
            ),
            "ja": (
                "\u30ea\u30ea\u30fc\u30b9\u30ce\u30fc\u30c8",
                "\u4eca\u5f8c\u8868\u793a\u3057\u306a\u3044",
                "\u30a2\u30d7\u30ea\u5185\u30bd\u30d5\u30c8\u30a6\u30a7\u30a2\u97f3\u6e90",
            ),
            "zh": (
                "\u53d1\u884c\u8bf4\u660e",
                "\u4ee5\u540e\u4e0d\u518d\u663e\u793a",
                "\u5e94\u7528\u5185\u8f6f\u4ef6\u5408\u6210\u5668",
            ),
        }
        for language, labels in expected.items():
            with self.subTest(language=language):
                translations = TEXT[language]
                self.assertEqual(translations["release_notes"], labels[0])
                self.assertEqual(translations["dont_show_again"], labels[1])
                content = translations["release_notes_content"]
                self.assertTrue(content.startswith("v1.6.1"))
                self.assertIn(labels[2], content)
                self.assertIn("Qt", content)
                self.assertIn("Buffer", content)

    def test_view_scale_and_advanced_settings_labels_exist_for_all_languages(self) -> None:
        expected = {
            "en": ("Scale", "Advanced Settings"),
            "ja": ("\u62e1\u5927\u7387", "\u8a73\u7d30\u8a2d\u5b9a"),
            "zh": ("\u7f29\u653e\u6bd4\u4f8b", "\u9ad8\u7ea7\u8bbe\u7f6e"),
        }

        for language, labels in expected.items():
            with self.subTest(language=language):
                translations = TEXT[language]
                self.assertEqual(translations["ui_scale"], labels[0])
                self.assertEqual(translations["midi_sound_settings"], labels[1])

    def test_panel_visibility_labels_exist_for_all_languages(self) -> None:
        expected = {
            "en": (
                "Basic Screen",
                "Advanced Settings",
                "Rhythm Game",
                "Keyboard",
                "Player",
            ),
            "ja": (
                "\u57fa\u672c\u753b\u9762",
                "\u8a73\u7d30\u8a2d\u5b9a",
                "\u97f3\u30b2\u30fc",
                "\u9375\u76e4",
                "\u30d7\u30ec\u30a4\u30e4\u30fc",
            ),
            "zh": (
                "\u57fa\u672c\u754c\u9762",
                "\u8be6\u7ec6\u8bbe\u7f6e",
                "\u97f3\u4e50\u6e38\u620f",
                "\u952e\u76d8",
                "\u64ad\u653e\u5668",
            ),
        }
        keys = (
            "basic_screen_panel",
            "advanced_settings_panel",
            "rhythm_game_panel",
            "keyboard_panel",
            "player_panel",
        )
        for language, labels in expected.items():
            with self.subTest(language=language):
                translations = TEXT[language]
                self.assertEqual(
                    tuple(translations[key] for key in keys),
                    labels,
                )

    def test_conversion_stop_labels_use_end_in_every_language(self) -> None:
        expected = {
            "en": "End",
            "ja": "\u7d42\u4e86",
            "zh": "\u7ed3\u675f",
        }
        for language, label in expected.items():
            with self.subTest(language=language):
                self.assertEqual(TEXT[language]["stop_keys"], label)
                self.assertEqual(TEXT[language]["stop_midi_input"], label)

    def test_update_labels_exist_for_all_languages(self) -> None:
        for language, translations in TEXT.items():
            with self.subTest(language=language):
                self.assertTrue(translations["check_for_updates"])
                self.assertTrue(translations["no_updates"])
                self.assertIn("{error}", translations["update_check_failed"])

    def test_transport_knob_labels_are_localized(self) -> None:
        expected = {
            "en": ("Volume", "Speed", "Transpose", "Octave shift"),
            "ja": (
                "\u97f3\u91cf",
                "\u901f\u5ea6",
                "\u30c8\u30e9\u30f3\u30b9\u30dd\u30fc\u30ba",
                "\u30aa\u30af\u30bf\u30fc\u30d6\u30b7\u30d5\u30c8",
            ),
            "zh": (
                "\u97f3\u91cf",
                "\u901f\u5ea6",
                "\u79fb\u8c03",
                "\u516b\u5ea6\u79fb\u4f4d",
            ),
        }
        for language, translations in TEXT.items():
            with self.subTest(language=language):
                self.assertEqual(
                    (
                        translations["midi_sound_volume"],
                        translations["playback_speed"],
                        translations["transpose_semitones"],
                        translations["octave_shift"],
                    ),
                    expected[language],
                )

    def test_playlist_label_is_localized(self) -> None:
        expected = {
            "en": "Playlist",
            "ja": "\u30d7\u30ec\u30a4\u30ea\u30b9\u30c8",
            "zh": "\u64ad\u653e\u5217\u8868",
        }
        for language, translations in TEXT.items():
            with self.subTest(language=language):
                self.assertEqual(translations["playlist"], expected[language])

    def test_mute_labels_are_localized(self) -> None:
        expected = {
            "en": ("Mute", "Unmute"),
            "ja": (
                "\u30df\u30e5\u30fc\u30c8",
                "\u30df\u30e5\u30fc\u30c8\u89e3\u9664",
            ),
            "zh": ("\u9759\u97f3", "\u53d6\u6d88\u9759\u97f3"),
        }
        for language, translations in TEXT.items():
            with self.subTest(language=language):
                self.assertEqual(
                    (translations["mute"], translations["unmute"]),
                    expected[language],
                )

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

    def test_sky_blue_theme_is_first_without_text_marker(self) -> None:
        for language, theme_names in COLOR_THEME_NAMES.items():
            with self.subTest(language=language):
                self.assertEqual(next(iter(theme_names)), "sky_blue")
                self.assertNotIn("\u2605", theme_names["sky_blue"])

    def test_folder_column_label_exists_for_all_languages(self) -> None:
        self.assertEqual(TEXT["en"]["folder"], "Folder")
        self.assertEqual(TEXT["ja"]["folder"], "\u30d5\u30a9\u30eb\u30c0")
        self.assertEqual(TEXT["zh"]["folder"], "\u6587\u4ef6\u5939")

    def test_waiting_status_exists_for_all_languages(self) -> None:
        for translations in TEXT.values():
            self.assertEqual(translations["waiting"], "waiting..")

    def test_performance_option_labels_use_current_names(self) -> None:
        expected = {
            "en": (
                "Chord revoicing",
                "Timing variation",
                "Chord spread",
                "Automatic sustain generation",
            ),
            "ja": (
                "\u548c\u97f3\u306e\u518d\u914d\u7f6e",
                "\u30bf\u30a4\u30df\u30f3\u30b0\u306e\u5206\u6563",
                "\u548c\u97f3\u306e\u5206\u6563",
                "\u30b5\u30b9\u30c6\u30a3\u30f3\u306e\u81ea\u52d5\u751f\u6210",
            ),
            "zh": (
                "\u548c\u5f26\u91cd\u6392",
                "\u65f6\u5e8f\u5206\u6563",
                "\u548c\u5f26\u5206\u6563",
                "\u81ea\u52a8\u5ef6\u97f3\u751f\u6210",
            ),
        }

        for language, labels in expected.items():
            with self.subTest(language=language):
                translations = TEXT[language]
                self.assertEqual(translations["chord_optimization"], labels[0])
                self.assertEqual(translations["humanize_timing"], labels[1])
                self.assertEqual(translations["chord_strum"], labels[2])
                self.assertEqual(translations["auto_sustain"], labels[3])

    def test_optimization_progress_exists_for_all_languages(self) -> None:
        for translations in TEXT.values():
            self.assertIn("{percent}", translations["optimization_progress"])


if __name__ == "__main__":
    unittest.main()
