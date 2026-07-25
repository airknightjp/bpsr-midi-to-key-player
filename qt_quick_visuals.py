from __future__ import annotations

import sys
import time
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Property, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QSizePolicy, QWidget

from config import PIANO_NOTE_MAX, PIANO_NOTE_MIN
from note_visualization import PianoRollNote


def _resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def _color_name(value: str | QColor) -> str:
    return QColor(value).name(QColor.NameFormat.HexArgb)


def _load_qml(widget: QQuickWidget, relative: str) -> None:
    widget.setSource(QUrl.fromLocalFile(str(_resource_path(relative))))
    if widget.status() != QQuickWidget.Status.Error:
        return
    messages = "\n".join(error.toString() for error in widget.errors())
    raise RuntimeError(f"Failed to load {relative}:\n{messages}")


class _KeyboardBridge(QObject):
    activeNotesChanged = Signal()
    releasedNotesChanged = Signal()
    usedRangeChanged = Signal()
    colorsChanged = Signal()
    renderingEnabledChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._active_notes: list[int] = []
        self._released_notes: list[int] = []
        self._has_used_range = False
        self._used_low = PIANO_NOTE_MIN
        self._used_high = PIANO_NOTE_MAX
        self._surface = "#ffffffff"
        self._border = "#ff9aa5b1"
        self._text = "#ff5d6878"
        self._black = "#ff202632"
        self._accent = "#ff00a7d6"
        self._accent_border = "#ff0093bd"
        self._accent_text = "#ffffffff"
        self._rendering_enabled = True

    @Property(list, notify=activeNotesChanged)
    def activeNotes(self) -> list[int]:
        return self._active_notes

    @Property(list, notify=releasedNotesChanged)
    def releasedNotes(self) -> list[int]:
        return self._released_notes

    @Property(bool, notify=usedRangeChanged)
    def hasUsedRange(self) -> bool:
        return self._has_used_range

    @Property(int, notify=usedRangeChanged)
    def usedLow(self) -> int:
        return self._used_low

    @Property(int, notify=usedRangeChanged)
    def usedHigh(self) -> int:
        return self._used_high

    @Property(str, notify=colorsChanged)
    def surfaceColor(self) -> str:
        return self._surface

    @Property(str, notify=colorsChanged)
    def borderColor(self) -> str:
        return self._border

    @Property(str, notify=colorsChanged)
    def textColor(self) -> str:
        return self._text

    @Property(str, notify=colorsChanged)
    def blackColor(self) -> str:
        return self._black

    @Property(str, notify=colorsChanged)
    def accentColor(self) -> str:
        return self._accent

    @Property(str, notify=colorsChanged)
    def accentBorderColor(self) -> str:
        return self._accent_border

    @Property(str, notify=colorsChanged)
    def accentTextColor(self) -> str:
        return self._accent_text

    @Property(bool, notify=renderingEnabledChanged)
    def renderingEnabled(self) -> bool:
        return self._rendering_enabled

    def set_active_notes(self, notes: frozenset[int]) -> None:
        values = sorted(notes)
        if values != self._active_notes:
            self._active_notes = values
            self.activeNotesChanged.emit()

    def set_released_notes(self, notes: set[int]) -> None:
        values = sorted(notes)
        if values != self._released_notes:
            self._released_notes = values
            self.releasedNotesChanged.emit()

    def set_used_range(self, note_range: tuple[int, int] | None) -> None:
        has_range = note_range is not None
        low, high = note_range or (PIANO_NOTE_MIN, PIANO_NOTE_MAX)
        if (
            has_range != self._has_used_range
            or low != self._used_low
            or high != self._used_high
        ):
            self._has_used_range = has_range
            self._used_low = low
            self._used_high = high
            self.usedRangeChanged.emit()

    def set_colors(
        self,
        surface: str,
        border: str,
        text: str,
        accent: str,
        accent_border: str,
        accent_text: str,
    ) -> None:
        values = (
            _color_name(surface),
            _color_name(border),
            _color_name(text),
            _color_name("#202632"),
            _color_name(accent),
            _color_name(accent_border),
            _color_name(accent_text),
        )
        if values == (
            self._surface,
            self._border,
            self._text,
            self._black,
            self._accent,
            self._accent_border,
            self._accent_text,
        ):
            return
        (
            self._surface,
            self._border,
            self._text,
            self._black,
            self._accent,
            self._accent_border,
            self._accent_text,
        ) = values
        self.colorsChanged.emit()

    def set_rendering_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled != self._rendering_enabled:
            self._rendering_enabled = enabled
            self.renderingEnabledChanged.emit()


