from __future__ import annotations

import time
import math
from bisect import bisect_right
from dataclasses import dataclass

from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDrag,
    QFontMetricsF,
    QIcon,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDial,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStyle,
    QStyleOptionSlider,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app_state import TrackChannelItem
from config import PIANO_NOTE_MAX, PIANO_NOTE_MIN
from note_visualization import PianoRollNote


PANEL_DRAG_MIME_TYPE = "application/x-bpsr-panel-id"


def make_refresh_icon(color: str, size: int) -> QIcon:
    size = max(12, size)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    stroke = max(1.25, size / 10)
    painter.setPen(QPen(QColor(color), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    inset = stroke + 1
    bounds = QRectF(inset, inset, size - inset * 2, size - inset * 2)
    painter.drawArc(bounds, 35 * 16, 285 * 16)
    arrow_color = QColor(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(arrow_color))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(size * 0.72, size * 0.08),
                QPointF(size * 0.96, size * 0.18),
                QPointF(size * 0.76, size * 0.36),
            ]
        )
    )
    painter.end()
    return QIcon(pixmap)


def make_transport_icon(action: str, color: str, size: int) -> QIcon:
    size = max(14, size)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    icon_color = QColor(color)
    stroke = max(1.25, size / 12)
    inset = stroke
    bounds = QRectF(inset, inset, size - inset * 2, size - inset * 2)
    painter.setPen(
        QPen(
            icon_color,
            stroke,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(bounds)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(icon_color))
    if action == "stop":
        side = size * 0.30
        painter.drawRoundedRect(
            QRectF((size - side) / 2, (size - side) / 2, side, side),
            max(1.0, size * 0.05),
            max(1.0, size * 0.05),
        )
    elif action == "pause":
        bar_width = size * 0.10
        bar_height = size * 0.34
        for center_x in (size * 0.44, size * 0.60):
            painter.drawRoundedRect(
                QRectF(
                    center_x - bar_width / 2,
                    (size - bar_height) / 2,
                    bar_width,
                    bar_height,
                ),
                max(0.7, size * 0.025),
                max(0.7, size * 0.025),
            )
    elif action in {"previous", "next"}:
        direction = -1 if action == "previous" else 1
        center_x = size * 0.50
        triangle_width = size * 0.22
        triangle_height = size * 0.30
        tip_x = center_x + direction * triangle_width * 0.58
        base_x = center_x - direction * triangle_width * 0.58
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(tip_x, size * 0.50),
                    QPointF(base_x, size * 0.50 - triangle_height / 2),
                    QPointF(base_x, size * 0.50 + triangle_height / 2),
                ]
            )
        )
        bar_width = max(1.0, size * 0.065)
        bar_x = center_x + direction * size * 0.17
        painter.drawRoundedRect(
            QRectF(
                bar_x - bar_width / 2,
                size * 0.35,
                bar_width,
                size * 0.30,
            ),
            bar_width / 2,
            bar_width / 2,
        )
    elif action.startswith("repeat_"):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                icon_color,
                max(1.0, size / 15),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawLine(
            QPointF(size * 0.34, size * 0.41),
            QPointF(size * 0.66, size * 0.41),
        )
        painter.drawLine(
            QPointF(size * 0.66, size * 0.59),
            QPointF(size * 0.34, size * 0.59),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(icon_color))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(size * 0.67, size * 0.33),
                    QPointF(size * 0.76, size * 0.41),
                    QPointF(size * 0.67, size * 0.49),
                ]
            )
        )
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(size * 0.33, size * 0.51),
                    QPointF(size * 0.24, size * 0.59),
                    QPointF(size * 0.33, size * 0.67),
                ]
            )
        )
        if action == "repeat_one":
            font = painter.font()
            font.setBold(True)
            font.setPixelSize(max(6, round(size * 0.25)))
            painter.setFont(font)
            painter.setPen(icon_color)
            painter.drawText(
                QRectF(size * 0.40, size * 0.40, size * 0.20, size * 0.20),
                Qt.AlignmentFlag.AlignCenter,
                "1",
            )
        elif action == "repeat_off":
            painter.setPen(
                QPen(
                    icon_color,
                    max(1.0, size / 13),
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(
                QPointF(size * 0.32, size * 0.68),
                QPointF(size * 0.68, size * 0.32),
            )
    else:
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(size * 0.42, size * 0.32),
                    QPointF(size * 0.42, size * 0.68),
                    QPointF(size * 0.70, size * 0.50),
                ]
            )
        )
    painter.end()
    return QIcon(pixmap)


def make_feature_icon(feature: str, color: str, size: int) -> QIcon:
    size = max(16, size)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    icon_color = QColor(color)
    outer_stroke = max(1.25, size / 12)
    painter.setPen(
        QPen(
            icon_color,
            outer_stroke,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset = outer_stroke
    painter.drawEllipse(QRectF(inset, inset, size - inset * 2, size - inset * 2))

    inner_stroke = max(1.0, size / 18)
    painter.setPen(
        QPen(
            icon_color,
            inner_stroke,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    if feature == "input_device":
        keyboard = QRectF(size * 0.20, size * 0.34, size * 0.60, size * 0.34)
        painter.drawRoundedRect(keyboard, size * 0.04, size * 0.04)
        white_key_width = keyboard.width() / 7
        for index in range(1, 7):
            x = keyboard.left() + white_key_width * index
            painter.drawLine(
                QPointF(x, keyboard.top()),
                QPointF(x, keyboard.bottom()),
            )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(icon_color))
        black_key_width = max(1.0, white_key_width * 0.46)
        black_key_height = keyboard.height() * 0.48
        for index in (1, 2, 4, 5, 6):
            x = keyboard.left() + white_key_width * index
            painter.drawRoundedRect(
                QRectF(
                    x - black_key_width / 2,
                    keyboard.top(),
                    black_key_width,
                    black_key_height,
                ),
                black_key_width * 0.22,
                black_key_width * 0.22,
            )
    elif feature == "shortcut":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(icon_color))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(size * 0.56, size * 0.24),
                    QPointF(size * 0.33, size * 0.53),
                    QPointF(size * 0.48, size * 0.53),
                    QPointF(size * 0.41, size * 0.77),
                    QPointF(size * 0.68, size * 0.43),
                    QPointF(size * 0.52, size * 0.43),
                ]
            )
        )
    else:
        center = QPointF(size * 0.50, size * 0.50)
        painter.drawLine(center, QPointF(size * 0.50, size * 0.29))
        painter.drawLine(center, QPointF(size * 0.66, size * 0.57))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(icon_color))
        center_radius = max(1.0, size * 0.055)
        painter.drawEllipse(center, center_radius, center_radius)
    painter.end()
    return QIcon(pixmap)


