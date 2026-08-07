from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app_database import DATABASE_FILE_NAME
from playlist_store import (
    Playlist,
    PlaylistStore,
    PlaylistTrack,
    playlist_total_duration,
)


class PlaylistStoreTests(unittest.TestCase):
    def test_save_and_load_preserve_playlist_order_and_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / DATABASE_FILE_NAME
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
            self.assertTrue(path.exists())

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
