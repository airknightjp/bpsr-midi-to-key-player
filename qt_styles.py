from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFontDatabase


@dataclass(frozen=True)
class ThemePalette:
    canvas: str
    panel: str
    panel_alt: str
    surface: str
    surface_hover: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    disabled: str
    danger: str


THEMES = {
    "light": ThemePalette("#eef1f5", "#f8fafc", "#e7ecf2", "#ffffff", "#f1f5f9", "#c4ccd6", "#172033", "#5d6878", "#2563eb", "#1d4ed8", "#ffffff", "#aab2bd", "#c2414c"),
    "dark": ThemePalette("#15191f", "#1e242c", "#252d37", "#171c22", "#2a333e", "#3d4855", "#f3f6fa", "#aeb8c5", "#38bdf8", "#0ea5e9", "#07141c", "#586270", "#fb7185"),
    "green": ThemePalette("#e8f4ee", "#f5fbf8", "#dceee5", "#ffffff", "#edf8f2", "#a9cbbb", "#173a2b", "#557064", "#12845b", "#0e6f4c", "#ffffff", "#91aa9f", "#c04450"),
    "yellow": ThemePalette("#fff8d8", "#fffdf2", "#f5edc0", "#ffffff", "#fff9df", "#ddcd78", "#342c10", "#746a3b", "#d89b00", "#bd8500", "#241900", "#b4aa75", "#c2414c"),
    "blue": ThemePalette("#e7effb", "#f5f8fe", "#dce7f6", "#ffffff", "#edf4fd", "#b3c6e1", "#162b48", "#5a6c83", "#2874c6", "#1e5fa8", "#ffffff", "#98a9bd", "#c2414c"),
    "sky_blue": ThemePalette("#dff6fc", "#f3fbfe", "#d1f0f8", "#ffffff", "#e8f8fc", "#91cddd", "#12323b", "#50727a", "#00a7d6", "#0093bd", "#ffffff", "#8fafb7", "#d04855"),
    "red": ThemePalette("#fae9eb", "#fff7f8", "#f5dde1", "#ffffff", "#fdf0f2", "#dfb0b7", "#461d24", "#7b5a60", "#d04455", "#b93646", "#ffffff", "#b79da1", "#a82638"),
    "pink": ThemePalette("#f8eaf2", "#fff7fb", "#f2dce9", "#ffffff", "#fcedf6", "#dcb4ca", "#432337", "#775b6b", "#d14d91", "#b93c7c", "#ffffff", "#b69faa", "#b52f46"),
    "orange": ThemePalette("#fff0df", "#fff9f2", "#f7e3cc", "#ffffff", "#fff3e5", "#dfbd96", "#442b13", "#78634d", "#e47718", "#c8620e", "#ffffff", "#b9a38c", "#c2414c"),
}


def register_windows_fonts() -> None:
    if QFontDatabase.families():
        return
    for path in (
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/segoeui.ttf",
    ):
        QFontDatabase.addApplicationFont(path)


