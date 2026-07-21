from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
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
    QFrame,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_state import TrackChannelItem


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


class ThemedBackground(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ocean_enabled = False

    @property
    def ocean_enabled(self) -> bool:
        return self._ocean_enabled

    def set_ocean_enabled(self, enabled: bool) -> None:
        if self._ocean_enabled != enabled:
            self._ocean_enabled = enabled
            self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        if not self._ocean_enabled:
            return
        painter = QPainter(self)
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


class SectionPanel(QGroupBox):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setProperty("section", True)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(0)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        self.layout.addWidget(self.body)

    def set_title(self, title: str) -> None:
        self.setTitle(title)

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


class VerticalValueSlider(QWidget):
    valueChanged = Signal(int)
    resetRequested = Signal()

    def __init__(self, minimum: int, maximum: int, value: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setProperty("caption", True)
        self.label.installEventFilter(self)
        self.slider = PositionSlider(Qt.Orientation.Vertical)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.setMinimumHeight(126)
        self.slider.setFixedWidth(22)
        self.value_label = QLabel(str(value))
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setMinimumWidth(34)
        layout.addWidget(self.label)
        layout.addWidget(self.slider, 1, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._emit_value)

    def _emit_value(self, value: int) -> None:
        self.value_label.setText(str(value))
        self.valueChanged.emit(value)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if watched is self.label and event.type() == QEvent.Type.MouseButtonDblClick:
            self.resetRequested.emit()
            return True
        return super().eventFilter(watched, event)

    def set_value(self, value: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self.value_label.setText(str(value))

    def apply_scale(self, scale: float) -> None:
        self.layout().setSpacing(max(1, round(4 * scale)))
        self.slider.setMinimumHeight(max(1, round(126 * scale)))
        self.slider.setFixedWidth(max(22, round(22 * scale)))
        self.value_label.setFixedWidth(max(1, round(34 * scale)))
        self.setFixedWidth(max(1, round(34 * scale)))


class DoubleClickLabel(QLabel):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class SeekSlider(PositionSlider):
    seekRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.seekRequested.emit(self.value())


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


class TrackChannelDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[no-untyped-def]
        table = self.parent()
        enabled = bool(index.data(TrackChannelTable.ENABLED_ROLE))
        background = table._enabled_background if enabled else table._disabled_background
        foreground = table._enabled_foreground if enabled else table._disabled_foreground
        painter.save()
        painter.fillRect(option.rect, background)
        painter.setPen(foreground)
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, str(index.data()))
        painter.restore()


class TrackChannelTable(QTableWidget):
    sourceToggled = Signal(int, int)
    ENABLED_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 1, parent)
        self._ui_scale = 1.0
        self.setObjectName("TrackChannelTable")
        self.setHorizontalHeaderLabels(["TC"])
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionsMovable(False)
        header.setSectionsClickable(False)
        header.setStretchLastSection(False)
        header.viewport().installEventFilter(self)
        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setColumnWidth(0, 26)
        self.setFixedWidth(28)
        self._enabled_background = QColor("#00a7d6")
        self._enabled_foreground = QColor("#ffffff")
        self._disabled_background = QColor("#dff6fc")
        self._disabled_foreground = QColor("#12323b")
        self.setItemDelegate(TrackChannelDelegate(self))
        self.cellClicked.connect(self._clicked)

    allEnabledRequested = Signal()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if (
            watched is self.horizontalHeader().viewport()
            and event.type() == QEvent.Type.MouseButtonDblClick
        ):
            self.allEnabledRequested.emit()
            return True
        return super().eventFilter(watched, event)

    def apply_scale(self, scale: float) -> None:
        self._ui_scale = scale
        width = max(1, round(28 * scale))
        self.setFixedWidth(width)
        column_width = max(1, width - round(2 * scale))
        self.horizontalHeader().setDefaultSectionSize(column_width)
        self.setColumnWidth(0, column_width)
        self.horizontalHeader().setFixedHeight(max(1, round(24 * scale)))
        for row in range(self.rowCount()):
            self.setRowHeight(row, max(1, round(20 * scale)))

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
            cell.setData(Qt.ItemDataRole.UserRole, (source.track, source.channel))
            cell.setData(self.ENABLED_ROLE, source.enabled)
            cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 0, cell)
            self._apply_item_colors(cell, source.enabled)
            self.setRowHeight(row, max(1, round(20 * self._ui_scale)))

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
            cell = self.item(row, 0)
            if cell:
                self._apply_item_colors(cell, bool(cell.data(self.ENABLED_ROLE)))
        self.viewport().update()

    def _apply_item_colors(self, cell: QTableWidgetItem, enabled: bool) -> None:
        cell.setBackground(QBrush(self._enabled_background if enabled else self._disabled_background))
        cell.setForeground(QBrush(self._enabled_foreground if enabled else self._disabled_foreground))

    def _clicked(self, row: int, _column: int) -> None:
        cell = self.item(row, 0)
        source = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if source:
            self.sourceToggled.emit(*source)


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