class InteractiveIconButton(QToolButton):
    HOVER_SCALE = 1.075
    PRESSED_SCALE = 0.925

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_icon_size = QSize(16, 16)
        self._hovered = False
        self._pressed = False
        self._background_source: QWidget | None = None
        self._background_color = QColor(Qt.GlobalColor.transparent)
        self._background_radius = 0.0
        self._interaction_scaling_enabled = True

    @property
    def background_color(self) -> QColor:
        return QColor(self._background_color)

    def set_theme_backdrop(
        self,
        source: QWidget,
        color: str,
        radius: float,
    ) -> None:
        self._background_source = source
        self._background_color = QColor(color)
        self._background_radius = max(0.0, float(radius))
        self.update()

    def set_base_icon_size(self, size: QSize) -> None:
        self._base_icon_size = QSize(size)
        self._refresh_icon_size()

    def set_interaction_scaling_enabled(self, enabled: bool) -> None:
        self._interaction_scaling_enabled = bool(enabled)
        self._refresh_icon_size()

    def enterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hovered = True
        self._refresh_icon_size()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hovered = False
        self._refresh_icon_size()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._refresh_icon_size(force_focus=True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().focusOutEvent(event)
        self._refresh_icon_size()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pressed = True
        self._refresh_icon_size()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._pressed = False
        super().mouseReleaseEvent(event)
        self._refresh_icon_size()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(
            bounds,
            self._background_radius,
            self._background_radius,
        )
        painter.setClipPath(clip)
        paint_slice = getattr(self._background_source, "paint_ocean_slice", None)
        painted = bool(paint_slice and paint_slice(painter, self))
        if not painted:
            painter.fillRect(bounds, self._background_color)
        painter.end()
        super().paintEvent(event)

    def _refresh_icon_size(self, *, force_focus: bool = False) -> None:
        if not self._interaction_scaling_enabled:
            factor = 1.0
        elif self._pressed:
            factor = self.PRESSED_SCALE
        elif self._hovered or force_focus or self.hasFocus():
            factor = self.HOVER_SCALE
        else:
            factor = 1.0
        width = max(1, round(self._base_icon_size.width() * factor))
        height = max(1, round(self._base_icon_size.height() * factor))
        self.setIconSize(QSize(width, height))


class PanelDragHandle(QWidget):
    dragStarted = Signal(str)
    dragFinished = Signal(str)

    def __init__(self, panel_id: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.panel_id = panel_id
        self._press_position: QPoint | None = None
        self._color = QColor("#6b7280")
        self._scale = 1.0
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        parent.installEventFilter(self)
        self.apply_scale(1.0)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def apply_scale(self, scale: float) -> None:
        self._scale = max(1.0, float(scale))
        self.setFixedWidth(max(7, round(7 * self._scale)))
        self._sync_geometry()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if watched is self.parentWidget() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._press_position is None
            or not event.buttons() & Qt.MouseButton.LeftButton
            or (
                event.position().toPoint() - self._press_position
            ).manhattanLength() < QApplication.startDragDistance()
        ):
            super().mouseMoveEvent(event)
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(PANEL_DRAG_MIME_TYPE, self.panel_id.encode("ascii"))
        drag.setMimeData(mime)
        preview, hot_spot = self._make_drag_preview(self._press_position)
        drag.setPixmap(preview)
        drag.setHotSpot(hot_spot)
        self._press_position = None
        self.dragStarted.emit(self.panel_id)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.dragFinished.emit(self.panel_id)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_position = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(self._color)
        color.setAlpha(175)
        painter.setBrush(color)
        diameter = max(1.5, 1.6 * self._scale)
        gap = max(3.0, 4.0 * self._scale)
        center_y = self.height() / 2.0
        for column in (-1, 1):
            x = self.width() / 2.0 + column * diameter * 0.9
            for row in (-1, 0, 1):
                y = center_y + row * gap
                painter.drawEllipse(QPointF(x, y), diameter / 2.0, diameter / 2.0)
        painter.end()

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(1, 1, self.width(), max(1, parent.height() - 2))
            self.raise_()

    def _make_drag_preview(self, press_position: QPoint) -> tuple[QPixmap, QPoint]:
        panel = self.parentWidget()
        if panel is None:
            return QPixmap(), QPoint()

        source = panel.grab()
        max_width = max(300, round(500 * self._scale))
        max_height = max(80, round(150 * self._scale))
        factor = min(
            1.0,
            max_width / max(1, source.width()),
            max_height / max(1, source.height()),
        )
        content_size = QSize(
            max(1, round(source.width() * factor)),
            max(1, round(source.height() * factor)),
        )
        if content_size != source.size():
            source = source.scaled(
                content_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        radius = max(4.0, 6.0 * self._scale)
        preview = QPixmap(content_size)
        preview.fill(Qt.GlobalColor.transparent)
        painter = QPainter(preview)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        content_rect = QRectF(preview.rect())
        clip = QPainterPath()
        clip.addRoundedRect(content_rect, radius, radius)
        painter.setClipPath(clip)
        painter.setOpacity(0.72)
        painter.drawPixmap(content_rect.toRect(), source)
        painter.end()

        panel_press = self.mapTo(panel, press_position)
        hot_spot = QPoint(
            round(panel_press.x() * factor),
            round(panel_press.y() * factor),
        )
        return preview, hot_spot


class PanelInsertionIndicator(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._color = QColor("#00a7d6")
        self._scale = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def apply_scale(self, scale: float) -> None:
        self._scale = max(1.0, float(scale))
        self.update()

    def show_at(self, left: int, center_y: int, width: int) -> None:
        indicator_height = max(6, round(8 * self._scale))
        self.setGeometry(
            left,
            center_y - indicator_height // 2,
            max(1, width),
            indicator_height,
        )
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(
                self._color,
                max(2.0, 2.0 * self._scale),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        center_y = self.height() / 2.0
        inset = max(2.0, 3.0 * self._scale)
        painter.drawLine(
            QPointF(inset, center_y),
            QPointF(max(inset, self.width() - inset), center_y),
        )
        painter.end()


class ThemedBackground(QWidget):
    panelDropped = Signal(str, int)
    panelDragMoved = Signal(str, int)
    panelDragLeft = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ocean_enabled = False
        self._ocean_pixmap = QPixmap()
        self.setAcceptDrops(True)

    @property
    def ocean_enabled(self) -> bool:
        return self._ocean_enabled

    def set_ocean_enabled(self, enabled: bool) -> None:
        if self._ocean_enabled != enabled:
            self._ocean_enabled = enabled
            if not enabled:
                self._ocean_pixmap = QPixmap()
            self.update()

    def paint_ocean_slice(self, painter: QPainter, target: QWidget) -> bool:
        if not self._ocean_enabled or self._ocean_pixmap.isNull():
            return False
        origin = target.mapTo(self, target.rect().topLeft())
        painter.drawPixmap(
            QRectF(target.rect()),
            self._ocean_pixmap,
            QRectF(
                origin.x(),
                origin.y(),
                target.width(),
                target.height(),
            ),
        )
        return True

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(PANEL_DRAG_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(PANEL_DRAG_MIME_TYPE):
            panel_id = self._panel_id_from_mime(event.mimeData())
            if panel_id is None:
                event.ignore()
                return
            self.panelDragMoved.emit(
                panel_id,
                event.position().toPoint().y(),
            )
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.panelDragLeft.emit()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not event.mimeData().hasFormat(PANEL_DRAG_MIME_TYPE):
            super().dropEvent(event)
            return
        panel_id = self._panel_id_from_mime(event.mimeData())
        if panel_id is None:
            event.ignore()
            return
        self.panelDropped.emit(panel_id, event.position().toPoint().y())
        self.panelDragLeft.emit()
        event.acceptProposedAction()

    @staticmethod
    def _panel_id_from_mime(mime_data: QMimeData) -> str | None:
        try:
            return bytes(mime_data.data(PANEL_DRAG_MIME_TYPE)).decode("ascii")
        except (UnicodeDecodeError, ValueError):
            return None

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        if not self._ocean_enabled:
            return
        self._ensure_ocean_pixmap()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._ocean_pixmap)
        painter.end()

    def _ensure_ocean_pixmap(self) -> None:
        if (
            not self._ocean_pixmap.isNull()
            and self._ocean_pixmap.size() == self.size()
        ):
            return
        ocean_pixmap = QPixmap(self.size())
        ocean_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(ocean_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()

        water = QLinearGradient(0, 0, width, height)
        water.setColorAt(0.0, QColor("#9af3ff"))
        water.setColorAt(0.18, QColor("#64e5fa"))
        water.setColorAt(0.46, QColor("#26c8ef"))
        water.setColorAt(0.74, QColor("#0ba7df"))
        water.setColorAt(1.0, QColor("#096cbd"))
        painter.fillRect(self.rect(), water)

        surface_light = QLinearGradient(0, 0, 0, max(1, height * 0.34))
        surface_light.setColorAt(0.0, QColor(255, 255, 255, 84))
        surface_light.setColorAt(0.55, QColor(255, 255, 255, 24))
        surface_light.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), surface_light)

        for start, span, lean, alpha in (
            (0.04, 0.10, 0.16, 18),
            (0.30, 0.07, 0.10, 14),
            (0.60, 0.12, 0.18, 16),
            (0.86, 0.06, 0.08, 12),
        ):
            ray = QPainterPath(QPointF(width * start, -8))
            ray.lineTo(width * (start + span), -8)
            ray.cubicTo(
                width * (start + span + lean * 0.35),
                height * 0.28,
                width * (start + span + lean * 0.70),
                height * 0.55,
                width * (start + span + lean),
                height * 0.86,
            )
            ray.lineTo(width * (start + lean + span * 0.30), height * 0.86)
            ray.cubicTo(
                width * (start + lean * 0.58),
                height * 0.55,
                width * (start + lean * 0.26),
                height * 0.28,
                width * start,
                -8,
            )
            painter.fillPath(ray, QColor(255, 255, 255, alpha))

        for y_ratio, amplitude, alpha, stroke in (
            (0.16, 6, 58, 1.2),
            (0.34, 9, 50, 1.5),
            (0.57, 13, 36, 1.5),
            (0.78, 17, 28, 1.4),
        ):
            y = height * y_ratio
            wave = QPainterPath(QPointF(-20, y))
            wave.cubicTo(
                width * 0.16,
                y - amplitude,
                width * 0.30,
                y + amplitude,
                width * 0.48,
                y,
            )
            wave.cubicTo(
                width * 0.66,
                y - amplitude,
                width * 0.82,
                y + amplitude,
                width + 20,
                y,
            )
            painter.setPen(QPen(QColor(255, 255, 255, alpha), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(wave)

        for x_ratio, y_ratio, length_ratio, bend, alpha in (
            (0.05, 0.09, 0.12, -5, 72),
            (0.23, 0.12, 0.09, 4, 58),
            (0.46, 0.08, 0.14, -4, 68),
            (0.72, 0.13, 0.10, 5, 56),
            (0.84, 0.07, 0.11, -3, 64),
        ):
            x = width * x_ratio
            y = height * y_ratio
            caustic = QPainterPath(QPointF(x, y))
            caustic.cubicTo(
                x + width * length_ratio * 0.30,
                y + bend,
                x + width * length_ratio * 0.68,
                y - bend,
                x + width * length_ratio,
                y,
            )
            painter.setPen(QPen(QColor(255, 255, 255, alpha), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(caustic)

        depth = QLinearGradient(0, height * 0.48, 0, height)
        depth.setColorAt(0.0, QColor(5, 74, 157, 0))
        depth.setColorAt(1.0, QColor(4, 55, 137, 48))
        painter.fillRect(self.rect(), depth)

        bubbles = (
            (0.08, 0.43, 7),
            (0.17, 0.70, 4),
            (0.40, 0.53, 5),
            (0.72, 0.40, 4),
            (0.84, 0.63, 8),
            (0.94, 0.47, 5),
        )
        painter.setBrush(QColor(255, 255, 255, 22))
        for x_ratio, y_ratio, radius in bubbles:
            center = QPointF(width * x_ratio, height * y_ratio)
            painter.setPen(QPen(QColor(255, 255, 255, 105), 1.2))
            painter.drawEllipse(center, radius, radius)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 120))
            highlight = max(1.2, radius * 0.22)
            painter.drawEllipse(
                QPointF(center.x() - radius * 0.32, center.y() - radius * 0.34),
                highlight,
                highlight,
            )
            painter.setBrush(QColor(255, 255, 255, 22))
        painter.end()
        self._ocean_pixmap = ocean_pixmap


class PianoKeyboardWidget(QWidget):
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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._active_notes: frozenset[int] = frozenset()
        self._surface = QColor("#ffffff")
        self._border = QColor("#9aa5b1")
        self._text = QColor("#5d6878")
        self._black = QColor("#202632")
        self._accent = QColor("#00a7d6")
        self._accent_border = QColor("#0093bd")
        self._accent_text = QColor("#ffffff")
        self._last_retrigger_serials: dict[int, int] = {}
        self._retrigger_release_until: dict[int, float] = {}
        self._retrigger_timer = QTimer(self)
        self._retrigger_timer.setInterval(16)
        self._retrigger_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._retrigger_timer.timeout.connect(self._advance_retrigger_release)
        self._rendering_enabled = True
        self.apply_scale(1.0)

    @property
    def active_notes(self) -> frozenset[int]:
        return self._active_notes

    @property
    def rendering_enabled(self) -> bool:
        return self._rendering_enabled

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
        if enabled:
            try:
                for note, serial in current_retrigger_events:  # type: ignore[union-attr]
                    self._last_retrigger_serials[int(note)] = int(serial)
            except (TypeError, ValueError):
                pass
            self.update()

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
            self.update()

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
            if not self.NOTE_MIN <= note <= self.NOTE_MAX:
                continue
            self._retrigger_release_until[note] = release_until
            changed = True
        if not changed:
            return
        if not self._retrigger_timer.isActive():
            self._retrigger_timer.start()
        self.update()

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
        if not self._retrigger_release_until:
            self._retrigger_timer.stop()
        self.update()

    def set_colors(
        self,
        surface: str,
        border: str,
        text: str,
        accent: str,
        accent_border: str,
        accent_text: str,
    ) -> None:
        self._surface = QColor(surface)
        self._border = QColor(border)
        self._text = QColor(text)
        self._accent = QColor(accent)
        self._accent_border = QColor(accent_border)
        self._accent_text = QColor(accent_text)
        self.update()

    def apply_scale(self, scale: float) -> None:
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setFixedHeight(max(1, round(self.BASE_HEIGHT * scale)))

    def sizeHint(self) -> QSize:
        return QSize(420, self.BASE_HEIGHT)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(1.0, float(self.width() - 1))
        height = max(1.0, float(self.height() - 1))
        painter.fillRect(self.rect(), self._surface)
        white_notes = [
            note
            for note in range(self.NOTE_MIN, self.NOTE_MAX + 1)
            if note % 12 in self.WHITE_PITCH_CLASSES
        ]
        white_width = width / len(white_notes)
        border_pen = QPen(self._border, 1.0)
        label_font = painter.font()
        label_font.setPixelSize(
            max(7, min(12, round(min(height * 0.16, white_width * 0.9))))
        )

        for index, note in enumerate(white_notes):
            key_rect = QRectF(index * white_width + 0.5, 0.5, white_width, height)
            active = (
                note in self._active_notes
                and note not in self._retrigger_release_until
            )
            painter.fillRect(key_rect, self._accent if active else self._surface)
            painter.setPen(QPen(self._accent_border, 1.0) if active else border_pen)
            painter.drawRect(key_rect)

        for index, note in enumerate(white_notes):
            if note == self.NOTE_MIN or note % 12 == 0:
                painter.setFont(label_font)
                painter.setPen(self._text)
                key_center = (index + 0.5) * white_width
                label_text = (
                    f"A{note // 12 - 1}"
                    if note == self.NOTE_MIN
                    else f"C{note // 12 - 1}"
                )
                label_width = min(
                    width,
                    max(1.0, float(painter.fontMetrics().horizontalAdvance(label_text) + 2)),
                )
                label_left = max(
                    0.5,
                    min(width - label_width, key_center - label_width / 2),
                )
                label_rect = QRectF(
                    label_left,
                    0.5,
                    label_width,
                    height,
                )
                painter.drawText(
                    label_rect.adjusted(0, 0, 0, -2),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                    label_text,
                )

        black_width = white_width * 0.62
        black_height = height * 0.60
        for note in range(self.NOTE_MIN, self.NOTE_MAX + 1):
            if note % 12 not in self.BLACK_BOUNDARIES:
                continue
            previous_white = note - 1
            if previous_white not in white_notes:
                continue
            center_x = (white_notes.index(previous_white) + 1) * white_width
            key_rect = QRectF(center_x - black_width / 2, 0.5, black_width, black_height)
            active = (
                note in self._active_notes
                and note not in self._retrigger_release_until
            )
            painter.fillRect(key_rect, self._accent if active else self._black)
            painter.setPen(QPen(self._accent_border if active else self._border, 1.0))
            painter.drawRect(key_rect)
        painter.end()


@dataclass(frozen=True)
class _RhythmHitImpact:
    serial: int
    note: int
    started_at: float
    judgment: str
    released: bool


@dataclass(frozen=True)
class _RhythmLaneFade:
    serial: int
    note: int
    started_at: float
    missed: bool


class FallingNotesWidget(QWidget):
    NOTE_MIN = PIANO_NOTE_MIN
    NOTE_MAX = PIANO_NOTE_MAX
    BASE_HEIGHT = PianoKeyboardWidget.BASE_HEIGHT
    PREVIEW_SECONDS = 1.0
    IMPACT_SECONDS = 0.24
    IMPACT_DURATION_SECONDS = {
        "PERFECT": 0.24,
        "GREAT": 0.18,
        "GOOD": 0.12,
    }
    IMPACT_SIZE_SCALE = 1.0
    IMPACT_OPACITY = 1.0
    PERFECT_IMPACT_OPACITY = 0.50
    PERFECT_RELEASE_IMPACT_OPACITY = 0.20
    RELEASE_IMPACT_SIZE_SCALE = 0.60
    RELEASE_IMPACT_OPACITY = 0.70
    RELEASE_IMPACT_PARTICLE_SCALE = 0.50
    LANE_FADE_SECONDS = 0.15
    HELD_LANE_OPACITY = 0.28
    MISSED_LANE_OPACITY = 0.60
    MISSED_LANE_COLOR = "#ff3158"
    APPROACHING_TRAIL_GLOW_STOPS = ((0.0, 0), (0.55, 31), (1.0, 120))
    APPROACHING_TRAIL_CORE_STOPS = ((0.0, 16), (0.62, 189), (1.0, 255))
    HELD_TRAIL_GLOW_STOPS = ((0.0, 0), (0.60, 31), (0.88, 57), (1.0, 0))
    HELD_TRAIL_CORE_STOPS = ((0.0, 16), (0.58, 189), (0.88, 150), (1.0, 0))
    WHITE_PITCH_CLASSES = PianoKeyboardWidget.WHITE_PITCH_CLASSES
    BLACK_PITCH_CLASSES = frozenset((1, 3, 6, 8, 10))
    LIGHT_BAR_INTENSITY_STEPS = 12
    IMPACT_PROGRESS_STEPS = 24
    SUBPIXEL_STEPS = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FallingNotes")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._sequence_notes: tuple[PianoRollNote, ...] = ()
        self._sequence_starts: tuple[float, ...] = ()
        self._sequence_by_end: tuple[PianoRollNote, ...] = ()
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
        self._frame_position = 0.0
        self._frame_visible_notes: tuple[PianoRollNote, ...] = ()
        self._frame_visible_lanes: frozenset[int] = frozenset()
        self._score = 0
        self._combo = 0
        self._judgment = ""
        self._multiplier_tenths = 10
        self._hit_impacts: list[_RhythmHitImpact] = []
        self._held_lane_counts: dict[int, int] = {}
        self._lane_fades: list[_RhythmLaneFade] = []
        self._last_hit_serial = 0
        self._surface = QColor("#000000")
        self._border = QColor("#9aa5b1")
        self._grid = QColor("#d5dde7")
        self._scheduled = QColor("#00a7d6")
        self._live = QColor("#0093bd")
        self._scale = 1.0
        self._static_layer: QPixmap | None = None
        self._grid_layer: QPixmap | None = None
        self._frame_layer: QPixmap | None = None
        self._score_layer: QPixmap | None = None
        self._score_layer_position = QPoint()
        self._note_rect_cache_width = -1.0
        self._note_rect_cache: dict[int, tuple[float, float]] = {}
        self._note_body_cache: dict[tuple[object, ...], QPixmap] = {}
        self._light_bar_cache: dict[tuple[object, ...], QPixmap] = {}
        self._impact_cache: dict[tuple[object, ...], QPixmap] = {}
        self._pending_effect_notes: set[int] = set()
        self._score_update_pending = False
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(16)
        self._animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._animation_timer.timeout.connect(self._advance_animation)
        self._rendering_enabled = True
        self.apply_scale(1.0)

    @property
    def sequence_notes(self) -> tuple[PianoRollNote, ...]:
        return self._sequence_notes

    @property
    def rendering_enabled(self) -> bool:
        return self._rendering_enabled

    @property
    def live_trail_count(self) -> int:
        return 0

    @property
    def score(self) -> int:
        return self._score

    @property
    def combo(self) -> int:
        return self._combo

    @property
    def judgment(self) -> str:
        return self._judgment

    @property
    def multiplier_tenths(self) -> int:
        return self._multiplier_tenths

    @property
    def hit_impact_count(self) -> int:
        return len(self._hit_impacts)

    @property
    def held_lane_notes(self) -> frozenset[int]:
        return frozenset(self._held_lane_counts)

    @property
    def lane_fade_count(self) -> int:
        return len(self._lane_fades)

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
        self._pending_effect_notes.clear()
        self._score_update_pending = False
        self._hit_impacts.clear()
        self._held_lane_counts.clear()
        self._lane_fades.clear()
        self._frame_visible_notes = ()
        self._frame_visible_lanes = frozenset()
        self._playback_running = False
        self._reset_active_sequence_cache()
        if enabled:
            try:
                serials = []
                for event in latest_hit_events:  # type: ignore[union-attr]
                    values = tuple(event)
                    if values:
                        serials.append(int(values[0]))
                self._last_hit_serial = max(
                    serials,
                    default=self._last_hit_serial,
                )
            except (TypeError, ValueError, IndexError):
                pass
            self.update()

    def set_score(
        self,
        score: int,
        combo: int,
        judgment: str = "",
        multiplier_tenths: int = 10,
    ) -> None:
        if not self._rendering_enabled:
            return
        next_score = max(0, int(score))
        next_combo = max(0, int(combo))
        next_judgment = str(judgment).upper()
        next_multiplier_tenths = max(10, min(20, int(multiplier_tenths)))
        if (
            self._score == next_score
            and self._combo == next_combo
            and self._judgment == next_judgment
            and self._multiplier_tenths == next_multiplier_tenths
        ):
            return
        dirty_notes = {
            impact.note for impact in self._hit_impacts
        } | set(self._held_lane_counts) | {
            fade.note for fade in self._lane_fades
        }
        self._score = next_score
        self._combo = next_combo
        self._judgment = next_judgment
        self._multiplier_tenths = next_multiplier_tenths
        if not next_score and not next_combo and not next_judgment:
            self._hit_impacts.clear()
            self._held_lane_counts.clear()
            self._lane_fades.clear()
            self._update_animation_timer()
        self._score_layer = None
        if self._playback_running or self._animation_timer.isActive():
            self._score_update_pending = True
            self._pending_effect_notes.update(dirty_notes)
        else:
            self.update(self._score_update_rect())
            self._update_note_lanes(
                dirty_notes,
                include_effect_margin=True,
            )

    def set_hit_events(self, events: object) -> None:
        if not self._rendering_enabled:
            return
        try:
            normalized_events = []
            for raw_event in events:  # type: ignore[union-attr]
                values = tuple(raw_event)
                if len(values) == 3:
                    serial, note, judgment = values
                    released = False
                elif len(values) == 4:
                    serial, note, judgment, released = values
                else:
                    return
                normalized_events.append(
                    (
                        int(serial),
                        int(note),
                        str(judgment).upper(),
                        bool(released),
                    )
                )
            normalized = tuple(
                sorted(normalized_events, key=lambda item: item[0])
            )
        except (TypeError, ValueError):
            return
        now = time.monotonic()
        changed = False
        for serial, note, judgment, released in normalized:
            if serial <= self._last_hit_serial:
                continue
            self._last_hit_serial = serial
            if not self.NOTE_MIN <= note <= self.NOTE_MAX:
                continue
            if judgment == "MISS":
                if released:
                    self._release_held_lane(note)
                self._lane_fades.append(
                    _RhythmLaneFade(
                        serial=serial,
                        note=note,
                        started_at=now,
                        missed=True,
                    )
                )
            elif judgment in {"PERFECT", "GREAT", "GOOD"}:
                if released:
                    self._release_held_lane(note)
                    self._lane_fades.append(
                        _RhythmLaneFade(
                            serial=serial,
                            note=note,
                            started_at=now,
                            missed=False,
                        )
                    )
                else:
                    self._held_lane_counts[note] = (
                        self._held_lane_counts.get(note, 0) + 1
                    )
                self._hit_impacts.append(
                    _RhythmHitImpact(
                        serial=serial,
                        note=note,
                        started_at=now,
                        judgment=judgment,
                        released=released,
                    )
                )
            else:
                continue
            changed = True
        if changed:
            self._hit_impacts = self._hit_impacts[-64:]
            self._lane_fades = self._lane_fades[-64:]
            self._update_animation_timer()
            changed_notes = {
                note
                for _serial, note, _judgment, _released in normalized
            }
            if self._animation_timer.isActive():
                self._pending_effect_notes.update(changed_notes)
            else:
                self._update_note_lanes(
                    changed_notes,
                    include_effect_margin=True,
                )

    def _release_held_lane(self, note: int) -> None:
        active_count = self._held_lane_counts.get(note, 0)
        if active_count <= 1:
            self._held_lane_counts.pop(note, None)
        else:
            self._held_lane_counts[note] = active_count - 1

    def set_sequence_notes(self, notes: tuple[PianoRollNote, ...]) -> None:
        if not self._rendering_enabled:
            return
        normalized = tuple(sorted(notes, key=lambda item: (item.start, item.note, item.end)))
        if normalized != self._sequence_notes:
            self._sequence_notes = normalized
            self._sequence_starts = tuple(note.start for note in normalized)
            self._sequence_end_entries = tuple(
                sorted(
                    (
                        (note.end, index)
                        for index, note in enumerate(normalized)
                    ),
                    key=lambda item: (
                        item[0],
                        normalized[item[1]].start,
                        normalized[item[1]].note,
                    ),
                )
            )
            self._sequence_by_end = tuple(
                normalized[index]
                for _end, index in self._sequence_end_entries
            )
            self._sequence_ends = tuple(end for end, _index in self._sequence_end_entries)
            self._reset_active_sequence_cache()
            self._frame_visible_notes = ()
            self._frame_visible_lanes = frozenset()
            self.update()

    def set_playback_state(
        self,
        position: float,
        speed_percent: int,
        running: bool,
    ) -> None:
        if not self._rendering_enabled:
            return
        was_running = self._playback_running
        self._position = max(0.0, float(position))
        self._position_anchor = time.monotonic()
        self._speed_ratio = max(0.1, min(2.0, int(speed_percent) / 100.0))
        self._playback_running = bool(running)
        self._update_animation_timer()
        if self._playback_running and was_running:
            return
        dirty_notes = self._prepare_animation_frame(self._position_anchor)
        self._update_note_lanes(dirty_notes)

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
        if not stale:
            return
        for note in stale:
            self._held_lane_counts.pop(note, None)
        self._update_animation_timer()
        self._update_note_lanes(stale)

    def set_colors(
        self,
        surface: str,
        border: str,
        grid: str,
        scheduled: str,
        live: str,
    ) -> None:
        self._surface = QColor(surface)
        self._border = QColor(border)
        self._grid = QColor(grid)
        self._scheduled = QColor(scheduled)
        self._live = QColor(live)
        self._invalidate_render_cache()
        self.update()

    def apply_scale(self, scale: float) -> None:
        self._scale = max(0.5, float(scale))
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setFixedHeight(max(1, round(self.BASE_HEIGHT * scale)))
        self._invalidate_render_cache()

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
        effect_notes = set(self._pending_effect_notes) | {
            impact.note for impact in self._hit_impacts
        } | {
            fade.note for fade in self._lane_fades
        }
        self._pending_effect_notes.clear()
        self._hit_impacts = [
            impact
            for impact in self._hit_impacts
            if now - impact.started_at
            <= self._impact_duration(impact.judgment)
        ]
        self._lane_fades = [
            fade
            for fade in self._lane_fades
            if now - fade.started_at <= self.LANE_FADE_SECONDS
        ]
        effect_notes.update(impact.note for impact in self._hit_impacts)
        effect_notes.update(fade.note for fade in self._lane_fades)
        moving_notes = self._prepare_animation_frame(now)
        self._update_animation_timer()
        self._update_note_lanes(moving_notes)
        self._update_note_lanes(effect_notes, include_effect_margin=True)
        if self._score_update_pending:
            self._score_update_pending = False
            self.update(self._score_update_rect())

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

    def _prepare_animation_frame(self, now: float) -> set[int]:
        position = self._current_position(now)
        song_horizon = self.PREVIEW_SECONDS * self._speed_ratio
        visible_notes = self._visible_sequence_notes(position, song_horizon)
        visible_lanes = frozenset(note.note for note in visible_notes)
        dirty_lanes = set(self._frame_visible_lanes | visible_lanes)
        self._frame_position = position
        self._frame_visible_notes = visible_notes
        self._frame_visible_lanes = visible_lanes
        return dirty_lanes

    def _note_rect(self, note: int, width: float) -> tuple[float, float] | None:
        if abs(self._note_rect_cache_width - width) > 0.01:
            self._rebuild_note_rect_cache(width)
        return self._note_rect_cache.get(int(note))

    def _rebuild_note_rect_cache(self, width: float) -> None:
        white_notes = tuple(
            value
            for value in range(self.NOTE_MIN, self.NOTE_MAX + 1)
            if value % 12 in self.WHITE_PITCH_CLASSES
        )
        white_width = width / len(white_notes)
        white_indexes = {
            note: index for index, note in enumerate(white_notes)
        }
        cache: dict[int, tuple[float, float]] = {}
        for note in range(self.NOTE_MIN, self.NOTE_MAX + 1):
            if note in white_indexes:
                center = (white_indexes[note] + 0.5) * white_width
                note_width = white_width
            elif (
                note % 12 in self.BLACK_PITCH_CLASSES
                and note - 1 in white_indexes
            ):
                center = (white_indexes[note - 1] + 1) * white_width
                note_width = white_width * 0.62
            else:
                continue
            cache[note] = (center - note_width / 2, note_width)
        self._note_rect_cache_width = width
        self._note_rect_cache = cache

    def _invalidate_render_cache(self) -> None:
        self._static_layer = None
        self._grid_layer = None
        self._frame_layer = None
        self._score_layer = None
        self._note_body_cache.clear()
        self._light_bar_cache.clear()
        self._impact_cache.clear()
        self._note_rect_cache_width = -1.0
        self._note_rect_cache.clear()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._invalidate_render_cache()
        super().resizeEvent(event)

    def _ensure_static_layer(self, width: float, height: float) -> QPixmap:
        if (
            self._static_layer is not None
            and self._grid_layer is not None
            and self._frame_layer is not None
            and self._static_layer.size() == self.size()
        ):
            return self._static_layer
        layer = QPixmap(self.size())
        layer.fill(self._surface)
        painter = QPainter(layer)
        painter.end()
        grid_layer = QPixmap(self.size())
        grid_layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(grid_layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        white_notes = tuple(
            note
            for note in range(self.NOTE_MIN, self.NOTE_MAX + 1)
            if note % 12 in self.WHITE_PITCH_CLASSES
        )
        white_width = width / len(white_notes)
        lane_color = QColor(self._grid)
        lane_color.setAlpha(175)
        painter.setPen(QPen(lane_color, max(0.8, 0.75 * self._scale)))
        for index in range(len(white_notes) + 1):
            x = index * white_width + 0.5
            painter.drawLine(QPointF(x, 0.5), QPointF(x, height))
        octave_color = QColor(self._border)
        octave_color.setAlpha(150)
        painter.setPen(QPen(octave_color, max(1.0, self._scale)))
        for index, note in enumerate(white_notes):
            if note == self.NOTE_MIN or note % 12 == 0:
                x = index * white_width + 0.5
                painter.drawLine(QPointF(x, 0.5), QPointF(x, height))
        painter.end()
        frame_layer = QPixmap(self.size())
        frame_layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame_layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self._border, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0.5, 0.5, width, height))
        hit_line = QLinearGradient(0.5, 0.0, width, 0.0)
        for position, alpha in ((0.0, 35), (0.5, 185), (1.0, 35)):
            color = QColor(self._live)
            color.setAlpha(alpha)
            hit_line.setColorAt(position, color)
        painter.setPen(QPen(hit_line, 1.5 * self._scale))
        painter.drawLine(
            QPointF(0.5, height - 0.5),
            QPointF(width, height - 0.5),
        )
        painter.end()
        self._static_layer = layer
        self._grid_layer = grid_layer
        self._frame_layer = frame_layer
        return layer

    def _update_note_lanes(
        self,
        notes: set[int],
        *,
        include_effect_margin: bool = False,
    ) -> None:
        if not notes:
            return
        width = max(1.0, float(self.width() - 1))
        for note in sorted(notes):
            horizontal = self._note_rect(note, width)
            if horizontal is None:
                continue
            x, note_width = horizontal
            effect_margin = (
                max(48.0 * self._scale, note_width * 3.0)
                if include_effect_margin
                else max(2.0 * self._scale, note_width * 0.12)
            )
            left = max(0.0, x - effect_margin)
            right = min(width, x + note_width + effect_margin)
            self.update(
                QRectF(
                    left,
                    0.0,
                    right - left + 1.0,
                    float(self.height()),
                ).toAlignedRect()
            )

    def _score_update_rect(self) -> QRect:
        height = max(1, round(18 * self._scale))
        return QRect(0, 0, max(1, self.width()), min(self.height(), height))

    def _ensure_score_layer(self) -> tuple[QPixmap, QPoint]:
        if self._score_layer is not None:
            return self._score_layer, self._score_layer_position
        score_font = self.font()
        score_font.setBold(True)
        score_font.setPixelSize(max(8, round(9 * self._scale)))
        metrics = QFontMetricsF(score_font)
        score_text = self._score_text()
        padding = max(2, round(4 * self._scale))
        text_width = max(1, round(metrics.horizontalAdvance(score_text)))
        text_height = max(1, round(metrics.height()))
        layer = QPixmap(text_width + padding * 2, text_height + padding)
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        painter.setFont(score_font)
        dark_surface = self._surface.lightness() < 128
        shadow = (
            QColor(0, 0, 0, 150)
            if dark_surface
            else QColor(255, 255, 255, 190)
        )
        score_color = (
            QColor(255, 255, 255)
            if dark_surface
            else QColor(self._border).darker(190)
        )
        text_rect = QRectF(
            float(padding),
            0.0,
            float(text_width),
            float(text_height + padding),
        )
        painter.setPen(shadow)
        painter.drawText(
            text_rect.translated(1.0 * self._scale, 1.0 * self._scale),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            score_text,
        )
        painter.setPen(score_color)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            score_text,
        )
        painter.end()
        self._score_layer = layer
        self._score_layer_position = QPoint(
            max(0, self.width() - layer.width() - padding),
            max(0, round(2 * self._scale)),
        )
        return layer, self._score_layer_position

    @staticmethod
    def _region_intersects_lane(
        region,
        x: float,
        note_width: float,
        height: float,
        margin: float = 0.0,
    ) -> bool:
        return region.intersects(
            QRectF(
                x - margin,
                0.0,
                note_width + margin * 2.0,
                height,
            ).toAlignedRect()
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
        upcoming = self._sequence_notes[left:right]
        return tuple(
            sorted(
                (*active, *upcoming),
                key=lambda item: (item.start, item.note, item.end),
            )
        )

    def _active_sequence_notes(
        self,
        position: float,
    ) -> tuple[PianoRollNote, ...]:
        started_right = bisect_right(self._sequence_starts, position)
        ending_left = bisect_right(self._sequence_ends, position)
        previous_position = self._active_query_position
        if previous_position is None:
            if started_right <= len(self._sequence_notes) - ending_left:
                active = set(range(started_right))
                for _end, index in self._sequence_end_entries[:ending_left]:
                    active.discard(index)
            else:
                active = {
                    index
                    for _end, index in self._sequence_end_entries[ending_left:]
                    if index < started_right
                }
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

    def _draw_impact_core(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        radius: float,
        color: QColor,
        intensity: float,
    ) -> None:
        glow = QRadialGradient(QPointF(center_x, center_y), radius)
        glow_center = QColor(color)
        glow_center.setAlpha(round(220 * intensity))
        glow_edge = QColor(color)
        glow_edge.setAlpha(0)
        glow.setColorAt(0.0, glow_center)
        glow.setColorAt(1.0, glow_edge)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(
            QRectF(
                center_x - radius,
                center_y - radius,
                radius * 2.0,
                radius * 2.0,
            )
        )

        accent = QColor(color).darker(108)
        accent.setAlpha(round(225 * intensity))
        painter.setPen(
            QPen(
                accent,
                max(1.1 * self._scale, radius * 0.28),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        for start, end in (
            (
                QPointF(center_x, center_y - radius * 0.88),
                QPointF(center_x, center_y + radius * 0.88),
            ),
            (
                QPointF(center_x - radius * 0.88, center_y),
                QPointF(center_x + radius * 0.88, center_y),
            ),
        ):
            painter.drawLine(start, end)

    def _draw_light_bar(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        note_width: float,
        color: QColor,
        intensity: float,
    ) -> None:
        if not isinstance(painter, QPainter):
            self._draw_light_bar_direct(
                painter,
                center_x,
                center_y,
                note_width,
                color,
                intensity,
            )
            return
        intensity = max(0.0, min(1.0, float(intensity)))
        center_y = self._quantize_subpixel(center_y)
        intensity_bucket = min(
            self.LIGHT_BAR_INTENSITY_STEPS - 1,
            round(intensity * (self.LIGHT_BAR_INTENSITY_STEPS - 1)),
        )
        bar_height, outline_width = self._light_bar_metrics(note_width)
        glow_height = max(4.0 * self._scale, bar_height * 2.0)
        asset_height = max(
            1,
            math.ceil(
                max(glow_height, bar_height + outline_width * 2.0) + 4.0
            ),
        )
        asset_top = math.floor(center_y - asset_height / 2.0)
        local_center_y = center_y - asset_top
        cache_key = (
            round(note_width, 2),
            color.rgba(),
            intensity_bucket,
            round(local_center_y * self.SUBPIXEL_STEPS),
            round(self._scale, 3),
        )
        asset = self._light_bar_cache.get(cache_key)
        if asset is None:
            quantized_intensity = intensity_bucket / max(
                1,
                self.LIGHT_BAR_INTENSITY_STEPS - 1,
            )
            asset_width = max(
                1,
                math.ceil(note_width + outline_width * 2.0 + 2.0),
            )
            asset = QPixmap(asset_width, asset_height)
            asset.fill(Qt.GlobalColor.transparent)
            asset_painter = QPainter(asset)
            asset_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_light_bar_direct(
                asset_painter,
                asset_width / 2.0,
                local_center_y,
                note_width,
                color,
                quantized_intensity,
            )
            asset_painter.end()
            self._light_bar_cache[cache_key] = asset
        painter.drawPixmap(
            round(center_x - asset.width() / 2.0),
            asset_top,
            asset,
        )

    def _draw_light_bar_direct(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        note_width: float,
        color: QColor,
        intensity: float,
    ) -> None:
        bar_width = note_width
        bar_height, outline_width = self._light_bar_metrics(note_width)
        glow_height = max(4.0 * self._scale, bar_height * 2.0)
        corner_radius = min(1.2 * self._scale, bar_height / 3.0)

        glow = QLinearGradient(
            center_x,
            center_y - glow_height / 2.0,
            center_x,
            center_y + glow_height / 2.0,
        )
        glow_edge = QColor(color)
        glow_edge.setAlpha(0)
        glow_center = QColor(color)
        glow_center.setAlpha(round(120 * intensity))
        glow.setColorAt(0.0, glow_edge)
        glow.setColorAt(0.5, glow_center)
        glow.setColorAt(1.0, glow_edge)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawRoundedRect(
            QRectF(
                center_x - bar_width / 2.0,
                center_y - glow_height / 2.0,
                bar_width,
                glow_height,
            ),
            corner_radius,
            corner_radius,
        )

        core = QLinearGradient(
            center_x - bar_width / 2.0,
            center_y,
            center_x + bar_width / 2.0,
            center_y,
        )
        edge = QColor(color).lighter(125)
        edge.setAlpha(round(225 * intensity))
        center = QColor(255, 255, 255, round(255 * intensity))
        core.setColorAt(0.0, edge)
        core.setColorAt(0.18, center)
        core.setColorAt(0.82, center)
        core.setColorAt(1.0, edge)
        outline = QColor(color).darker(108)
        outline.setAlpha(round(230 * intensity))
        painter.setPen(QPen(outline, outline_width))
        painter.setBrush(core)
        painter.drawRoundedRect(
            QRectF(
                center_x - bar_width / 2.0,
                center_y - bar_height / 2.0,
                bar_width,
                bar_height,
            ),
            corner_radius,
            corner_radius,
        )

    def _light_bar_metrics(self, note_width: float) -> tuple[float, float]:
        return (
            max(2.0 * self._scale, note_width * 0.12),
            max(0.6, 0.65 * self._scale),
        )

    def _minimum_note_body_height(self, note_width: float) -> float:
        return max(
            4.0 * self._scale,
            min(6.0 * self._scale, note_width * 0.35),
        )

    def _quantize_subpixel(self, value: float) -> float:
        return round(float(value) * self.SUBPIXEL_STEPS) / self.SUBPIXEL_STEPS

    def _clamp_light_bar_center(self, center_y: float, note_width: float) -> float:
        bar_height, outline_width = self._light_bar_metrics(note_width)
        half_extent = (bar_height + outline_width) / 2.0
        drawable_bottom = float(self.height() - 1)
        return max(
            half_extent,
            min(drawable_bottom - half_extent, center_y),
        )

    def _draw_note_span(
        self,
        painter: QPainter,
        x: float,
        note_width: float,
        top: float,
        bottom: float,
        color: QColor,
        show_head: bool = True,
        now: float | None = None,
        phase_seed: float = 0.0,
    ) -> None:
        drawable_top = 0.5
        drawable_bottom = float(self.height() - 1)
        top = max(drawable_top, min(drawable_bottom, top))
        bottom = max(top, min(drawable_bottom, bottom))
        center_x = x + note_width / 2.0
        head_y = self._clamp_light_bar_center(bottom, note_width)
        if show_head:
            trail_top = min(top, head_y)
            trail_bottom = max(bottom, head_y)
        else:
            trail_top = min(top, bottom)
            trail_bottom = max(top, bottom)
        minimum_height = (
            self._minimum_note_body_height(note_width)
            if show_head
            else 0.0
        )
        if trail_bottom - trail_top < minimum_height:
            trail_top = max(drawable_top, trail_bottom - minimum_height)
        trail_height = max(0.0, trail_bottom - trail_top)
        if trail_height <= 0.0:
            return

        if isinstance(painter, QPainter):
            trail_top = self._quantize_subpixel(trail_top)
            trail_bottom = max(
                trail_top,
                self._quantize_subpixel(trail_bottom),
            )
            asset_top = math.floor(trail_top) - 1
            asset_bottom = math.ceil(trail_bottom) + 1
            local_top = trail_top - asset_top
            local_bottom = trail_bottom - asset_top
            body = self._note_body_asset(
                note_width,
                local_top,
                local_bottom,
                asset_bottom - asset_top,
                color,
                show_head,
            )
            painter.drawPixmap(
                round(center_x - body.width() / 2.0),
                asset_top,
                body,
            )
            animation_time = time.monotonic() if now is None else now
            twinkle = 0.82 + 0.18 * (
                math.sin(animation_time * 7.0 + phase_seed * 0.73) + 1.0
            ) / 2.0
            if show_head:
                self._draw_light_bar(
                    painter,
                    center_x,
                    head_y,
                    note_width,
                    color,
                    twinkle,
                )
            return

        glow_width = max(7.0 * self._scale, note_width * 0.58)
        core_width = max(1.8 * self._scale, note_width * 0.12)
        glow_gradient = QLinearGradient(0.0, trail_top, 0.0, trail_bottom)
        core_gradient = QLinearGradient(0.0, trail_top, 0.0, trail_bottom)
        if show_head:
            glow_stops = self.APPROACHING_TRAIL_GLOW_STOPS
            core_stops = self.APPROACHING_TRAIL_CORE_STOPS
        else:
            glow_stops = self.HELD_TRAIL_GLOW_STOPS
            core_stops = self.HELD_TRAIL_CORE_STOPS
        for position, alpha in glow_stops:
            stop_color = QColor(color)
            stop_color.setAlpha(alpha)
            glow_gradient.setColorAt(position, stop_color)
        for position, alpha in core_stops:
            stop_color = (
                QColor(255, 255, 255)
                if alpha >= 200
                else QColor(color).lighter(155)
            )
            stop_color.setAlpha(alpha)
            core_gradient.setColorAt(position, stop_color)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow_gradient)
        painter.drawRoundedRect(
            QRectF(
                center_x - glow_width / 2.0,
                trail_top,
                glow_width,
                trail_height,
            ),
            glow_width / 2.0,
            glow_width / 2.0,
        )
        painter.setBrush(core_gradient)
        painter.drawRoundedRect(
            QRectF(
                center_x - core_width / 2.0,
                trail_top,
                core_width,
                trail_height,
            ),
            core_width / 2.0,
            core_width / 2.0,
        )

        animation_time = time.monotonic() if now is None else now
        twinkle = 0.82 + 0.18 * (
            math.sin(animation_time * 7.0 + phase_seed * 0.73) + 1.0
        ) / 2.0
        if show_head:
            self._draw_light_bar(
                painter,
                center_x,
                head_y,
                note_width,
                color,
                twinkle,
            )

    def _note_body_asset(
        self,
        note_width: float,
        trail_top: float,
        trail_bottom: float,
        asset_height: int,
        color: QColor,
        show_head: bool,
    ) -> QPixmap:
        asset_height = max(1, int(asset_height))
        trail_top = max(0.0, float(trail_top))
        trail_bottom = max(trail_top, float(trail_bottom))
        trail_height = max(0.0, trail_bottom - trail_top)
        cache_key = (
            round(note_width, 2),
            round(trail_top * self.SUBPIXEL_STEPS),
            round(trail_bottom * self.SUBPIXEL_STEPS),
            asset_height,
            color.rgba(),
            bool(show_head),
            round(self._scale, 3),
        )
        asset = self._note_body_cache.get(cache_key)
        if asset is not None:
            return asset
        glow_width = max(7.0 * self._scale, note_width * 0.58)
        core_width = max(1.8 * self._scale, note_width * 0.12)
        asset_width = max(1, math.ceil(max(glow_width, core_width) + 2.0))
        asset = QPixmap(asset_width, asset_height)
        asset.fill(Qt.GlobalColor.transparent)
        painter = QPainter(asset)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        glow_gradient = QLinearGradient(
            0.0,
            trail_top,
            0.0,
            trail_bottom,
        )
        core_gradient = QLinearGradient(
            0.0,
            trail_top,
            0.0,
            trail_bottom,
        )
        if show_head:
            glow_stops = self.APPROACHING_TRAIL_GLOW_STOPS
            core_stops = self.APPROACHING_TRAIL_CORE_STOPS
        else:
            glow_stops = self.HELD_TRAIL_GLOW_STOPS
            core_stops = self.HELD_TRAIL_CORE_STOPS
        for position, alpha in glow_stops:
            stop_color = QColor(color)
            stop_color.setAlpha(alpha)
            glow_gradient.setColorAt(position, stop_color)
        for position, alpha in core_stops:
            stop_color = (
                QColor(255, 255, 255)
                if alpha >= 200
                else QColor(color).lighter(155)
            )
            stop_color.setAlpha(alpha)
            core_gradient.setColorAt(position, stop_color)
        center_x = asset_width / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow_gradient)
        painter.drawRoundedRect(
            QRectF(
                center_x - glow_width / 2.0,
                trail_top,
                glow_width,
                trail_height,
            ),
            glow_width / 2.0,
            glow_width / 2.0,
        )
        painter.setBrush(core_gradient)
        painter.drawRoundedRect(
            QRectF(
                center_x - core_width / 2.0,
                trail_top,
                core_width,
                trail_height,
            ),
            core_width / 2.0,
            core_width / 2.0,
        )
        painter.end()
        self._note_body_cache[cache_key] = asset
        return asset

    def _draw_impact_burst(
        self,
        painter: QPainter,
        x: float,
        note_width: float,
        color: QColor,
        progress: float,
        intensity: float = 1.0,
        ray_count: int = 11,
        ring_count: int = 1,
        mote_count: int = 4,
        *,
        rainbow: bool = False,
        key_width_scale: float = 1.0,
        effect_size_scale: float = 1.0,
        effect_opacity: float = 1.0,
    ) -> None:
        if not isinstance(painter, QPainter):
            self._draw_impact_burst_direct(
                painter,
                x,
                note_width,
                color,
                progress,
                intensity,
                ray_count,
                ring_count,
                mote_count,
                rainbow=rainbow,
                key_width_scale=key_width_scale,
                effect_size_scale=effect_size_scale,
                effect_opacity=effect_opacity,
            )
            return
        progress = max(0.0, min(1.0, progress))
        progress_bucket = min(
            self.IMPACT_PROGRESS_STEPS - 1,
            round(progress * (self.IMPACT_PROGRESS_STEPS - 1)),
        )
        cache_key = (
            round(note_width, 2),
            color.rgba(),
            progress_bucket,
            round(float(intensity), 3),
            int(ray_count),
            int(ring_count),
            int(mote_count),
            bool(rainbow),
            round(float(key_width_scale), 3),
            round(float(effect_size_scale), 3),
            round(float(effect_opacity), 3),
            round(self._scale, 3),
            self.height(),
        )
        asset = self._impact_cache.get(cache_key)
        margin = max(48.0 * self._scale, note_width * 3.0)
        if asset is None:
            asset_width = max(1, math.ceil(note_width + margin * 2.0))
            asset = QPixmap(asset_width, max(1, self.height()))
            asset.fill(Qt.GlobalColor.transparent)
            asset_painter = QPainter(asset)
            asset_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_impact_burst_direct(
                asset_painter,
                margin,
                note_width,
                color,
                progress_bucket / max(1, self.IMPACT_PROGRESS_STEPS - 1),
                intensity,
                ray_count,
                ring_count,
                mote_count,
                rainbow=rainbow,
                key_width_scale=key_width_scale,
                effect_size_scale=effect_size_scale,
                effect_opacity=effect_opacity,
            )
            asset_painter.end()
            self._impact_cache[cache_key] = asset
        painter.drawPixmap(round(x - margin), 0, asset)

    def _draw_impact_burst_direct(
        self,
        painter: QPainter,
        x: float,
        note_width: float,
        color: QColor,
        progress: float,
        intensity: float = 1.0,
        ray_count: int = 11,
        ring_count: int = 1,
        mote_count: int = 4,
        *,
        rainbow: bool = False,
        key_width_scale: float = 1.0,
        effect_size_scale: float = 1.0,
        effect_opacity: float = 1.0,
    ) -> None:
        progress = max(0.0, min(1.0, progress))
        fade = 1.0 - progress
        spatial_scale = (
            self.IMPACT_SIZE_SCALE
            * max(0.5, min(1.0, float(key_width_scale)))
            * max(0.1, float(effect_size_scale))
        )
        center_x = x + note_width / 2.0
        base_radius = max(
            4.5 * self._scale,
            min(note_width * 0.58, 7.2 * self._scale),
        ) * intensity * spatial_scale
        center_y = self._impact_origin_y()
        center_color = (
            self._rainbow_impact_color(0, 7, progress)
            if rainbow
            else QColor(color)
        )
        painter.save()
        painter.setOpacity(
            painter.opacity()
            * self.IMPACT_OPACITY
            * max(0.0, min(1.0, float(effect_opacity)))
        )
        self._draw_impact_core(
            painter,
            center_x,
            center_y,
            base_radius * (1.0 + progress * 0.45),
            center_color,
            fade,
        )

        for ring_index in range(max(0, ring_count)):
            ring_color = (
                self._rainbow_impact_color(
                    ring_index * 3 + 1,
                    max(7, ring_count * 3),
                    progress,
                ).lighter(120)
                if rainbow
                else QColor(color).lighter(150 + ring_index * 12)
            )
            ring_color.setAlpha(
                round(235 * fade * max(0.45, 1.0 - ring_index * 0.28))
            )
            ring_radius = (
                base_radius
                * (0.72 + progress * 2.1)
                * (1.0 + ring_index * 0.48)
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(
                    ring_color,
                    max(0.9 * self._scale, 1.8 * self._scale * fade),
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawEllipse(
                QPointF(center_x, center_y),
                ring_radius,
                ring_radius * 0.52,
            )

        particle_radius = (
            max(0.75 * self._scale, 1.55 * self._scale * fade)
            * spatial_scale
        )
        ray_count = max(1, int(ray_count))
        angles = tuple(
            270.0
            if ray_count == 1
            else 195.0 + 150.0 * index / (ray_count - 1)
            for index in range(ray_count)
        )
        for index, angle in enumerate(angles):
            ray_color = (
                self._rainbow_impact_color(index, ray_count, progress)
                if rainbow
                else QColor(color).lighter(135)
            )
            ray_color.setAlpha(round(220 * fade))
            particle_color = (
                QColor(ray_color).lighter(145)
                if rainbow
                else QColor(color).lighter(155)
            )
            particle_color.setAlpha(round(235 * fade))
            painter.setPen(
                QPen(
                    ray_color,
                    max(0.8 * self._scale, 1.4 * self._scale * fade),
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            radians = math.radians(angle)
            spread = 0.86 + 0.18 * (index % 3)
            start_distance = (
                base_radius * 0.52
                + 2.5
                * self._scale
                * progress
                * spatial_scale
            )
            end_distance = (
                base_radius
                + (3.0 + 14.0 * progress)
                * self._scale
                * spread
                * spatial_scale
            )
            start = QPointF(
                center_x + math.cos(radians) * start_distance,
                center_y + math.sin(radians) * start_distance,
            )
            end = QPointF(
                center_x + math.cos(radians) * end_distance,
                center_y + math.sin(radians) * end_distance,
            )
            painter.drawLine(start, end)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(particle_color)
            painter.drawEllipse(end, particle_radius, particle_radius)
            painter.setPen(
                QPen(
                    ray_color,
                    max(0.8 * self._scale, 1.4 * self._scale * fade),
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
        mote_angles = (205, 225, 245, 285, 305, 325, 345)
        for mote_index, angle in enumerate(
            mote_angles[:max(0, min(len(mote_angles), mote_count))]
        ):
            radians = math.radians(angle)
            distance = (
                base_radius
                + (8.0 + 20.0 * progress)
                * self._scale
                * spatial_scale
            )
            mote = QPointF(
                center_x + math.cos(radians) * distance,
                center_y + math.sin(radians) * distance,
            )
            mote_color = (
                self._rainbow_impact_color(
                    mote_index + 2,
                    max(7, mote_count),
                    progress,
                ).lighter(130)
                if rainbow
                else QColor(color).lighter(175)
            )
            mote_color.setAlpha(round(205 * fade))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mote_color)
            mote_radius = (
                max(0.8 * self._scale, 1.8 * self._scale * fade)
                * spatial_scale
            )
            painter.drawEllipse(mote, mote_radius, mote_radius)
        painter.restore()

    @staticmethod
    def _rainbow_impact_color(index: int, count: int, progress: float) -> QColor:
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
        return QColor(self._scheduled).lighter(120), 0.72, 5, 0, 2

    def _impact_key_width_scale(
        self,
        note_width: float,
        available_width: float,
    ) -> float:
        white_note_count = sum(
            1
            for note in range(self.NOTE_MIN, self.NOTE_MAX + 1)
            if note % 12 in self.WHITE_PITCH_CLASSES
        )
        white_width = max(1.0, float(available_width)) / white_note_count
        return max(0.5, min(1.0, float(note_width) / white_width))

    def _impact_duration(self, judgment: str) -> float:
        return self.IMPACT_DURATION_SECONDS.get(
            judgment,
            self.IMPACT_DURATION_SECONDS["GOOD"],
        )

    def _impact_origin_y(self) -> float:
        return float(self.height() - 1)

    def _draw_lane_glow(
        self,
        painter: QPainter,
        x: float,
        note_width: float,
        height: float,
        color: QColor,
        opacity: float,
    ) -> None:
        opacity = max(0.0, min(1.0, float(opacity)))
        if opacity <= 0.0:
            return
        edge_color = QColor(color)
        edge_color.setAlpha(round(255 * opacity * 0.28))
        center_color = QColor(color)
        center_color.setAlpha(round(255 * opacity))
        gradient = QLinearGradient(x, 0.0, x + note_width, 0.0)
        gradient.setColorAt(0.0, edge_color)
        gradient.setColorAt(0.5, center_color)
        gradient.setColorAt(1.0, edge_color)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRect(QRectF(x, 0.5, note_width, height))
        painter.restore()

    def _score_text(self) -> str:
        judgment_prefix = (
            f"{self._judgment}   "
            if self._judgment and self._judgment != "MISS"
            else ""
        )
        return (
            f"{judgment_prefix}SCORE {self._score:06d}   "
            f"COMBO {self._combo}   x{self._multiplier_tenths / 10:.1f}"
        )

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(1.0, float(self.width() - 1))
        height = max(1.0, float(self.height() - 1))
        dirty_region = event.region()
        painter.drawPixmap(0, 0, self._ensure_static_layer(width, height))
        now = time.monotonic()

        for impact in self._hit_impacts:
            horizontal = self._note_rect(impact.note, width)
            if horizontal is None:
                continue
            elapsed = max(0.0, now - impact.started_at)
            duration = self._impact_duration(impact.judgment)
            if elapsed > duration:
                continue
            x, note_width = horizontal
            effect_margin = max(48.0 * self._scale, note_width * 3.0)
            if not self._region_intersects_lane(
                dirty_region,
                x,
                note_width,
                height,
                effect_margin,
            ):
                continue
            color, intensity, ray_count, ring_count, mote_count = (
                self._impact_style(impact.judgment)
            )
            effect_size_scale = 1.0
            effect_opacity = (
                self.PERFECT_IMPACT_OPACITY
                if impact.judgment == "PERFECT"
                else 1.0
            )
            if impact.released:
                effect_size_scale = self.RELEASE_IMPACT_SIZE_SCALE
                effect_opacity = (
                    self.PERFECT_RELEASE_IMPACT_OPACITY
                    if impact.judgment == "PERFECT"
                    else self.RELEASE_IMPACT_OPACITY
                )
                ray_count = max(
                    1,
                    round(ray_count * self.RELEASE_IMPACT_PARTICLE_SCALE),
                )
                mote_count = round(
                    mote_count * self.RELEASE_IMPACT_PARTICLE_SCALE
                )
            self._draw_impact_burst(
                painter,
                x,
                note_width,
                color,
                elapsed / duration,
                intensity,
                ray_count,
                ring_count,
                mote_count,
                rainbow=impact.judgment == "PERFECT",
                key_width_scale=self._impact_key_width_scale(
                    note_width,
                    width,
                ),
                effect_size_scale=effect_size_scale,
                effect_opacity=effect_opacity,
            )

        for note in sorted(self._held_lane_counts):
            horizontal = self._note_rect(note, width)
            if horizontal is None:
                continue
            x, note_width = horizontal
            if not self._region_intersects_lane(
                dirty_region,
                x,
                note_width,
                height,
            ):
                continue
            self._draw_lane_glow(
                painter,
                x,
                note_width,
                height,
                QColor(self._live),
                self.HELD_LANE_OPACITY,
            )

        for fade in self._lane_fades:
            horizontal = self._note_rect(fade.note, width)
            if horizontal is None:
                continue
            elapsed = max(0.0, now - fade.started_at)
            if elapsed > self.LANE_FADE_SECONDS:
                continue
            x, note_width = horizontal
            if not self._region_intersects_lane(
                dirty_region,
                x,
                note_width,
                height,
            ):
                continue
            progress = elapsed / self.LANE_FADE_SECONDS
            base_opacity = (
                self.MISSED_LANE_OPACITY
                if fade.missed
                else self.HELD_LANE_OPACITY
            )
            color = (
                QColor(self.MISSED_LANE_COLOR)
                if fade.missed
                else QColor(self._live)
            )
            self._draw_lane_glow(
                painter,
                x,
                note_width,
                height,
                color,
                base_opacity * (1.0 - progress) ** 2,
            )

        if self._grid_layer is not None:
            painter.drawPixmap(0, 0, self._grid_layer)

        if not self._frame_visible_notes and self._sequence_notes:
            self._prepare_animation_frame(now)
        position = self._frame_position
        song_horizon = self.PREVIEW_SECONDS * self._speed_ratio
        for note in self._frame_visible_notes:
            horizontal = self._note_rect(note.note, width)
            if horizontal is None:
                continue
            x, note_width = horizontal
            if not self._region_intersects_lane(
                dirty_region,
                x,
                note_width,
                height,
            ):
                continue
            top = height - ((note.end - position) / song_horizon) * height
            bottom = height - ((note.start - position) / song_horizon) * height
            self._draw_note_span(
                painter,
                x,
                note_width,
                top,
                bottom,
                QColor(self._scheduled),
                show_head=position < note.start,
                now=now,
                phase_seed=note.note + note.start,
            )

        if self._frame_layer is not None:
            painter.drawPixmap(0, 0, self._frame_layer)
        score_layer, score_position = self._ensure_score_layer()
        painter.drawPixmap(score_position, score_layer)
        painter.end()


class ContentPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(0)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        self.layout.addWidget(self.body)

    def apply_scale(self, scale: float) -> None:
        margin = max(1, round(8 * scale))
        self.layout.setContentsMargins(margin, margin, margin, margin)


class PositionSlider(QSlider):
    def _value_at_event(self, event: QMouseEvent) -> int:
        vertical = self.orientation() == Qt.Orientation.Vertical
        position = event.position().y() if vertical else event.position().x()
        span = self.height() if vertical else self.width()
        return QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            round(position),
            max(1, span),
            vertical,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._value_at_event(event))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.setValue(self._value_at_event(event))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._value_at_event(event))
        super().mouseReleaseEvent(event)


class RoundKnob(QDial):
    BASE_SIZE = 46
    START_ANGLE = 135.0
    SWEEP_ANGLE = 270.0
    DRAG_TRAVEL_FOR_FULL_RANGE = 160.0

    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scale = 1.0
        self._surface = QColor("#ffffff")
        self._track = QColor("#e7ecf2")
        self._border = QColor("#c4ccd6")
        self._text = QColor("#172033")
        self._accent = QColor("#2563eb")
        self._accent_hover = QColor("#1d4ed8")
        self._hovered = False
        self._drag_active = False
        self._drag_start_y = 0.0
        self._drag_start_value = value
        self._base_size = self.BASE_SIZE
        self.setRange(minimum, maximum)
        self.setValue(value)
        self.setWrapping(False)
        self.setNotchesVisible(False)
        self.setTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.apply_scale(1.0)

    def apply_scale(self, scale: float, base_size: int | None = None) -> None:
        self._scale = max(0.5, float(scale))
        if base_size is not None:
            self._base_size = max(1, int(base_size))
        diameter = max(1, round(self._base_size * self._scale))
        self.setFixedSize(diameter, diameter)
        self.update()

    def set_colors(
        self,
        surface: str,
        track: str,
        border: str,
        text: str,
        accent: str,
        accent_hover: str,
    ) -> None:
        self._surface = QColor(surface)
        self._track = QColor(track)
        self._border = QColor(border)
        self._text = QColor(text)
        self._accent = QColor(accent)
        self._accent_hover = QColor(accent_hover)
        self.update()

    def sizeHint(self) -> QSize:
        diameter = max(1, round(self._base_size * self._scale))
        return QSize(diameter, diameter)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _ratio(self) -> float:
        value_range = self.maximum() - self.minimum()
        if value_range <= 0:
            return 0.0
        return (self.value() - self.minimum()) / value_range

    def _set_value_from_vertical_drag(self, current_y: float) -> None:
        value_range = self.maximum() - self.minimum()
        if value_range <= 0:
            return
        drag_travel = max(1.0, self.DRAG_TRAVEL_FOR_FULL_RANGE * self._scale)
        upward_distance = self._drag_start_y - current_y
        value_delta = upward_distance * value_range / drag_travel
        self.setValue(round(self._drag_start_value + value_delta))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self._drag_start_y = event.position().y()
            self._drag_start_value = self.value()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_active and event.buttons() & Qt.MouseButton.LeftButton:
            self._set_value_from_vertical_drag(event.position().y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_active:
            self._set_value_from_vertical_drag(event.position().y())
            self._drag_active = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = min(float(self.width()), float(self.height()))
        inset = max(2.0, 2.5 * self._scale)
        dial_rect = QRectF(
            (self.width() - diameter) / 2.0 + inset,
            (self.height() - diameter) / 2.0 + inset,
            diameter - inset * 2.0,
            diameter - inset * 2.0,
        )
        border = self._accent if self.hasFocus() or self._hovered else self._border
        painter.setPen(QPen(border, max(1.0, 1.2 * self._scale)))
        painter.setBrush(self._surface)
        painter.drawEllipse(dial_rect)

        arc_inset = max(4.0, 5.0 * self._scale)
        arc_rect = dial_rect.adjusted(arc_inset, arc_inset, -arc_inset, -arc_inset)
        arc_width = max(2.0, 3.0 * self._scale)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                self._track,
                arc_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(arc_rect, 225 * 16, -round(self.SWEEP_ANGLE * 16))
        accent = self._accent_hover if self._hovered else self._accent
        painter.setPen(
            QPen(
                accent,
                arc_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(
            arc_rect,
            225 * 16,
            -round(self.SWEEP_ANGLE * self._ratio() * 16),
        )

        center = dial_rect.center()
        radius = dial_rect.width() / 2.0
        pointer_angle = math.radians(
            self.START_ANGLE + self.SWEEP_ANGLE * self._ratio()
        )
        pointer_start = QPointF(
            center.x() + math.cos(pointer_angle) * radius * 0.58,
            center.y() + math.sin(pointer_angle) * radius * 0.58,
        )
        pointer_end = QPointF(
            center.x() + math.cos(pointer_angle) * radius * 0.78,
            center.y() + math.sin(pointer_angle) * radius * 0.78,
        )
        painter.setPen(
            QPen(
                accent,
                max(1.5, 1.8 * self._scale),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawLine(pointer_start, pointer_end)

        font = painter.font()
        font.setPixelSize(max(7, round(10 * self._scale)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self._text)
        painter.drawText(dial_rect, Qt.AlignmentFlag.AlignCenter, str(self.value()))
        painter.end()


class KnobValueControl(QWidget):
    valueChanged = Signal(int)
    resetRequested = Signal()

    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int,
        parent: QWidget | None = None,
        *,
        horizontal: bool = False,
        horizontal_knob_size: int = 20,
        horizontal_minimum_width: int = 58,
        caption: bool = True,
    ) -> None:
        super().__init__(parent)
        self._horizontal = horizontal
        self._horizontal_knob_size = max(1, int(horizontal_knob_size))
        self._horizontal_minimum_width = max(
            1,
            int(horizontal_minimum_width),
        )
        layout = QHBoxLayout(self) if horizontal else QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(
            Qt.AlignmentFlag.AlignVCenter
            if horizontal
            else Qt.AlignmentFlag.AlignHCenter
        )
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setProperty("caption", caption)
        self.label.installEventFilter(self)
        self.knob = RoundKnob(minimum, maximum, value)
        layout.addWidget(self.label)
        layout.addWidget(
            self.knob,
            0,
            (
                Qt.AlignmentFlag.AlignVCenter
                if horizontal
                else Qt.AlignmentFlag.AlignHCenter
            ),
        )
        self.knob.valueChanged.connect(self._emit_value)

    def _emit_value(self, value: int) -> None:
        self.valueChanged.emit(value)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if watched is self.label and event.type() == QEvent.Type.MouseButtonDblClick:
            self.resetRequested.emit()
            return True
        return super().eventFilter(watched, event)

    def set_value(self, value: int) -> None:
        self.knob.blockSignals(True)
        self.knob.setValue(value)
        self.knob.blockSignals(False)

    def apply_scale(self, scale: float) -> None:
        spacing = 3 if self._horizontal else 2
        knob_size = (
            self._horizontal_knob_size
            if self._horizontal
            else RoundKnob.BASE_SIZE
        )
        scaled_spacing = max(1, round(spacing * scale))
        self.layout().setSpacing(scaled_spacing)
        self.knob.apply_scale(scale, knob_size)
        if self._horizontal:
            text_width = self.label.fontMetrics().horizontalAdvance(
                self.label.text()
            )
            control_width = max(
                round(self._horizontal_minimum_width * scale),
                text_width + self.knob.width() + scaled_spacing + round(2 * scale),
            )
        else:
            control_width = round(68 * scale)
        self.setFixedWidth(max(1, control_width))

    def set_colors(
        self,
        surface: str,
        track: str,
        border: str,
        text: str,
        accent: str,
        accent_hover: str,
    ) -> None:
        self.knob.set_colors(
            surface,
            track,
            border,
            text,
            accent,
            accent_hover,
        )


class SeekSlider(PositionSlider):
    seekRequested = Signal(int)
    WHALE_FRAME_INTERVAL_MS = 140
    WHALE_FRAME_SEQUENCE = (0, 1, 2, 1)
    WHALE_SPOUT_CYCLE_FRAMES = 28
    WHALE_SPOUT_ACTIVE_FRAMES = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._user_drag_active = False
        self._whale_frames: tuple[QPixmap, ...] = ()
        self._whale_frame_position = 0
        self._whale_animation_tick = 0
        self._whale_handle_size = 0
        self._whale_vertical_offset = 0.0
        self._playback_running = False
        self._whale_timer = QTimer(self)
        self._whale_timer.setInterval(self.WHALE_FRAME_INTERVAL_MS)
        self._whale_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._whale_timer.timeout.connect(self._advance_whale_frame)
        self.setProperty("animatedWhale", True)

    def is_user_drag_active(self) -> bool:
        return self._user_drag_active

    @property
    def whale_frame_count(self) -> int:
        return len(self._whale_frames)

    @property
    def whale_handle_size(self) -> int:
        return self._whale_handle_size

    @property
    def whale_vertical_offset(self) -> float:
        return self._whale_vertical_offset

    @property
    def whale_animation_active(self) -> bool:
        return self._whale_timer.isActive()

    @property
    def whale_spout_active(self) -> bool:
        return (
            self._playback_running
            and bool(self._whale_frames)
            and self._whale_animation_tick % self.WHALE_SPOUT_CYCLE_FRAMES
            < self.WHALE_SPOUT_ACTIVE_FRAMES
        )

    def set_playback_running(self, running: bool) -> None:
        running = bool(running)
        if self._playback_running == running:
            return
        self._playback_running = running
        self._update_whale_timer()
        self.update()

    def set_whale_handle_frames(
        self,
        paths: tuple[str, ...],
        display_size: int,
        vertical_offset: float = 0.0,
    ) -> None:
        frames = tuple(
            pixmap
            for pixmap in (QPixmap(path) for path in paths)
            if not pixmap.isNull()
        )
        self._whale_frames = frames if len(frames) == len(paths) else ()
        self._whale_handle_size = max(1, int(display_size)) if self._whale_frames else 0
        self._whale_vertical_offset = (
            max(0.0, float(vertical_offset)) if self._whale_frames else 0.0
        )
        self._whale_frame_position = 0
        self._whale_animation_tick = 0
        self._update_whale_timer()
        self.update()

    def clear_whale_handle_frames(self) -> None:
        self._whale_frames = ()
        self._whale_handle_size = 0
        self._whale_vertical_offset = 0.0
        self._whale_frame_position = 0
        self._whale_animation_tick = 0
        self._update_whale_timer()
        self.update()

    def _update_whale_timer(self) -> None:
        should_run = (
            self._playback_running
            and bool(self._whale_frames)
            and self.isVisible()
        )
        if should_run and not self._whale_timer.isActive():
            self._whale_timer.start()
        elif not should_run and self._whale_timer.isActive():
            self._whale_timer.stop()

    def _advance_whale_frame(self) -> None:
        if not self._playback_running or not self._whale_frames:
            self._update_whale_timer()
            return
        self._whale_frame_position = (
            self._whale_frame_position + 1
        ) % len(self.WHALE_FRAME_SEQUENCE)
        self._whale_animation_tick = (
            self._whale_animation_tick + 1
        ) % self.WHALE_SPOUT_CYCLE_FRAMES
        self.update()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        self._update_whale_timer()

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._whale_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        if not self._whale_frames or self._whale_handle_size <= 0:
            return
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        sequence_index = self.WHALE_FRAME_SEQUENCE[self._whale_frame_position]
        frame = self._whale_frames[sequence_index % len(self._whale_frames)]
        center_x = handle_rect.x() + handle_rect.width() / 2.0
        center_y = handle_rect.y() + handle_rect.height() / 2.0
        target = QRectF(
            center_x - self._whale_handle_size / 2.0,
            center_y
            - self._whale_handle_size / 2.0
            - self._whale_vertical_offset,
            self._whale_handle_size,
            self._whale_handle_size,
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, frame, QRectF(frame.rect()))
        self._draw_whale_spout(painter, target)
        painter.end()

    def _draw_whale_spout(self, painter: QPainter, target: QRectF) -> None:
        if not self._playback_running:
            return
        phase = self._whale_animation_tick % self.WHALE_SPOUT_CYCLE_FRAMES
        if phase >= self.WHALE_SPOUT_ACTIVE_FRAMES:
            return
        progress = (phase + 1) / (self.WHALE_SPOUT_ACTIVE_FRAMES + 1)
        intensity = math.sin(math.pi * progress)
        origin = QPointF(
            target.left() + target.width() * 0.72,
            target.top() + target.height() * 0.37,
        )
        rise = target.height() * (0.18 + 0.20 * progress)
        spread = target.width() * (0.05 + 0.08 * progress)
        apex = QPointF(origin.x(), origin.y() - rise)
        water = QColor(205, 249, 255, round(235 * intensity))
        highlight = QColor(255, 255, 255, round(245 * intensity))
        stroke = max(0.8, target.width() * 0.045)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                water,
                stroke,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        trunk = QPainterPath(origin)
        trunk.cubicTo(
            QPointF(origin.x(), origin.y() - rise * 0.32),
            QPointF(apex.x(), apex.y() + rise * 0.22),
            apex,
        )
        painter.drawPath(trunk)
        for direction in (-1.0, 1.0):
            branch = QPainterPath(apex)
            branch.cubicTo(
                QPointF(
                    apex.x() + direction * spread * 0.25,
                    apex.y() - rise * 0.08,
                ),
                QPointF(
                    apex.x() + direction * spread * 0.72,
                    apex.y() + rise * 0.04,
                ),
                QPointF(
                    apex.x() + direction * spread,
                    apex.y() + rise * 0.18,
                ),
            )
            painter.drawPath(branch)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(highlight)
        drop_radius = max(0.7, target.width() * 0.035)
        for direction, offset in ((-1.0, 0.95), (1.0, 0.72)):
            painter.drawEllipse(
                QPointF(
                    apex.x() + direction * spread * offset,
                    apex.y() + rise * (0.10 + 0.15 * offset),
                ),
                drop_radius,
                drop_radius,
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._user_drag_active = True
            self.setSliderDown(True)
            self.setValue(self._value_at_event(event))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._user_drag_active and event.buttons() & Qt.MouseButton.LeftButton:
            self.setValue(self._value_at_event(event))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._user_drag_active:
            self.setValue(self._value_at_event(event))
            self.setSliderDown(False)
            self._user_drag_active = False
            self.seekRequested.emit(self.value())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ReadableSpinBox(QSpinBox):
    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().color(self.foregroundRole())
        pen = QPen(color, max(1.0, self.height() / 24), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        center_x = self.width() - max(5, round(self.height() * 0.28))
        half_width = max(2, round(self.height() * 0.10))
        rise = max(1, round(self.height() * 0.06))
        upper_y = round(self.height() * 0.28)
        lower_y = round(self.height() * 0.72)
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(center_x - half_width, upper_y + rise),
                    QPointF(center_x, upper_y - rise),
                    QPointF(center_x + half_width, upper_y + rise),
                ]
            )
        )
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(center_x - half_width, lower_y - rise),
                    QPointF(center_x, lower_y + rise),
                    QPointF(center_x + half_width, lower_y - rise),
                ]
            )
        )


def _draw_text_centered_in_circle(
    painter: QPainter,
    circle: QRectF,
    text: str,
) -> None:
    metrics = QFontMetricsF(painter.font())
    ink_bounds = metrics.tightBoundingRect(text)
    origin = QPointF(
        circle.center().x() - ink_bounds.center().x(),
        circle.center().y() - ink_bounds.center().y(),
    )
    painter.drawText(origin, text)


class TrackChannelButton(QToolButton):
    def __init__(self, source: tuple[int, int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source = source
        self._diameter = 18
        self._enabled_background = QColor("#00a7d6")
        self._enabled_foreground = QColor("#ffffff")
        self._disabled_background = QColor("#dff6fc")
        self._disabled_foreground = QColor("#12323b")
        self.setObjectName("TrackChannelButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_scale(self, scale: float) -> None:
        self._diameter = max(1, round(18 * scale))
        font = self.font()
        font.setPixelSize(max(1, round(9 * scale)))
        self.setFont(font)
        self.update()

    def set_colors(
        self,
        enabled_background: QColor,
        enabled_foreground: QColor,
        disabled_background: QColor,
        disabled_foreground: QColor,
    ) -> None:
        self._enabled_background = QColor(enabled_background)
        self._enabled_foreground = QColor(enabled_foreground)
        self._disabled_background = QColor(disabled_background)
        self._disabled_foreground = QColor(disabled_foreground)
        self.update()

    def _circle_rect(self) -> QRectF:
        diameter = max(1, min(self._diameter, self.width() - 2, self.height() - 2))
        return QRectF(
            (self.width() - diameter) / 2,
            (self.height() - diameter) / 2,
            diameter,
            diameter,
        )

    def hitButton(self, position) -> bool:  # type: ignore[no-untyped-def]
        return self._circle_rect().contains(QPointF(position))

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        enabled = self.isChecked()
        background = QColor(
            self._enabled_background if enabled else self._disabled_background
        )
        foreground = QColor(
            self._enabled_foreground if enabled else self._disabled_foreground
        )
        if self.isDown():
            background = background.darker(118)
        elif self.underMouse():
            background = background.lighter(106)
        border = QColor(self._enabled_background if enabled else self._disabled_foreground)
        if not enabled:
            border.setAlpha(110)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(border, max(1.0, self._diameter / 18)))
        painter.setBrush(background)
        bounds = self._circle_rect().adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawEllipse(bounds)
        painter.setPen(foreground)
        font = self.font()
        metrics = QFontMetricsF(font)
        available = max(1.0, bounds.width() - 3.0)
        text_bounds = metrics.tightBoundingRect(self.text())
        if text_bounds.width() > available or text_bounds.height() > available:
            ratio = min(
                available / max(1.0, text_bounds.width()),
                available / max(1.0, text_bounds.height()),
            )
            font.setPixelSize(max(1, round(font.pixelSize() * ratio)))
        painter.setFont(font)
        _draw_text_centered_in_circle(painter, bounds, self.text())
        painter.end()


class ColumnSeparatorHeaderView(QHeaderView):
    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self._separator_color = QColor("#c4ccd6")

    def set_separator_color(self, color: str | QColor) -> None:
        self._separator_color = QColor(color)
        self.viewport().update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        if self.orientation() != Qt.Orientation.Horizontal or self.count() < 2:
            return

        painter = QPainter(self.viewport())
        painter.setPen(QPen(self._separator_color, 1))
        line_bottom = max(0, self.viewport().height() - 2)
        viewport_offset = 0
        table = self.parentWidget()
        if isinstance(table, QTableWidget):
            viewport_offset = (
                table.viewport().mapTo(table, QPoint(0, 0)).x()
                - self.viewport().mapTo(table, QPoint(0, 0)).x()
            )
        for visual_index in range(self.count() - 1):
            logical_index = self.logicalIndex(visual_index)
            x = (
                self.sectionViewportPosition(logical_index)
                + self.sectionSize(logical_index)
                - 1
                + viewport_offset
            )
            if 0 <= x < self.viewport().width():
                painter.drawLine(x, 0, x, line_bottom)
        painter.end()


class TrackChannelTable(QTableWidget):
    sourceToggled = Signal(int, int)
    ENABLED_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 1, parent)
        self._ui_scale = 1.0
        self.setObjectName("TrackChannelTable")
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionsMovable(False)
        header.setSectionsClickable(False)
        header.setStretchLastSection(False)
        header.hide()
        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setColumnWidth(0, 20)
        self.setFixedWidth(22)
        self._enabled_background = QColor("#00a7d6")
        self._enabled_foreground = QColor("#ffffff")
        self._disabled_background = QColor("#dff6fc")
        self._disabled_foreground = QColor("#12323b")

    def apply_scale(self, scale: float) -> None:
        self._ui_scale = scale
        width = max(1, round(22 * scale))
        self.setFixedWidth(width)
        column_width = max(1, round(20 * scale))
        self.horizontalHeader().setDefaultSectionSize(column_width)
        self.setColumnWidth(0, column_width)
        for row in range(self.rowCount()):
            self.setRowHeight(row, max(1, round(22 * scale)))
            button = self.cellWidget(row, 0)
            if isinstance(button, TrackChannelButton):
                button.set_scale(scale)

    def set_items(self, items: list[TrackChannelItem]) -> None:
        old_sources = [
            self.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(self.rowCount())
            if self.item(row, 0)
        ]
        new_sources = [(item.track, item.channel) for item in items]
        if old_sources != new_sources:
            self.setRowCount(len(items))
        for row, source in enumerate(items):
            cell = self.item(row, 0) or QTableWidgetItem()
            cell.setText(f"{source.track + 1}{source.channel + 1}")
            cell.setData(
                Qt.ItemDataRole.UserRole,
                (source.track, source.channel),
            )
            cell.setData(self.ENABLED_ROLE, source.enabled)
            cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 0, cell)
            button = self.cellWidget(row, 0)
            source_key = (source.track, source.channel)
            if not isinstance(button, TrackChannelButton) or button.source != source_key:
                button = TrackChannelButton(source_key)
                button.clicked.connect(
                    lambda _checked, control=button: self.sourceToggled.emit(
                        *control.source
                    )
                )
                self.setCellWidget(row, 0, button)
            button.setText(cell.text())
            button.setChecked(source.enabled)
            button.set_scale(self._ui_scale)
            button.set_colors(
                self._enabled_background,
                self._enabled_foreground,
                self._disabled_background,
                self._disabled_foreground,
            )
            self.setRowHeight(row, max(1, round(22 * self._ui_scale)))

    def set_colors(
        self,
        enabled_background: str,
        enabled_foreground: str,
        disabled_background: str,
        disabled_foreground: str,
    ) -> None:
        self._enabled_background = QColor(enabled_background)
        self._enabled_foreground = QColor(enabled_foreground)
        self._disabled_background = QColor(disabled_background)
        self._disabled_foreground = QColor(disabled_foreground)
        for row in range(self.rowCount()):
            button = self.cellWidget(row, 0)
            if isinstance(button, TrackChannelButton):
                button.set_colors(
                    self._enabled_background,
                    self._enabled_foreground,
                    self._disabled_background,
                    self._disabled_foreground,
                )
        self.viewport().update()


class ShortcutCaptureEdit(QLineEdit):
    shortcutCaptured = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMaximumWidth(82)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        text = shortcut_from_key_event(event)
        if text:
            self.setText(text)
            self.shortcutCaptured.emit(text)
        event.accept()


def shortcut_from_key_event(event: QKeyEvent) -> str:
    key = event.key()
    modifiers = event.modifiers()
    modifier_keys = {
        Qt.Key.Key_Control,
        Qt.Key.Key_Shift,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
    }
    if key in modifier_keys:
        return ""
    key_name = {
        Qt.Key.Key_Space: "SPACE",
        Qt.Key.Key_Return: "ENTER",
        Qt.Key.Key_Enter: "ENTER",
        Qt.Key.Key_Escape: "ESC",
        Qt.Key.Key_Tab: "TAB",
        Qt.Key.Key_Backspace: "BACKSPACE",
        Qt.Key.Key_Delete: "DELETE",
        Qt.Key.Key_Insert: "INSERT",
        Qt.Key.Key_Home: "HOME",
        Qt.Key.Key_End: "END",
        Qt.Key.Key_PageUp: "PAGEUP",
        Qt.Key.Key_PageDown: "PAGEDOWN",
        Qt.Key.Key_Left: "LEFT",
        Qt.Key.Key_Right: "RIGHT",
        Qt.Key.Key_Up: "UP",
        Qt.Key.Key_Down: "DOWN",
    }.get(key)
    if key_name is None and Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
        key_name = f"F{key - Qt.Key.Key_F1 + 1}"
    if key_name is None:
        text = event.text().upper()
        key_name = text if len(text) == 1 and text.isprintable() else ""
    if not key_name:
        return ""
    parts: list[str] = []
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        parts.append("CTRL")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        parts.append("ALT")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        parts.append("SHIFT")
    parts.append(key_name)
    return "+".join(parts)
