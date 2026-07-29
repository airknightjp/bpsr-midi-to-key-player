from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, Qt, Signal
from PySide6.QtGui import QCloseEvent, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_controller import AppController
from i18n import TEXT
from playlist_store import Playlist, PlaylistTrack, playlist_total_duration


MIDI_PATHS_MIME_TYPE = "application/x-bpsr-midi-paths"


class MidiLibraryTable(QTableWidget):
    def __init__(self, rows: int, columns: int, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, _supported_actions: Qt.DropAction) -> None:
        rows = sorted({index.row() for index in self.selectedIndexes()})
        paths: list[str] = []
        for row in rows:
            item = self.item(row, 0)
            if item is None:
                continue
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if path:
                paths.append(path)
        if not paths:
            return
        mime_data = QMimeData()
        mime_data.setData(
            MIDI_PATHS_MIME_TYPE,
            QByteArray(json.dumps(paths).encode("utf-8")),
        )
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)


class PlaylistDropTable(QTableWidget):
    pathsDropped = Signal(list)

    def __init__(self, rows: int, columns: int, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(MIDI_PATHS_MIME_TYPE):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(MIDI_PATHS_MIME_TYPE):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not event.mimeData().hasFormat(MIDI_PATHS_MIME_TYPE):
            event.ignore()
            return
        try:
            raw_paths = json.loads(
                bytes(
                    event.mimeData().data(MIDI_PATHS_MIME_TYPE)
                ).decode("utf-8")
            )
        except (UnicodeError, json.JSONDecodeError):
            event.ignore()
            return
        paths = [
            path
            for path in raw_paths
            if isinstance(path, str) and path.strip()
        ] if isinstance(raw_paths, list) else []
        if not paths:
            event.ignore()
            return
        self.pathsDropped.emit(paths)
        event.acceptProposedAction()


class PlaylistEditorDialog(QDialog):
    def __init__(
        self,
        controller: AppController,
        language: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.language = language
        self.text = TEXT[language]
        self.playlists = list(controller.state.playlists)
        self._dirty = False
        self.setObjectName("PlaylistEditorDialog")
        self.setWindowTitle(self.text["playlist_editor"])
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._build_ui()
        self._refresh_playlist_list()
        scale = max(1.0, controller.state.ui_scale_percent / 100.0)
        self.resize(round(720 * scale), round(430 * scale))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        content = QHBoxLayout()
        content.setSpacing(10)
        root.addLayout(content, 1)

        playlist_pane = QWidget()
        playlist_layout = QVBoxLayout(playlist_pane)
        playlist_layout.setContentsMargins(0, 0, 0, 0)
        playlist_layout.setSpacing(6)
        playlist_layout.addWidget(QLabel(self.text["playlist_names"]))
        self.playlist_list = QListWidget()
        self.playlist_list.setObjectName("PlaylistEditorList")
        self.playlist_list.currentRowChanged.connect(self._playlist_selected)
        playlist_layout.addWidget(self.playlist_list, 1)
        playlist_buttons = QHBoxLayout()
        playlist_buttons.setSpacing(4)
        self.new_button = QPushButton(self.text["new"])
        self.rename_button = QPushButton(self.text["rename"])
        self.delete_button = QPushButton(self.text["delete"])
        self.new_button.clicked.connect(self._create_playlist)
        self.rename_button.clicked.connect(self._rename_playlist)
        self.delete_button.clicked.connect(self._delete_playlist)
        playlist_buttons.addWidget(self.new_button)
        playlist_buttons.addWidget(self.rename_button)
        playlist_buttons.addWidget(self.delete_button)
        playlist_layout.addLayout(playlist_buttons)
        content.addWidget(playlist_pane, 1)

        track_pane = QWidget()
        track_layout = QVBoxLayout(track_pane)
        track_layout.setContentsMargins(0, 0, 0, 0)
        track_layout.setSpacing(6)
        track_header = QHBoxLayout()
        track_header.setContentsMargins(0, 0, 0, 0)
        track_header.setSpacing(8)
        self.playlist_drop_hint_label = QLabel(
            self.text["playlist_drop_hint"]
        )
        track_header.addWidget(self.playlist_drop_hint_label)
        track_header.addStretch(1)
        self.total_duration_label = QLabel()
        self.total_duration_label.setObjectName("PlaylistTotalDuration")
        track_header.addWidget(
            self.total_duration_label,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        track_layout.addLayout(track_header)
        self.track_table = PlaylistDropTable(0, 2)
        self.track_table.setObjectName("PlaylistEditorTracks")
        self.track_table.setHorizontalHeaderLabels(
            [self.text["name"], self.text["duration"]]
        )
        for column in range(self.track_table.columnCount()):
            self.track_table.horizontalHeaderItem(column).setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        self.track_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.track_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.track_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.track_table.verticalHeader().hide()
        self.track_table.horizontalHeader().setStretchLastSection(False)
        self.track_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        self.track_table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Fixed,
        )
        self.track_table.setColumnWidth(
            1,
            max(
                64,
                self.track_table.fontMetrics().horizontalAdvance("00:00") + 20,
            ),
        )
        self.track_table.pathsDropped.connect(self._add_paths)
        self.track_table.currentCellChanged.connect(
            lambda *_args: self._update_button_states()
        )
        track_layout.addWidget(self.track_table, 1)
        order_buttons = QHBoxLayout()
        order_buttons.setSpacing(4)
        self.move_up_button = QPushButton(self.text["move_up"])
        self.move_down_button = QPushButton(self.text["move_down"])
        self.remove_button = QPushButton(self.text["remove"])
        self.move_up_button.clicked.connect(lambda: self._move_track(-1))
        self.move_down_button.clicked.connect(lambda: self._move_track(1))
        self.remove_button.clicked.connect(self._remove_track)
        order_buttons.addWidget(self.move_up_button)
        order_buttons.addWidget(self.move_down_button)
        order_buttons.addStretch(1)
        order_buttons.addWidget(self.remove_button)
        track_layout.addLayout(order_buttons)
        content.addWidget(track_pane, 2)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton(
            self.text["save"],
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.close_button = buttons.addButton(
            self.text["close"],
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.close)
        root.addWidget(buttons)

    def _refresh_playlist_list(self, selected_row: int | None = None) -> None:
        if selected_row is None:
            selected_row = self.playlist_list.currentRow()
        self.playlist_list.blockSignals(True)
        self.playlist_list.clear()
        self.playlist_list.addItems([playlist.name for playlist in self.playlists])
        self.playlist_list.blockSignals(False)
        if self.playlists:
            self.playlist_list.setCurrentRow(
                max(0, min(selected_row, len(self.playlists) - 1))
            )
        else:
            self._render_tracks(-1)
        self._update_button_states()

    def _playlist_selected(self, row: int) -> None:
        self._render_tracks(row)
        self._update_button_states()

    def _render_tracks(self, playlist_index: int) -> None:
        tracks = (
            self.playlists[playlist_index].tracks
            if 0 <= playlist_index < len(self.playlists)
            else ()
        )
        self.track_table.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            name_item = QTableWidgetItem(Path(track.name).stem)
            name_item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            name_item.setData(Qt.ItemDataRole.UserRole, str(track.path))
            self.track_table.setItem(row, 0, name_item)
            duration_item = QTableWidgetItem(track.duration)
            duration_item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.track_table.setItem(row, 1, duration_item)
        self.total_duration_label.setText(
            self.text["playlist_total_duration"].format(
                duration=playlist_total_duration(tracks)
            )
        )
        self._update_button_states()

    def _create_playlist(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            self.text["playlist_new_title"],
            self.text["playlist_name"],
        )
        if not accepted or not name.strip():
            return
        self.playlists.append(Playlist.create(name))
        self._dirty = True
        self._refresh_playlist_list(len(self.playlists) - 1)

    def _rename_playlist(self) -> None:
        row = self.playlist_list.currentRow()
        if not 0 <= row < len(self.playlists):
            return
        playlist = self.playlists[row]
        name, accepted = QInputDialog.getText(
            self,
            self.text["playlist_rename_title"],
            self.text["playlist_name"],
            text=playlist.name,
        )
        if not accepted or not name.strip() or name.strip() == playlist.name:
            return
        self.playlists[row] = replace(playlist, name=name.strip())
        self._dirty = True
        self._refresh_playlist_list(row)

    def _delete_playlist(self) -> None:
        row = self.playlist_list.currentRow()
        if not 0 <= row < len(self.playlists):
            return
        playlist = self.playlists[row]
        answer = QMessageBox.question(
            self,
            self.text["playlist_delete_title"],
            self.text["playlist_delete_confirm"].format(name=playlist.name),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self.playlists[row]
        self._dirty = True
        self._refresh_playlist_list(row)

    def _add_paths(self, raw_paths: list[str]) -> None:
        row = self.playlist_list.currentRow()
        if not 0 <= row < len(self.playlists):
            QMessageBox.information(
                self,
                self.text["playlist_title"],
                self.text["playlist_create_first"],
            )
            return
        metadata = {
            str(item.path): item
            for item in self.controller.state.midi_rows
        }
        tracks = list(self.playlists[row].tracks)
        for raw_path in raw_paths:
            path = Path(raw_path)
            midi_row = metadata.get(str(path))
            tracks.append(
                PlaylistTrack(
                    path=path,
                    name=midi_row.name if midi_row is not None else path.name,
                    duration=(
                        midi_row.duration
                        if midi_row is not None
                        else "--:--"
                    ),
                )
            )
        self.playlists[row] = replace(
            self.playlists[row],
            tracks=tuple(tracks),
        )
        self._dirty = True
        self._render_tracks(row)
        if tracks:
            self.track_table.selectRow(len(tracks) - 1)

    def _move_track(self, offset: int) -> None:
        playlist_row = self.playlist_list.currentRow()
        track_row = self.track_table.currentRow()
        if not 0 <= playlist_row < len(self.playlists):
            return
        tracks = list(self.playlists[playlist_row].tracks)
        target = track_row + offset
        if not 0 <= track_row < len(tracks) or not 0 <= target < len(tracks):
            return
        tracks[track_row], tracks[target] = tracks[target], tracks[track_row]
        self.playlists[playlist_row] = replace(
            self.playlists[playlist_row],
            tracks=tuple(tracks),
        )
        self._dirty = True
        self._render_tracks(playlist_row)
        self.track_table.selectRow(target)

    def _remove_track(self) -> None:
        playlist_row = self.playlist_list.currentRow()
        track_row = self.track_table.currentRow()
        if not 0 <= playlist_row < len(self.playlists):
            return
        tracks = list(self.playlists[playlist_row].tracks)
        if not 0 <= track_row < len(tracks):
            return
        del tracks[track_row]
        self.playlists[playlist_row] = replace(
            self.playlists[playlist_row],
            tracks=tuple(tracks),
        )
        self._dirty = True
        self._render_tracks(playlist_row)
        if tracks:
            self.track_table.selectRow(min(track_row, len(tracks) - 1))

    def _save(self) -> None:
        if self.controller.replace_playlists(self.playlists):
            self.playlists = list(self.controller.state.playlists)
            self._dirty = False

    def _update_button_states(self) -> None:
        playlist_selected = (
            0 <= self.playlist_list.currentRow() < len(self.playlists)
        )
        track_row = self.track_table.currentRow()
        track_count = self.track_table.rowCount()
        self.rename_button.setEnabled(playlist_selected)
        self.delete_button.setEnabled(playlist_selected)
        self.remove_button.setEnabled(playlist_selected and track_row >= 0)
        self.move_up_button.setEnabled(
            playlist_selected and track_row > 0
        )
        self.move_down_button.setEnabled(
            playlist_selected and 0 <= track_row < track_count - 1
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._dirty:
            event.accept()
            return
        message_box = self._make_unsaved_message_box()
        answer = QMessageBox.StandardButton(message_box.exec())
        if answer == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        if answer == QMessageBox.StandardButton.Save:
            self._save()
            if self._dirty:
                event.ignore()
                return
        event.accept()

    def _make_unsaved_message_box(self) -> QMessageBox:
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Question)
        message_box.setWindowTitle(self.text["playlist_unsaved_title"])
        message_box.setText(self.text["playlist_unsaved_message"])
        message_box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.Save)
        message_box.button(QMessageBox.StandardButton.Save).setText(
            self.text["save"]
        )
        message_box.button(QMessageBox.StandardButton.Discard).setText(
            self.text["discard"]
        )
        message_box.button(QMessageBox.StandardButton.Cancel).setText(
            self.text["cancel"]
        )
        return message_box