class PianoKeyboardWidget(QQuickWidget):
    NOTE_MIN = PIANO_NOTE_MIN
    NOTE_MAX = PIANO_NOTE_MAX
    BASE_HEIGHT = 57
    WHITE_PITCH_CLASSES = frozenset((0, 2, 4, 5, 7, 9, 11))
    BLACK_BOUNDARIES = {1: 1, 3: 2, 6: 4, 8: 5, 10: 6}
    RETRIGGER_RELEASE_SECONDS = 0.05

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OutputPianoKeyboard")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._active_notes: frozenset[int] = frozenset()
        self._used_note_range: tuple[int, int] | None = None
        self._last_retrigger_serials: dict[int, int] = {}
        self._retrigger_release_until: dict[int, float] = {}
        self._rendering_enabled = True
        self._bridge = _KeyboardBridge()
        self.rootContext().setContextProperty("keyboardBridge", self._bridge)
        _load_qml(self, "qml/PianoKeyboard.qml")
        self._retrigger_timer = QTimer(self)
        self._retrigger_timer.setInterval(16)
        self._retrigger_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._retrigger_timer.timeout.connect(self._advance_retrigger_release)
        self.apply_scale(1.0)

    @property
    def active_notes(self) -> frozenset[int]:
        return self._active_notes

    @property
    def used_note_range(self) -> tuple[int, int] | None:
        return self._used_note_range

    @property
    def rendering_enabled(self) -> bool:
        return self._rendering_enabled

    @property
    def graphics_api_name(self) -> str:
        return QQuickWindow.graphicsApi().name

    def set_rendering_enabled(
        self,
        enabled: bool,
        *,
        current_retrigger_events: object = (),
    ) -> None:
        enabled = bool(enabled)
        if self._rendering_enabled == enabled:
            return
        self._rendering_enabled = enabled
        self._retrigger_timer.stop()
        self._retrigger_release_until.clear()
        self._bridge.set_released_notes(set())
        self._bridge.set_rendering_enabled(enabled)
        if enabled:
            try:
                for note, serial in current_retrigger_events:  # type: ignore[union-attr]
                    self._last_retrigger_serials[int(note)] = int(serial)
            except (TypeError, ValueError):
                pass

    def set_active_notes(self, notes: object) -> None:
        if not self._rendering_enabled:
            return
        try:
            active = frozenset(
                int(note)
                for note in notes  # type: ignore[union-attr]
                if self.NOTE_MIN <= int(note) <= self.NOTE_MAX
            )
        except (TypeError, ValueError):
            active = frozenset()
        if active != self._active_notes:
            self._active_notes = active
            self._bridge.set_active_notes(active)

    def set_used_note_range(self, note_range: object) -> None:
        normalized: tuple[int, int] | None = None
        if note_range is not None:
            try:
                low, high = note_range  # type: ignore[misc]
                low = max(self.NOTE_MIN, min(self.NOTE_MAX, int(low)))
                high = max(self.NOTE_MIN, min(self.NOTE_MAX, int(high)))
                if low <= high:
                    normalized = (low, high)
            except (TypeError, ValueError):
                normalized = None
        if normalized != self._used_note_range:
            self._used_note_range = normalized
            self._bridge.set_used_range(normalized)

    def set_retrigger_events(self, events: object) -> None:
        if not self._rendering_enabled:
            return
        try:
            retrigger_events = tuple(
                (int(note), int(serial))
                for note, serial in events  # type: ignore[union-attr]
            )
        except (TypeError, ValueError):
            return
        release_until = time.monotonic() + self.RETRIGGER_RELEASE_SECONDS
        changed = False
        for note, serial in retrigger_events:
            if self._last_retrigger_serials.get(note) == serial:
                continue
            self._last_retrigger_serials[note] = serial
            if self.NOTE_MIN <= note <= self.NOTE_MAX:
                self._retrigger_release_until[note] = release_until
                changed = True
        if changed:
            self._bridge.set_released_notes(set(self._retrigger_release_until))
            if not self._retrigger_timer.isActive():
                self._retrigger_timer.start()

    def _advance_retrigger_release(self) -> None:
        if not self._rendering_enabled:
            self._retrigger_timer.stop()
            return
        now = time.monotonic()
        expired = [
            note
            for note, until in self._retrigger_release_until.items()
            if now >= until
        ]
        for note in expired:
            self._retrigger_release_until.pop(note, None)
        self._bridge.set_released_notes(set(self._retrigger_release_until))
        if not self._retrigger_release_until:
            self._retrigger_timer.stop()

    def set_colors(
        self,
        surface: str,
        border: str,
        text: str,
        accent: str,
        accent_border: str,
        accent_text: str,
    ) -> None:
        self.setClearColor(QColor(surface))
        self._bridge.set_colors(
            surface,
            border,
            text,
            accent,
            accent_border,
            accent_text,
        )

    def apply_scale(self, scale: float) -> None:
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setFixedHeight(max(1, round(self.BASE_HEIGHT * scale)))

    def sizeHint(self) -> QSize:
        return QSize(420, self.BASE_HEIGHT)


