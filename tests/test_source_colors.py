from __future__ import annotations

import unittest

from itertools import combinations

from source_colors import contrasting_text_color, track_channel_color


def _rgb_distance(first: str, second: str) -> float:
    first_rgb = tuple(int(first[index:index + 2], 16) for index in (1, 3, 5))
    second_rgb = tuple(int(second[index:index + 2], 16) for index in (1, 3, 5))
    return sum(
        (left - right) ** 2
        for left, right in zip(first_rgb, second_rgb)
    ) ** 0.5


class TrackChannelColorTests(unittest.TestCase):
    def test_colors_are_stable_and_distinct_for_common_sources(self) -> None:
        colors = [
            track_channel_color(track, channel)
            for track in range(4)
            for channel in range(16)
        ]

        self.assertEqual(colors, [
            track_channel_color(track, channel)
            for track in range(4)
            for channel in range(16)
        ])
        self.assertEqual(len(colors), len(set(colors)))

    def test_realtime_channels_have_stable_colors(self) -> None:
        self.assertNotEqual(
            track_channel_color(-1, 0),
            track_channel_color(-1, 1),
        )

    def test_common_track_and_channel_sequences_are_visually_separated(self) -> None:
        groups = (
            [track_channel_color(track, 0) for track in range(6)],
            [track_channel_color(0, channel) for channel in range(6)],
        )

        for colors in groups:
            for first, second in combinations(colors, 2):
                self.assertGreater(_rgb_distance(first, second), 55)

    def test_source_text_color_tracks_background_brightness(self) -> None:
        self.assertEqual(contrasting_text_color("#F0D000"), "#101820")
        self.assertEqual(contrasting_text_color("#003060"), "#FFFFFF")


if __name__ == "__main__":
    unittest.main()