def build_stylesheet(
    theme_name: str,
    scale_percent: int = 100,
) -> str:
    palette = THEMES.get(theme_name, THEMES["sky_blue"])
    scale = max(1.0, scale_percent / 100)
    font = round(12 * scale)
    small = round(11 * scale)
    control_height = round(26 * scale)
    radius = min(6, round(4 * scale))
    pad_x = round(8 * scale)
    pad_y = round(4 * scale)
    slider_handle_size = round(14 * scale)
    slider_handle_margin = round(5 * scale)
    slider_handle_radius = round(7 * scale)
    slider_handle_border = max(1, round(2 * scale))
    start_button_edge = max(2, round(2 * scale))
    start_button_height = max(1, round(55 * scale))
    start_button_content_height = max(
        1,
        start_button_height - start_button_edge - 1,
    )
    ocean_rules = ""
    sky_blue_slider_rules = ""
    indicator_size = round(16 * scale)
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    checkmark_path = (resource_root / "assets" / "check_white.svg").as_posix()
    # Keep the radio control as an outlined ring with a center point in every
    # theme.  The popup controls use the same foreground color as their theme.
    radio_indicator_color = "#ffffff" if theme_name == "dark" else palette.text
    radio_button_rules = f"""
        QRadioButton {{ spacing: {round(6 * scale)}px; }}
        QRadioButton::indicator {{
            width: {indicator_size}px;
            height: {indicator_size}px;
            background: transparent;
            border: {max(1, round(2 * scale))}px solid {radio_indicator_color};
            border-radius: {round(indicator_size / 2)}px;
        }}
        QRadioButton::indicator:checked {{
            background: qradialgradient(
                cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
                stop: 0 {radio_indicator_color},
                stop: 0.24 {radio_indicator_color},
                stop: 0.27 transparent,
                stop: 1 transparent
            );
            border-color: {radio_indicator_color};
            image: none;
        }}
        QRadioButton::indicator:disabled {{
            background: transparent;
            border-color: {palette.disabled};
        }}
        QRadioButton::indicator:checked:disabled {{
            background: {palette.disabled};
            border-color: {palette.disabled};
        }}
        """
    checkbox_rules = f"""
    QCheckBox::indicator {{
        width: {indicator_size}px;
        height: {indicator_size}px;
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: {max(2, round(4 * scale))}px;
    }}
    QCheckBox::indicator:hover {{
        background: {palette.surface_hover};
        border-color: {palette.accent};
    }}
    QCheckBox::indicator:checked {{
        background: {palette.accent};
        border: 1px solid {palette.accent_hover};
        image: url("{checkmark_path}");
    }}
    QCheckBox::indicator:checked:hover {{
        background: {palette.accent_hover};
        border-color: {palette.accent_hover};
    }}
    QCheckBox::indicator:disabled {{
        background: {palette.panel_alt};
        border-color: {palette.disabled};
    }}
    QCheckBox::indicator:checked:disabled {{
        background: {palette.disabled};
        border-color: {palette.disabled};
        image: url("{checkmark_path}");
    }}
    QCheckBox[unsupported="true"] {{
        color: {palette.disabled};
    }}
    QCheckBox[unsupported="true"]::indicator {{
        background: {palette.panel_alt};
        border-color: {palette.disabled};
    }}
    QCheckBox[unsupported="true"]::indicator:checked {{
        background: {palette.disabled};
        border-color: {palette.disabled};
        image: url("{checkmark_path}");
    }}
    QCheckBox[unsupported="true"]::indicator:hover {{
        border-color: {palette.disabled};
    }}
    """
    if theme_name == "sky_blue":
        whale_handle_size = round(24 * scale)
        whale_handle_margin = max(1, round((whale_handle_size - round(5 * scale)) / 2))
        ocean_rules = f"""
        QMenuBar {{ background: rgba(246, 253, 255, 238); }}
        QGroupBox[section="true"] {{ background: {palette.canvas}; }}
        QWidget#SettingsPanel {{
            background: rgba(239, 251, 255, 116);
            border-radius: {radius}px;
        }}
        """
        sky_blue_slider_rules = f"""
        QSlider[animatedWhale="true"]::handle:horizontal {{
            width: {whale_handle_size}px;
            height: {whale_handle_size}px;
            margin: -{whale_handle_margin}px 0;
            background: transparent;
            border: none;
        }}
        """
    return f"""
    * {{
        font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
        font-size: {font}px;
        color: {palette.text};
        outline: none;
    }}
    QMainWindow, QDialog, QWidget#AppRoot {{ background: {palette.canvas}; }}
    QWidget#SettingsPanel {{
        background: {palette.panel};
        border-radius: {radius}px;
    }}
    QMenuBar {{ background: {palette.panel}; border-bottom: 1px solid {palette.border}; padding: 1px; }}
    QMenuBar::item {{ padding: {pad_y}px {pad_x}px; background: transparent; }}
    QMenuBar::item:selected, QMenu::item:selected {{ background: {palette.panel_alt}; }}
    QMenu {{ background: {palette.panel}; border: 1px solid {palette.border}; padding: 4px; }}
    QMenu::item {{ padding: {pad_y + 1}px {pad_x * 2}px; border-radius: {radius}px; }}
    QGroupBox[section="true"] {{
        background: {palette.panel};
        border: 1px solid {palette.border};
        border-radius: {radius}px;
        margin-top: {round(8 * scale)}px;
        padding-top: {round(3 * scale)}px;
    }}
    QGroupBox[section="true"]::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: {round(8 * scale)}px;
        padding: 0 {round(3 * scale)}px;
        font-weight: 600;
        color: {palette.text};
        background: {palette.canvas};
        border-radius: {radius}px;
    }}
    QGroupBox[section="true"][titleless="true"] {{
        margin-top: 0;
        padding-top: 0;
    }}
    QFrame[subgroup="true"] {{
        background: transparent;
        border: 1px solid {palette.border};
        border-radius: {radius}px;
    }}
    QFrame[subgroup="true"][frameless="true"] {{
        border: none;
    }}
    QLabel[caption="true"] {{ color: {palette.muted}; font-size: {small}px; }}
    QLabel#UpdateStatusBadge {{
        min-width: {round(28 * scale)}px;
        max-width: {round(28 * scale)}px;
        min-height: {round(28 * scale)}px;
        max-height: {round(28 * scale)}px;
        background: {palette.accent};
        color: {palette.accent_text};
        border: none;
        border-radius: {round(14 * scale)}px;
        font-size: {round(16 * scale)}px;
        font-weight: 700;
    }}
    QLabel#UpdateStatusMessage {{
        font-size: {font}px;
        font-weight: 600;
    }}
    QPushButton, QToolButton {{
        min-height: {control_height}px;
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: {radius}px;
        padding: 0 {pad_x}px;
    }}
    QToolButton#ConversionStartButton {{
        min-height: {start_button_content_height}px;
        max-height: {start_button_content_height}px;
        padding: 0 {max(2, round(4 * scale))}px;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 {palette.surface},
            stop: 1 {palette.panel_alt}
        );
        border: 1px solid {palette.border};
        border-bottom: {start_button_edge}px solid {palette.accent};
        border-radius: {radius}px;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {palette.surface_hover}; border-color: {palette.accent}; }}
    QPushButton:pressed, QToolButton:pressed, QPushButton[active="true"], QToolButton[active="true"] {{
        background: {palette.accent}; color: {palette.accent_text}; border-color: {palette.accent};
    }}
    QPushButton:disabled, QToolButton:disabled {{ color: {palette.disabled}; background: {palette.panel_alt}; }}
    QPushButton#UpdateStatusCloseButton {{
        background: {palette.accent};
        color: {palette.accent_text};
        border-color: {palette.accent};
        font-weight: 600;
    }}
    QPushButton#UpdateStatusCloseButton:hover {{
        background: {palette.accent_hover};
        border-color: {palette.accent_hover};
    }}
    QPushButton#UpdateStatusCloseButton:pressed {{
        background: {palette.accent_hover};
        border-color: {palette.accent_hover};
    }}
    QToolButton#ConversionStartButton:pressed,
    QToolButton#ConversionStartButton[active="true"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 {palette.surface_hover},
            stop: 1 {palette.panel_alt}
        );
        color: {palette.accent};
        border: 1px solid {palette.accent};
        border-bottom: {start_button_edge}px solid {palette.accent_hover};
    }}
    QToolButton#ConversionStartButton:hover,
    QToolButton#ConversionStartButton:focus {{
        background: {palette.surface_hover};
        border: 1px solid {palette.accent};
        border-bottom: {start_button_edge}px solid {palette.accent_hover};
    }}
    QToolButton#ConversionStartButton:pressed {{
        background: {palette.panel_alt};
        border: 1px solid {palette.accent_hover};
        padding-top: {start_button_edge}px;
        padding-bottom: 0;
    }}
    QToolButton#ConversionStartButton:disabled {{
        background: {palette.panel_alt};
        color: {palette.disabled};
        border: 1px solid {palette.disabled};
    }}
    QLineEdit, QComboBox, QSpinBox {{
        min-height: {control_height}px;
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: {radius}px;
        padding: 0 {pad_x}px;
        selection-background-color: {palette.accent};
        selection-color: {palette.accent_text};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {palette.accent}; }}
    QComboBox::drop-down {{ width: {control_height}px; border: none; }}
    QComboBox#AudioQtCombo, QComboBox#AudioBufferCombo {{
        min-height: {round(20 * scale)}px;
        max-height: {round(20 * scale)}px;
        padding: 0 {round(4 * scale)}px;
    }}
    QComboBox#AudioQtCombo::drop-down,
    QComboBox#AudioBufferCombo::drop-down {{
        width: {round(18 * scale)}px;
    }}
    QComboBox QAbstractItemView {{
        background: {palette.surface};
        color: {palette.text};
        border: 1px solid {palette.border};
        selection-background-color: {palette.accent};
        selection-color: {palette.accent_text};
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{ padding: {pad_y}px {pad_x}px; }}
    QComboBox QAbstractItemView::item:hover {{ background: {palette.surface_hover}; color: {palette.text}; }}
    QAbstractItemView {{
        background: {palette.surface};
        color: {palette.text};
        border: 1px solid {palette.border};
        selection-background-color: {palette.accent};
        selection-color: {palette.accent_text};
        outline: none;
    }}
    QAbstractItemView::item {{ padding: {pad_y}px {pad_x}px; }}
    QAbstractItemView::item:hover {{ background: {palette.surface_hover}; color: {palette.text}; }}
    QAbstractItemView::item:selected,
    QAbstractItemView::item:selected:hover {{
        background: {palette.accent};
        color: {palette.accent_text};
    }}
    QSpinBox {{ padding-right: {round(20 * scale)}px; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border;
        width: {round(18 * scale)}px;
        background: {palette.panel_alt};
        border-left: 1px solid {palette.border};
    }}
    QSpinBox::up-button {{ subcontrol-position: top right; border-bottom: 1px solid {palette.border}; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {palette.surface_hover}; }}
    QCheckBox {{ spacing: {round(6 * scale)}px; }}
    QCheckBox[settingsItem="true"] {{ margin-left: {round(6 * scale)}px; }}
    QCheckBox:disabled {{ color: {palette.disabled}; }}
    {checkbox_rules}
    {radio_button_rules}
    QSlider::groove:horizontal {{ height: {round(5 * scale)}px; background: {palette.panel_alt}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {palette.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: {slider_handle_size}px; margin: -{slider_handle_margin}px 0; background: {palette.surface}; border: {slider_handle_border}px solid {palette.accent}; border-radius: {slider_handle_radius}px; }}
    QSlider::groove:vertical {{ width: {round(5 * scale)}px; background: {palette.panel_alt}; border-radius: 2px; }}
    QSlider::sub-page:vertical {{ background: {palette.panel_alt}; }}
    QSlider::add-page:vertical {{ background: {palette.accent}; border-radius: 2px; }}
    QSlider::handle:vertical {{ height: {slider_handle_size}px; margin: 0 -{slider_handle_margin}px; background: {palette.surface}; border: {slider_handle_border}px solid {palette.accent}; border-radius: {slider_handle_radius}px; }}
    QTabWidget::pane {{ background: {palette.surface}; border: 1px solid {palette.border}; top: -1px; }}
    QTabBar::tab {{ background: {palette.panel_alt}; border: 1px solid {palette.border}; padding: {pad_y}px {pad_x}px; }}
    QTabBar::tab:selected {{ background: {palette.surface}; border-bottom-color: {palette.surface}; color: {palette.accent}; font-weight: 600; }}
    QTreeWidget, QTableWidget, QPlainTextEdit {{
        background: {palette.surface};
        alternate-background-color: {palette.surface_hover};
        border: none;
        selection-background-color: {palette.accent};
        selection-color: {palette.accent_text};
    }}
    QHeaderView {{
        background: transparent;
        border: none;
    }}
    QHeaderView::section {{
        background: {palette.panel_alt};
        border: none;
        border-bottom: 1px solid {palette.border};
        padding: {pad_y}px {pad_x}px;
        font-weight: 600;
    }}
    QTableWidget#TrackChannelTable {{
        background: transparent;
        border: none;
        font-size: {small}px;
    }}
    QTableWidget#TrackChannelTable::item {{ background: transparent; border: none; padding: 0; }}
    QToolButton#TrackChannelButton {{
        min-width: 0;
        min-height: 0;
        background: transparent;
        border: none;
        border-radius: 0;
        padding: 0;
        font-size: {max(1, round(9 * scale))}px;
    }}
    QToolButton#TrackChannelButton:hover,
    QToolButton#TrackChannelButton:pressed,
    QToolButton#TrackChannelButton:checked {{
        background: transparent;
        border: none;
    }}
    QToolButton#RefreshButton {{ padding: 0; background: transparent; }}
    QToolButton#RefreshButton:hover {{ background: {palette.surface_hover}; }}
    QToolButton#PlayerTransportButton {{
        padding: 0;
        background: transparent;
        border: none;
        border-radius: {round(12 * scale)}px;
    }}
    QToolButton#PlayerTransportButton:hover,
    QToolButton#PlayerTransportButton:focus {{
        background: {palette.surface_hover};
        border: none;
        border-radius: {round(12 * scale)}px;
    }}
    QToolButton#PlayerTransportButton:pressed {{
        background: {palette.panel_alt};
        border: none;
        border-radius: {round(12 * scale)}px;
    }}
    QToolButton#PlayerTransportButton:disabled {{
        background: transparent;
        border: none;
        border-radius: {round(12 * scale)}px;
    }}
    QScrollBar:vertical {{ background: {palette.panel_alt}; width: {round(10 * scale)}px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {palette.border}; min-height: {round(24 * scale)}px; border-radius: {round(5 * scale)}px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QToolTip {{ background: {palette.text}; color: {palette.surface}; border: none; padding: 4px 6px; }}
    {ocean_rules}
    {sky_blue_slider_rules}
    """
