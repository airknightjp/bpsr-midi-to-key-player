from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from playlist_store import (
    Playlist,
    PlaylistStore,
    PlaylistTrack,
    playlist_total_duration,
)


class PlaylistStoreTests(unittest.TestCase):
    def test_save_and_load_preserve_playlist_order_and_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "playlists.json"
            store = PlaylistStore(path)
            playlists = [
                Playlist(
                    playlist_id="first",
                    name="Set 1",
                    tracks=(
                        PlaylistTrack(
                            Path("C:/Music/one.mid"),
                            "one.mid",
                            "01:23",
                        ),
                        PlaylistTrack(
                            Path("C:/Music/two.mid"),
                            "two.mid",
                            "02:34",
                        ),
                    ),
                )
            ]

            store.save(playlists)

            self.assertEqual(store.load(), playlists)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertFalse(path.with_name("playlists.json.tmp").exists())

    def test_invalid_playlist_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "playlists.json"
            path.write_text("{invalid", encoding="utf-8")

            self.assertEqual(PlaylistStore(path).load(), [])

    def test_total_duration_sums_tracks_and_reports_unknown_values(self) -> None:
        self.assertEqual(playlist_total_duration(()), "00:00")
        self.assertEqual(
            playlist_total_duration(
                (
                    PlaylistTrack(Path("one.mid"), "one.mid", "01:23"),
                    PlaylistTrack(Path("two.mid"), "two.mid", "02:37"),
                )
            ),
            "04:00",
        )
        self.assertEqual(
            playlist_total_duration(
                (PlaylistTrack(Path("unknown.mid"), "unknown.mid"),)
            ),
            "--:--",
        )


if __name__ == "__main__":
    unittest.main()
