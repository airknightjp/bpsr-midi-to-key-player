from __future__ import annotations

import math

from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QPoint,
    QPointF,
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
)
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDial,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app_state import TrackChannelItem
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
        self._left_resizable_section = -1
        self._left_resize_origin_x = 0
        self._left_resize_origin_width = 0

    def set_left_resizable_section(self, logical_index: int) -> None:
        self._left_resizable_section = int(logical_index)

    def _is_left_resize_handle(self, x: int) -> bool:
        logical_index = self._left_resizable_section
        if not 0 <= logical_index < self.count():
            return False
        boundary = self.sectionViewportPosition(logical_index)
        return abs(int(x) - boundary) <= 5

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._is_left_resize_handle(round(event.position().x()))
        ):
            self._left_resize_origin_x = round(event.position().x())
            self._left_resize_origin_width = self.sectionSize(
                self._left_resizable_section
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._left_resize_origin_width > 0:
            self.viewport().setCursor(Qt.CursorShape.SplitHCursor)
            delta = round(event.position().x()) - self._left_resize_origin_x
            preceding_visual_index = self.visualIndex(
                self._left_resizable_section
            ) - 1
            preceding_index = self.logicalIndex(preceding_visual_index)
            available_width = self._left_resize_origin_width
            if 0 <= preceding_index < self.count():
                available_width += max(
                    0,
                    self.sectionSize(preceding_index)
                    - self.minimumSectionSize(),
                )
            target_width = max(
                self.minimumSectionSize(),
                min(available_width, self._left_resize_origin_width - delta),
            )
            self.resizeSection(self._left_resizable_section, target_width)
            event.accept()
            return
        if self._is_left_resize_handle(round(event.position().x())):
            self.viewport().setCursor(Qt.CursorShape.SplitHCursor)
            event.accept()
            return
        self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._left_resize_origin_width > 0:
            self._left_resize_origin_width = 0
            if self._is_left_resize_handle(round(event.position().x())):
                self.viewport().setCursor(Qt.CursorShape.SplitHCursor)
            else:
                self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._left_resize_origin_width <= 0:
            self.viewport().unsetCursor()
        super().leaveEvent(event)

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