@dataclass(frozen=True)
class _RhythmHitImpact:
    serial: int
    note: int
    started_at: float
    started_at_ms: int
    judgment: str
    released: bool


@dataclass(frozen=True)
class _RhythmLaneFade:
    serial: int
    note: int
    started_at: float
    started_at_ms: int


class _FallingNotesBridge(QObject):
    visibleNotesChanged = Signal()
    usedRangeChanged = Signal()
    playbackChanged = Signal()
    effectsChanged = Signal()
    colorsChanged = Signal()
    renderingEnabledChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._visible_notes: list[dict[str, object]] = []
        self._has_used_range = False
        self._used_low = PIANO_NOTE_MIN
        self._used_high = PIANO_NOTE_MAX
        self._position = 0.0
        self._position_anchor_ms = int(time.time() * 1000)
        self._speed_ratio = 1.0
        self._running = False
        self._impacts: list[dict[str, object]] = []
        self._held_notes: list[int] = []
        self._lane_fades: list[dict[str, object]] = []
        self._surface = "#ff000000"
        self._border = "#ff9aa5b1"
        self._grid = "#ffd5dde7"
        self._scheduled = "#ff00a7d6"
        self._live = "#ff0093bd"
        self._rendering_enabled = True

    @Property(list, notify=visibleNotesChanged)
    def visibleNotes(self) -> list[dict[str, object]]:
        return self._visible_notes

    @Property(bool, notify=usedRangeChanged)
    def hasUsedRange(self) -> bool:
        return self._has_used_range

    @Property(int, notify=usedRangeChanged)
    def usedLow(self) -> int:
        return self._used_low

    @Property(int, notify=usedRangeChanged)
    def usedHigh(self) -> int:
        return self._used_high

    @Property(float, notify=playbackChanged)
    def position(self) -> float:
        return self._position

    @Property(float, notify=playbackChanged)
    def positionAnchorMs(self) -> float:
        return float(self._position_anchor_ms)

    @Property(float, notify=playbackChanged)
    def speedRatio(self) -> float:
        return self._speed_ratio

    @Property(bool, notify=playbackChanged)
    def running(self) -> bool:
        return self._running

    @Property(list, notify=effectsChanged)
    def impacts(self) -> list[dict[str, object]]:
        return self._impacts

    @Property(list, notify=effectsChanged)
    def heldNotes(self) -> list[int]:
        return self._held_notes

    @Property(list, notify=effectsChanged)
    def laneFades(self) -> list[dict[str, object]]:
        return self._lane_fades

    @Property(str, notify=colorsChanged)
    def surfaceColor(self) -> str:
        return self._surface

    @Property(str, notify=colorsChanged)
    def borderColor(self) -> str:
        return self._border

    @Property(str, notify=colorsChanged)
    def gridColor(self) -> str:
        return self._grid

    @Property(str, notify=colorsChanged)
    def scheduledColor(self) -> str:
        return self._scheduled

    @Property(str, notify=colorsChanged)
    def liveColor(self) -> str:
        return self._live

    @Property(bool, notify=renderingEnabledChanged)
    def renderingEnabled(self) -> bool:
        return self._rendering_enabled

    @Property(bool, notify=playbackChanged)
    def animationRunning(self) -> bool:
        return (
            self._rendering_enabled
            and (
                self._running
                or bool(self._impacts)
                or bool(self._lane_fades)
            )
        )

    def set_visible_notes(self, notes: tuple[PianoRollNote, ...]) -> None:
        values = [
            {"start": note.start, "end": note.end, "note": note.note}
            for note in notes
        ]
        if values != self._visible_notes:
            self._visible_notes = values
            self.visibleNotesChanged.emit()

    def set_used_range(self, note_range: tuple[int, int] | None) -> None:
        has_range = note_range is not None
        low, high = note_range or (PIANO_NOTE_MIN, PIANO_NOTE_MAX)
        if (
            has_range != self._has_used_range
            or low != self._used_low
            or high != self._used_high
        ):
            self._has_used_range = has_range
            self._used_low = low
            self._used_high = high
            self.usedRangeChanged.emit()

    def set_playback(
        self,
        position: float,
        anchor_ms: int,
        speed_ratio: float,
        running: bool,
    ) -> None:
        values = (float(position), int(anchor_ms), float(speed_ratio), bool(running))
        current = (
            self._position,
            self._position_anchor_ms,
            self._speed_ratio,
            self._running,
        )
        if values != current:
            (
                self._position,
                self._position_anchor_ms,
                self._speed_ratio,
                self._running,
            ) = values
            self.playbackChanged.emit()

    def set_effects(
        self,
        impacts: list[dict[str, object]],
        held_notes: list[int],
        lane_fades: list[dict[str, object]],
    ) -> None:
        if (
            impacts == self._impacts
            and held_notes == self._held_notes
            and lane_fades == self._lane_fades
        ):
            return
        self._impacts = impacts
        self._held_notes = held_notes
        self._lane_fades = lane_fades
        self.effectsChanged.emit()
        self.playbackChanged.emit()

    def set_colors(
        self,
        surface: str,
        border: str,
        grid: str,
        scheduled: str,
        live: str,
    ) -> None:
        values = tuple(
            _color_name(value)
            for value in (surface, border, grid, scheduled, live)
        )
        if values == (
            self._surface,
            self._border,
            self._grid,
            self._scheduled,
            self._live,
        ):
            return
        (
            self._surface,
            self._border,
            self._grid,
            self._scheduled,
            self._live,
        ) = values
        self.colorsChanged.emit()

    def set_rendering_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled != self._rendering_enabled:
            self._rendering_enabled = enabled
            self.renderingEnabledChanged.emit()
            self.playbackChanged.emit()


