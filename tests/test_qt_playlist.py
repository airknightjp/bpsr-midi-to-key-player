from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem

from app_controller import AppController
from app_state import MidiListRow
from playlist_store import Playlist, PlaylistStore
from qt_playlist import (
    MIDI_PATHS_MIME_TYPE,
    MidiLibraryTable,
    PlaylistEditorDialog,
)
from settings import AppSettings


class QtPlaylistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_midi_table_drag_contains_selected_midi_path(self) -> None:
        table = MidiLibraryTable(1, 1)
        item = QTableWidgetItem("song.mid")
        item.setData(Qt.ItemDataRole.UserRole, "C:/Music/song.mid")
        table.setItem(0, 0, item)
        table.selectRow(0)

        with patch("qt_playlist.QDrag") as drag_class:
            table.startDrag(Qt.DropAction.CopyAction)

        mime_data = drag_class.return_value.setMimeData.call_args.args[0]
        self.assertTrue(mime_data.hasFormat(MIDI_PATHS_MIME_TYPE))
        self.assertIn(
            b"C:/Music/song.mid",
            bytes(mime_data.data(MIDI_PATHS_MIME_TYPE)),
        )

    def test_editor_adds_dropped_track_and_saves_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            midi_path = root / "song.mid"
            midi_path.write_bytes(b"MThd")
            store = PlaylistStore(root / "playlists.json")
            controller = AppController(
                AppSettings(),
                playlist_store=store,
            )
            controller.state.playlists = [Playlist.create("Set")]
            controller.state.selected_playlist_index = 0
            controller.state.midi_rows = [
                MidiListRow(
                    midi_path,
                    "song.mid",
                    root.name,
                    "01:23",
                )
            ]
            dialog = PlaylistEditorDialog(controller, "en")

            dialog._add_paths([str(midi_path)])
            self.assertEqual(
                dialog.track_table.horizontalHeaderItem(0).text(),
                "Name",
            )
            self.assertEqual(
                dialog.track_table.horizontalHeaderItem(1).text(),
                "Duration",
            )
            self.assertEqual(dialog.track_table.columnCount(), 2)
            self.assertEqual(dialog.track_table.item(0, 0).text(), "song")
            self.assertEqual(dialog.track_table.item(0, 1).text(), "01:23")
            self.assertTrue(
                dialog.track_table.horizontalHeaderItem(0).textAlignment()
                & Qt.AlignmentFlag.AlignLeft
            )
            self.assertTrue(
                dialog.track_table.item(0, 0).textAlignment()
                & Qt.AlignmentFlag.AlignLeft
            )
            self.assertEqual(
                dialog.total_duration_label.text(),
                "Total duration: 01:23",
            )
            self.assertEqual(
                dialog.total_duration_label.parentWidget(),
                dialog.track_table.parentWidget(),
            )
            dialog.show()
            self.application.processEvents()
            self.assertEqual(
                dialog.playlist_drop_hint_label.geometry().center().y(),
                dialog.total_duration_label.geometry().center().y(),
            )
            self.assertGreater(
                dialog.total_duration_label.x(),
                dialog.playlist_drop_hint_label.geometry().right(),
            )
            dialog._save()

            loaded = store.load()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].name, "Set")
            self.assertEqual(len(loaded[0].tracks), 1)
            self.assertEqual(loaded[0].tracks[0].path, midi_path)
            self.assertEqual(loaded[0].tracks[0].duration, "01:23")
            dialog.close()
            controller.shutdown()

    def test_unsaved_confirmation_buttons_follow_language(self) -> None:
        controller = AppController(AppSettings())
        dialog = PlaylistEditorDialog(controller, "ja")
        message_box = dialog._make_unsaved_message_box()

        self.assertEqual(
            dialog.total_duration_label.text(),
            "\u5408\u8a08\u6642\u9593: 00:00",
        )
        self.assertEqual(
            message_box.button(QMessageBox.StandardButton.Save).text(),
            "\u4fdd\u5b58",
        )
        self.assertEqual(
            message_box.button(QMessageBox.StandardButton.Discard).text(),
            "\u4fdd\u5b58\u3057\u306a\u3044",
        )
        self.assertEqual(
            message_box.button(QMessageBox.StandardButton.Cancel).text(),
            "\u30ad\u30e3\u30f3\u30bb\u30eb",
        )
        message_box.close()
        dialog.close()
        controller.shutdown()


if __name__ == "__main__":
    unittest.main()