class FallingNotesWidget(QQuickWidget):
    NOTE_MIN = PIANO_NOTE_MIN
    NOTE_MAX = PIANO_NOTE_MAX
    BASE_HEIGHT = PianoKeyboardWidget.BASE_HEIGHT
    PREVIEW_SECONDS = 1.0
    IMPACT_DURATION_SECONDS = {
        "PERFECT": 0.24,
        "GREAT": 0.18,
        "GOOD": 0.12,
    }
    LANE_FADE_SECONDS = 0.15
    HELD_LANE_OPACITY = 0.28
    WHITE_PITCH_CLASSES = PianoKeyboardWidget.WHITE_PITCH_CLASSES
    BLACK_PITCH_CLASSES = frozenset((1, 3, 6, 8, 10))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FallingNotes")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setClearColor(QColor("#000000"))
        self._sequence_notes: tuple[PianoRollNote, ...] = ()
        self._used_note_range: tuple[int, int] | None = None
        self._sequence_starts: tuple[float, ...] = ()
        self._sequence_ends: tuple[float, ...] = ()
        self._sequence_end_entries: tuple[tuple[float, int], ...] = ()
        self._active_sequence_indexes: set[int] = set()
        self._active_start_cursor = 0
        self._active_end_cursor = 0
        self._active_query_position: float | None = None
        self._position = 0.0
        self._position_anchor = time.monotonic()
        self._speed_ratio = 1.0
        self._playback_running = False
        self._hit_impacts: list[_RhythmHitImpact] = []
        self._held_lane_counts: dict[int, int] = {}
        self._lane_fades: list[_RhythmLaneFade] = []
        self._last_hit_serial = 0
        self._scale = 1.0
        self._surface = QColor("#000000")
        self._rendering_enabled = True
        self._bridge = _FallingNotesBridge()
        self.rootContext().setContextProperty("fallingNotesBridge", self._bridge)
        _load_qml(self, "qml/FallingNotes.qml")
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(100)
        self._animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._animation_timer.timeout.connect(self._advance_animation)
        self.apply_scale(1.0)

    @property
    def sequence_notes(self) -> tuple[PianoRollNote, ...]:
        return self._sequence_notes

    @property
    def used_note_range(self) -> tuple[int, int] | None:
        return self._used_note_range

    @property
    def rendering_enabled(self) -> bool:
        return self._rendering_enabled

    @property
    def live_trail_count(self) -> int:
        return 0

    @property
    def hit_impact_count(self) -> int:
        return len(self._hit_impacts)

    @property
    def held_lane_notes(self) -> frozenset[int]:
        return frozenset(self._held_lane_counts)

    @property
    def lane_fade_count(self) -> int:
        return len(self._lane_fades)

    @property
    def graphics_api_name(self) -> str:
        return QQuickWindow.graphicsApi().name

    def set_rendering_enabled(
        self,
        enabled: bool,
        *,
        latest_hit_events: object = (),
    ) -> None:
        enabled = bool(enabled)
        if self._rendering_enabled == enabled:
            return
        self._rendering_enabled = enabled
        self._animation_timer.stop()
        self._hit_impacts.clear()
        self._held_lane_counts.clear()
        self._lane_fades.clear()
        self._playback_running = False
        self._reset_active_sequence_cache()
        self._bridge.set_rendering_enabled(enabled)
        self._bridge.set_visible_notes(())
        self._sync_effects()
        if enabled:
            try:
                serials = [
                    int(tuple(event)[0])
                    for event in latest_hit_events  # type: ignore[union-attr]
                    if tuple(event)
                ]
                self._last_hit_serial = max(serials, default=self._last_hit_serial)
            except (TypeError, ValueError, IndexError):
                pass

    def set_hit_events(self, events: object) -> None:
        if not self._rendering_enabled:
            return
        try:
            source = events if isinstance(events, (list, tuple)) else tuple(events)  # type: ignore[arg-type]
            pending: list[tuple[int, int, str, bool]] = []
            for raw_event in reversed(source):
                values = tuple(raw_event)
                if len(values) not in {3, 4}:
                    continue
                serial = int(values[0])
                if serial <= self._last_hit_serial:
                    break
                pending.append(
                    (
                        serial,
                        int(values[1]),
                        str(values[2]).upper(),
                        bool(values[3]) if len(values) == 4 else False,
                    )
                )
        except (TypeError, ValueError, IndexError):
            return
        now = time.monotonic()
        now_ms = int(time.time() * 1000)
        changed = False
        for serial, note, judgment, released in reversed(pending):
            self._last_hit_serial = serial
            if (
                not self.NOTE_MIN <= note <= self.NOTE_MAX
                or judgment not in {"PERFECT", "GREAT", "GOOD"}
            ):
                continue
            if released:
                self._release_held_lane(note)
                self._lane_fades.append(
                    _RhythmLaneFade(serial, note, now, now_ms)
                )
            else:
                self._held_lane_counts[note] = (
                    self._held_lane_counts.get(note, 0) + 1
                )
            self._hit_impacts.append(
                _RhythmHitImpact(
                    serial,
                    note,
                    now,
                    now_ms,
                    judgment,
                    released,
                )
            )
            changed = True
        if changed:
            self._hit_impacts = self._hit_impacts[-64:]
            self._lane_fades = self._lane_fades[-64:]
            self._sync_effects()
            self._update_animation_timer()

    def _release_held_lane(self, note: int) -> None:
        active_count = self._held_lane_counts.get(note, 0)
        if active_count <= 1:
            self._held_lane_counts.pop(note, None)
        else:
            self._held_lane_counts[note] = active_count - 1

    def set_sequence_notes(self, notes: tuple[PianoRollNote, ...]) -> None:
        if not self._rendering_enabled:
            return
        normalized = tuple(
            sorted(notes, key=lambda item: (item.start, item.note, item.end))
        )
        if normalized == self._sequence_notes:
            return
        self._sequence_notes = normalized
        self._sequence_starts = tuple(note.start for note in normalized)
        self._sequence_end_entries = tuple(
            sorted(
                ((note.end, index) for index, note in enumerate(normalized)),
                key=lambda item: (
                    item[0],
                    normalized[item[1]].start,
                    normalized[item[1]].note,
                ),
            )
        )
        self._sequence_ends = tuple(end for end, _index in self._sequence_end_entries)
        self._reset_active_sequence_cache()
        self._refresh_visible_notes(self._position)

    def set_used_note_range(self, note_range: object) -> None:
        normalized: tuple[int, int] | None = None
        if note_range is not None:
            try:
                low, high = note_range  # type: ignore[misc]
                low = max(self.NOTE_MIN, min(self.NOTE_MAX, int(low)))
                high = max(self.NOTE_MIN, min(self.NOTE_MAX, int(high)))
                if low <= high:
                    normalized = (low, high)
            except (TypeError, ValueError):
                normalized = None
        if normalized != self._used_note_range:
            self._used_note_range = normalized
            self._bridge.set_used_range(normalized)

    def set_playback_state(
        self,
        position: float,
        speed_percent: int,
        running: bool,
    ) -> None:
        if not self._rendering_enabled:
            return
        self._position = max(0.0, float(position))
        self._position_anchor = time.monotonic()
        self._speed_ratio = max(0.1, min(2.0, int(speed_percent) / 100.0))
        self._playback_running = bool(running)
        self._bridge.set_playback(
            self._position,
            int(time.time() * 1000),
            self._speed_ratio,
            self._playback_running,
        )
        self._refresh_visible_notes(self._position)
        self._update_animation_timer()

    def set_live_state(
        self,
        active_notes: object,
        trigger_events: object,
    ) -> None:
        if not self._rendering_enabled:
            return
        _ = trigger_events
        try:
            active = {int(note) for note in active_notes}  # type: ignore[union-attr]
        except (TypeError, ValueError):
            return
        stale = set(self._held_lane_counts).difference(active)
        if stale:
            for note in stale:
                self._held_lane_counts.pop(note, None)
            self._sync_effects()
            self._update_animation_timer()

    def set_colors(
        self,
        surface: str,
        border: str,
        grid: str,
        scheduled: str,
        live: str,
    ) -> None:
        self._surface = QColor(surface)
        self.setClearColor(QColor(surface))
        self._bridge.set_colors(surface, border, grid, scheduled, live)

    def apply_scale(self, scale: float) -> None:
        self._scale = max(0.5, float(scale))
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setFixedHeight(max(1, round(self.BASE_HEIGHT * scale)))

    def sizeHint(self) -> QSize:
        return QSize(420, self.BASE_HEIGHT)

    def _current_position(self, now: float) -> float:
        if not self._playback_running:
            return self._position
        return self._position + (now - self._position_anchor) * self._speed_ratio

    def _advance_animation(self) -> None:
        if not self._rendering_enabled:
            self._animation_timer.stop()
            return
        now = time.monotonic()
        self._hit_impacts = [
            impact
            for impact in self._hit_impacts
            if now - impact.started_at <= self._impact_duration(impact.judgment)
        ]
        self._lane_fades = [
            fade
            for fade in self._lane_fades
            if now - fade.started_at <= self.LANE_FADE_SECONDS
        ]
        self._refresh_visible_notes(self._current_position(now))
        self._sync_effects()
        self._update_animation_timer()

    def _update_animation_timer(self) -> None:
        should_run = (
            self._rendering_enabled
            and (
                self._playback_running
                or bool(self._hit_impacts)
                or bool(self._lane_fades)
            )
        )
        if should_run and not self._animation_timer.isActive():
            self._animation_timer.start()
        elif not should_run and self._animation_timer.isActive():
            self._animation_timer.stop()

    def _refresh_visible_notes(self, position: float) -> None:
        horizon = self.PREVIEW_SECONDS * self._speed_ratio
        prefetch = max(0.25, horizon * 0.5)
        self._bridge.set_visible_notes(
            self._visible_sequence_notes(position, horizon + prefetch)
        )

    def _sync_effects(self) -> None:
        impacts = [
            {
                "serial": impact.serial,
                "note": impact.note,
                "startedAtMs": impact.started_at_ms,
                "judgment": impact.judgment,
                "released": impact.released,
            }
            for impact in self._hit_impacts
        ]
        fades = [
            {
                "serial": fade.serial,
                "note": fade.note,
                "startedAtMs": fade.started_at_ms,
            }
            for fade in self._lane_fades
        ]
        self._bridge.set_effects(
            impacts,
            sorted(self._held_lane_counts),
            fades,
        )

    def _visible_sequence_notes(
        self,
        position: float,
        song_horizon: float,
    ) -> tuple[PianoRollNote, ...]:
        if not self._sequence_notes:
            return ()
        active = self._active_sequence_notes(position)
        left = bisect_right(self._sequence_starts, position)
        right = bisect_right(self._sequence_starts, position + song_horizon)
        return tuple(
            sorted(
                (*active, *self._sequence_notes[left:right]),
                key=lambda item: (item.start, item.note, item.end),
            )
        )

    def _active_sequence_notes(self, position: float) -> tuple[PianoRollNote, ...]:
        started_right = bisect_right(self._sequence_starts, position)
        ending_left = bisect_right(self._sequence_ends, position)
        previous_position = self._active_query_position
        if previous_position is None:
            active = set(range(started_right))
            for _end, index in self._sequence_end_entries[:ending_left]:
                active.discard(index)
            self._active_sequence_indexes = active
        elif position >= previous_position:
            self._active_sequence_indexes.update(
                range(self._active_start_cursor, started_right)
            )
            for _end, index in self._sequence_end_entries[
                self._active_end_cursor:ending_left
            ]:
                self._active_sequence_indexes.discard(index)
        else:
            for _end, index in self._sequence_end_entries[
                ending_left:self._active_end_cursor
            ]:
                self._active_sequence_indexes.add(index)
            for index in range(started_right, self._active_start_cursor):
                self._active_sequence_indexes.discard(index)
        self._active_start_cursor = started_right
        self._active_end_cursor = ending_left
        self._active_query_position = position
        return tuple(
            self._sequence_notes[index]
            for index in sorted(self._active_sequence_indexes)
        )

    def _reset_active_sequence_cache(self) -> None:
        self._active_sequence_indexes.clear()
        self._active_start_cursor = 0
        self._active_end_cursor = 0
        self._active_query_position = None

    def _note_rect(self, note: int, width: float) -> tuple[float, float] | None:
        white_notes = tuple(
            value
            for value in range(self.NOTE_MIN, self.NOTE_MAX + 1)
            if value % 12 in self.WHITE_PITCH_CLASSES
        )
        white_indexes = {value: index for index, value in enumerate(white_notes)}
        white_width = float(width) / len(white_notes)
        if note in white_indexes:
            center = (white_indexes[note] + 0.5) * white_width
            note_width = white_width
        elif note % 12 in self.BLACK_PITCH_CLASSES and note - 1 in white_indexes:
            center = (white_indexes[note - 1] + 1) * white_width
            note_width = white_width * 0.62
        else:
            return None
        return center - note_width / 2.0, note_width

    def _minimum_note_body_height(self, note_width: float) -> float:
        return max(
            4.0 * self._scale,
            min(6.0 * self._scale, note_width * 0.35),
        )

    def _light_bar_metrics(self, note_width: float) -> tuple[float, float]:
        return (
            max(2.0 * self._scale, note_width * 0.12),
            max(0.6, 0.65 * self._scale),
        )

    def _clamp_light_bar_center(self, center_y: float, note_width: float) -> float:
        bar_height, outline_width = self._light_bar_metrics(note_width)
        half_extent = (bar_height + outline_width) / 2.0
        drawable_bottom = float(self.height() - 1)
        return max(
            half_extent,
            min(drawable_bottom - half_extent, center_y),
        )

    @staticmethod
    def _rainbow_impact_color(
        index: int,
        count: int,
        progress: float,
    ) -> QColor:
        count = max(1, int(count))
        hue = round(
            (int(index) % count) * 360.0 / count
            + max(0.0, min(1.0, float(progress))) * 80.0
        ) % 360
        return QColor.fromHsv(hue, 235, 255)

    def _impact_style(
        self,
        judgment: str,
    ) -> tuple[QColor, float, int, int, int]:
        if judgment == "PERFECT":
            return QColor("#ffd84d"), 1.50, 17, 2, 7
        if judgment == "GREAT":
            return QColor("#52e5ff"), 1.05, 10, 1, 4
        return QColor("#00a7d6").lighter(120), 0.72, 5, 0, 2

    def _impact_duration(self, judgment: str) -> float:
        return self.IMPACT_DURATION_SECONDS.get(
            judgment,
            self.IMPACT_DURATION_SECONDS["GOOD"],
        )
