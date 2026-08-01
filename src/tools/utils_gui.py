from os import path, makedirs, rename
import os
import shutil
from json import dump, load, JSONDecodeError
import ctypes
import sys
try:
    import winreg  # Windows only
except Exception:
    winreg = None

from qdarkstyle import load_stylesheet
from PyQt5.QtCore import Qt, QObject, QEvent, QRectF
from PyQt5.QtGui import QPainterPath, QRegion
from PyQt5.QtWidgets import QApplication

from tools.frameless_chrome import register_window_surface_effects, sync_translucent_chrome

# Lazy: tools.utils pulls manuf/scapy/networking — only import inside functions that need it.
import constants as _zcut_constants
from constants import *

# Backward compatibility for older packaged constants modules.
_WINDOW_CORNER_RADIUS = int(globals().get('WINDOW_CORNER_RADIUS_PX', 12))


def _experimental_charcoal_ui() -> bool:
    """Charcoal/teal UI (stable and experimental). UPDATE_CHANNEL only affects updater feed / labels."""
    return True


def _main_window_chrome_bg() -> str:
    # Solid behind qdarkstyle so “dead space” is opaque (no desktop bleed-through).
    if _experimental_charcoal_ui():
        return '#141414'
    return '#000000'


def translucent_main_chrome_qss() -> str:
    bg = _main_window_chrome_bg()
    return f"""
QMainWindow {{
    background-color: {bg};
    border-radius: {_WINDOW_CORNER_RADIUS}px;
}}
QWidget#centralwidget {{
    background-color: {bg};
    border-radius: {_WINDOW_CORNER_RADIUS}px;
}}
"""


_EXPERIMENTAL_CHARCOAL_QSS = """
/* After qdarkstyle: no blue. Window chrome stays charcoal (#141414 in translucent_main_chrome_qss);
   selections / list highlights / accents that used grey are pure black. */
QWidget {
    selection-background-color: #000000;
    selection-color: #f2f2f2;
}
QAbstractItemView, QTableView, QTableWidget, QListView, QTreeView {
    selection-background-color: #000000;
    selection-color: #f2f2f2;
    alternate-background-color: #1e2228;
}
/* Do not include QTableView/QTableWidget here — it would paint #000000 over #tableScan item brushes. */
QAbstractItemView::item:selected, QListView::item:selected, QTreeView::item:selected {
    background-color: #000000;
    color: #f2f2f2;
}
QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QComboBox {
    selection-background-color: #000000;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {
    border: 1px solid #3a3a3a;
}
QProgressBar {
    background-color: #141414;
    border: 1px solid #316E69;
    border-radius: 4px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #316E69;
    border-radius: 3px;
}
QProgressBar::chunk:disabled {
    background-color: #264d4a;
    border-radius: 3px;
}
/* Main scan bar: extra specificity + object name so Win style engine does not override chunk color. */
QProgressBar#pgbar {
    background-color: #141414;
    border: 1px solid #316E69;
    border-radius: 4px;
}
QProgressBar#pgbar::chunk {
    background-color: #316E69;
    border-radius: 3px;
}
/* QMenu / QMenuBar: see _context_menu_qss() (charcoal panel, black hover, selection teal). */
/* QTabBar: see _chrome_status_strip_and_tabs_qss() (transparent, matches window chrome). */
QCheckBox::indicator, QRadioButton::indicator {
    image: none;
    width: 14px;
    height: 14px;
    border: 1px solid #5D706E;
    background-color: transparent;
    margin: 0px;
}
QCheckBox::indicator:unchecked, QRadioButton::indicator:unchecked {
    image: none;
    background-color: transparent;
    border: 1px solid #5D706E;
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover,
QCheckBox::indicator:unchecked:hover, QRadioButton::indicator:unchecked:hover {
    image: none;
    border: 1px solid #316E69;
    background-color: transparent;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    image: none;
    background-color: #316E69;
    border: 1px solid #5D706E;
}
QCheckBox:hover, QRadioButton:hover {
    color: #316E69;
}
/* Scroll bars: idle thumb = medium grey; hover = selection teal (same as UI_TABLE_SELECTION_BG). */
QScrollBar:vertical {
    background-color: #141414;
    width: 10px;
    margin: 0;
    border: none;
    border-radius: 4px;
}
QScrollBar:horizontal {
    background-color: #141414;
    height: 10px;
    margin: 0;
    border: none;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #4a4a4a;
    min-height: 24px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background-color: #4a4a4a;
    min-width: 24px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: #316E69;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    height: 0;
    width: 0;
    border: none;
    background: transparent;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background-color: #141414;
}
/* qdarkstyle paints spin arrows blue; SVG triangles (CSS borders render as boxes on some Qt/Windows). */
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiM5YTlhOWEiIGQ9Ik0wIDYgTDQuNSAwIEw5IDYgWiIvPjwvc3ZnPg==);
    border: none;
    width: 9px;
    height: 6px;
    margin: 0 1px 1px 1px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiM5YTlhOWEiIGQ9Ik0wIDAgTDQuNSA2IEw5IDAgWiIvPjwvc3ZnPg==);
    border: none;
    width: 9px;
    height: 6px;
    margin: 1px 1px 0 1px;
}
QSlider::groove:horizontal {
    background-color: #1a1a1a;
}
QSlider::handle:horizontal {
    background-color: #316E69;
    border: 1px solid #5D706E;
}
QSlider::handle:horizontal:hover {
    background-color: #5D706E;
}
/* qdark paints the filled groove segment blue; keep it on the same charcoal as the window. */
QSlider::sub-page:horizontal {
    background-color: #316E69;
    border-radius: 2px;
    height: 4px;
}
QSlider::add-page:horizontal {
    background-color: #1a1a1a;
    border-radius: 2px;
    height: 4px;
}
QToolButton:hover {
    background-color: #000000;
}
QToolButton:pressed {
    background-color: #0d0d0d;
}
QComboBox QAbstractItemView {
    selection-background-color: #5D706E;
    selection-color: #f2f2f2;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #5D706E;
    color: #f2f2f2;
}
QComboBox QAbstractItemView::item:selected:active,
QComboBox QAbstractItemView::item:selected:!active {
    background-color: #5D706E;
    color: #f2f2f2;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #5D706E;
    color: #f2f2f2;
}
QComboBox QAbstractItemView::item:hover:!selected {
    background-color: #5D706E;
    color: #f2f2f2;
}
QListView::item:hover, QListView::item:selected,
QListView::item:selected:active, QListView::item:selected:!active {
    background-color: #5D706E;
    color: #f2f2f2;
}
/* Main device table: row chrome from item BackgroundRole; reset inherited QAbstractItemView selection tint. */
QTableWidget#tableScan {
    background-color: #000000;
    alternate-background-color: #0a0a0a;
    outline: none;
    selection-background-color: transparent;
    selection-color: #f2f2f2;
}
QTableWidget#tableScan::item {
    outline: none;
}
"""


def _main_chrome_action_buttons_qss() -> str:
    """
    Top toolbar + bottom row push buttons: same fill / border / hover / pressed palette as
    frameless_chrome.CustomTitleBar (title strip #2b2b2b, hover #383838, pressed #323232).
    Solid idle state so icon-only QPushButtons repaint :hover reliably (transparent idle did not).
    """
    if _experimental_charcoal_ui():
        bg, bd, bh, bp = '#2b2b2b', '#3d3d3d', '#383838', '#323232'
        tx, th, tp = '#e8eaed', '#d0d0d0', '#9a9a9a'
    else:
        bg, bd, bh, bp = '#2d323c', '#3d4a5c', '#3a3f49', '#353942'
        tx, th, tp = '#e8eaed', '#aeb4bf', '#8b909a'
    _ids = (
        '#btnScanEasy',
        '#btnScanHard',
        '#btnSettings',
        '#btnAbout',
        '#btnKill',
        '#btnLagSwitch',
        '#btnDupe',
        '#btnPercentCut',
    )
    sel = ', '.join(f'QPushButton{i}' for i in _ids)
    out = f"""
{sel} {{
    background-color: {bg};
    color: {tx};
    border: 1px solid {bd};
    border-radius: 4px;
    outline: none;
}}
{sel}:focus {{
    outline: none;
    border: 1px solid {bd};
}}
{sel}:hover {{
    background-color: {bh};
    border: 1px solid {bh};
    color: {th};
}}
{sel}:pressed {{
    background-color: {bp};
    border: 1px solid {bp};
    color: {tp};
}}
{sel}:disabled {{
    background-color: {bg};
    border: 1px solid {bd};
    color: {tp};
}}
/* Lag/Kill/Dupe row: plain QWidget can pick up qdark blue-grey behind child buttons; keep transparent. */
QWidget#flowActionsRow {{
    background: transparent;
    border: none;
}}
"""
    return out


def _chrome_status_strip_and_tabs_qss() -> str:
    """Status row under the table + tab bars: no panel tint; blend into window chrome."""
    dev_count_fg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_BG', '#316E69')
    if _experimental_charcoal_ui():
        mute, hi, hover = '#9a9a9a', '#e8eaed', '#d0d0d0'
    else:
        mute, hi, hover = '#8b909a', '#e8eaed', '#aeb4bf'
    return f"""
QLabel#lblleft {{
    background: transparent;
    border: none;
}}
QLabel#lblcenter, QLabel#lblright {{
    background: transparent;
    border: none;
    color: {mute};
}}
QLabel#lblcenter {{
    color: {hi};
}}
QLabel#lblright {{
    color: {dev_count_fg};
}}
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    border: none;
    padding: 6px 14px;
    color: {mute};
}}
QTabBar::tab:selected {{
    background: transparent;
    color: {hi};
    border-bottom: 2px solid {hi};
    padding-bottom: 4px;
}}
QTabBar::tab:!selected:hover {{
    background: transparent;
    color: {hover};
}}
"""


# IP/MAC/Vendor… header hover — device rows use the same pair so row hover matches column headers.
_TABLE_SCAN_HEADER_SECTION_HOVER_BG = '#0a0a0a'
_TABLE_SCAN_HEADER_SECTION_HOVER_FG = '#e8eaed'


def table_row_hover_chrome() -> tuple[str, str]:
    """Background / foreground for main table row hover (same as QHeaderView::section:hover on #tableScan)."""
    return _TABLE_SCAN_HEADER_SECTION_HOVER_BG, _TABLE_SCAN_HEADER_SECTION_HOVER_FG


def table_row_selection_chrome() -> tuple[str, str]:
    """Background / foreground for selected device row (item brushes; table QSS selection is transparent)."""
    if _experimental_charcoal_ui():
        bg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_BG', '#316E69')
        fg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_FG', '#f2f2f2')
        return bg, fg
    return '#324e7a', '#ffffff'


def _table_scan_header_qss() -> str:
    """IP/MAC/Vendor… header row: no qdark blue panel; same black chrome as #tableScan viewport."""
    hb = _TABLE_SCAN_HEADER_SECTION_HOVER_BG
    hf = _TABLE_SCAN_HEADER_SECTION_HOVER_FG
    return f"""
QTableWidget#tableScan QHeaderView {{
    background-color: #000000;
    border: none;
}}
QTableWidget#tableScan QHeaderView::section {{
    background-color: #000000;
    color: #9a9a9a;
    border: none;
    border-right: 1px solid #141414;
    border-bottom: 1px solid #2a2a2a;
    padding: 6px 4px;
}}
QTableWidget#tableScan QHeaderView::section:hover {{
    background-color: {hb};
    color: {hf};
}}
QTableWidget#tableScan QHeaderView::section:pressed {{
    background-color: #121212;
    color: {hf};
}}
"""


def _table_scan_focus_frame_qss() -> str:
    """Swap qdarkstyle’s blue QAbstractItemView focus border for the admin row grey-green."""
    if not _experimental_charcoal_ui():
        return ''
    edge = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_BG', '#5D706E')
    return f"""
QTableWidget#tableScan {{
    border: 2px solid #000000;
}}
QTableWidget#tableScan:focus {{
    border: 2px solid {edge};
    outline: none;
}}
"""


def _auxiliary_windows_qss() -> str:
    """
    Settings / About / Device / Traffic (QMainWindow#zubcutAuxiliaryWindow) and modal dialogs
    (Lag Switch, Dupe, message boxes): same charcoal buttons / panels as the main window.
    """
    toggle_acc = getattr(_zcut_constants, 'UI_TOGGLE_BORDER_ACCENT', '#316E69')
    sel_bg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_BG', '#316E69')
    admin_bg = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_BG', '#5D706E')
    sel_fg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_FG', '#f2f2f2')
    if _experimental_charcoal_ui():
        bg, bd, bh, bp = '#2b2b2b', '#3d3d3d', '#383838', '#323232'
        tx, th, tp, mute = '#e8eaed', '#d0d0d0', '#9a9a9a', '#9a9a9a'
        panel = '#141414'
        tbl_alt = '#0a0a0a'
        _aux_sel_bg, _aux_sel_fg = '#2b2b2b', '#f2f2f2'
        field_bd = admin_bg
    else:
        bg, bd, bh, bp = '#2d323c', '#3d4a5c', '#3a3f49', '#353942'
        tx, th, tp, mute = '#e8eaed', '#aeb4bf', '#8b909a', '#8b909a'
        panel = '#000000'
        tbl_alt = '#1e2228'
        _aux_sel_bg, _aux_sel_fg = '#324e7a', '#ffffff'
        field_bd = bd
    return f"""
QDialog {{
    background-color: {panel};
    font-weight: normal;
}}
/* Lag/Dupe content shell (must not use QDialog > QWidget — QFrame title bar is a QWidget). */
QDialog QWidget#zubcutDialogBody {{
    background-color: transparent;
}}
/* Settings scroll body — kill qdark blue viewport on short / high-DPI screens. */
QMainWindow#zubcutAuxiliaryWindow QScrollArea#zubcutSettingsScroll {{
    background-color: {panel};
    border: none;
}}
QMainWindow#zubcutAuxiliaryWindow QScrollArea#zubcutSettingsScroll > QWidget > QWidget {{
    background-color: {panel};
}}
QMainWindow#zubcutAuxiliaryWindow QWidget#zubcutSettingsScrollInner,
QMainWindow#zubcutAuxiliaryWindow QWidget#zubcutSettingsFooter {{
    background-color: {panel};
}}
QMainWindow#zubcutAuxiliaryWindow QPushButton,
QDialog QPushButton {{
    font-weight: normal;
    background-color: {bg};
    color: {tx};
    border: 1px solid {bd};
    border-radius: 4px;
    padding: 6px 10px;
    min-height: 22px;
}}
QMainWindow#zubcutAuxiliaryWindow QPushButton:hover,
QDialog QPushButton:hover {{
    font-weight: normal;
    background-color: {bh};
    border: 1px solid {bh};
    color: {th};
}}
QMainWindow#zubcutAuxiliaryWindow QPushButton:pressed,
QDialog QPushButton:pressed {{
    font-weight: normal;
    background-color: {bp};
    border: 1px solid {bp};
    color: {tp};
}}
QMainWindow#zubcutAuxiliaryWindow QPushButton:disabled,
QDialog QPushButton:disabled {{
    font-weight: normal;
    background-color: {bg};
    color: {tp};
    border: 1px solid {bd};
}}
QMainWindow#zubcutAuxiliaryWindow QGroupBox,
QDialog QGroupBox {{
    font-weight: normal;
    color: {admin_bg};
    border: 1px solid {bd};
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 8px;
    background-color: {panel};
}}
QMainWindow#zubcutAuxiliaryWindow QGroupBox::title,
QDialog QGroupBox::title {{
    font-weight: normal;
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
}}
/* Designer nests layouts in plain QWidget; qdark gives them a blue-grey fill — blend into group. */
QMainWindow#zubcutAuxiliaryWindow QGroupBox QWidget,
QDialog QGroupBox QWidget {{
    background-color: transparent;
}}
/* QFormLayout buddy labels + rows: qdark often paints these blue — match group chrome. */
QDialog QGroupBox QLabel,
QDialog QGroupBox QCheckBox {{
    font-weight: normal;
    color: {admin_bg};
    background-color: transparent;
}}
QMainWindow#zubcutAuxiliaryWindow QLabel,
QDialog QLabel {{
    color: {admin_bg};
    background-color: transparent;
}}
QMainWindow#zubcutAuxiliaryWindow QCheckBox,
QDialog QCheckBox {{
    font-weight: normal;
    color: {admin_bg};
    background-color: transparent;
}}
QMainWindow#zubcutAuxiliaryWindow QCheckBox:hover,
QDialog QCheckBox:hover {{
    color: {sel_bg};
    background-color: transparent;
}}
QMainWindow#zubcutAuxiliaryWindow QCheckBox::indicator,
QDialog QCheckBox::indicator {{
    image: none;
    width: 14px;
    height: 14px;
    border: 1px solid {admin_bg};
    background-color: transparent;
    margin: 0px;
}}
QMainWindow#zubcutAuxiliaryWindow QCheckBox::indicator:unchecked,
QDialog QCheckBox::indicator:unchecked {{
    image: none;
    border: 1px solid {admin_bg};
    background-color: transparent;
}}
QMainWindow#zubcutAuxiliaryWindow QCheckBox::indicator:hover,
QDialog QCheckBox::indicator:hover,
QMainWindow#zubcutAuxiliaryWindow QCheckBox::indicator:unchecked:hover,
QDialog QCheckBox::indicator:unchecked:hover {{
    image: none;
    border: 1px solid {sel_bg};
    background-color: transparent;
}}
QMainWindow#zubcutAuxiliaryWindow QCheckBox::indicator:checked,
QDialog QCheckBox::indicator:checked {{
    image: none;
    background-color: {sel_bg};
    border: 1px solid {admin_bg};
}}
QMainWindow#zubcutAuxiliaryWindow QSlider::groove:horizontal,
QDialog QSlider::groove:horizontal {{
    background-color: #1a1a1a;
    height: 4px;
    border-radius: 2px;
}}
QMainWindow#zubcutAuxiliaryWindow QSlider::sub-page:horizontal,
QDialog QSlider::sub-page:horizontal {{
    background-color: {sel_bg};
    border-radius: 2px;
    height: 4px;
}}
QMainWindow#zubcutAuxiliaryWindow QSlider::add-page:horizontal,
QDialog QSlider::add-page:horizontal {{
    background-color: #1a1a1a;
    border-radius: 2px;
    height: 4px;
}}
QMainWindow#zubcutAuxiliaryWindow QKeySequenceEdit,
QDialog QKeySequenceEdit {{
    font-weight: normal;
    background-color: {bg};
    color: {tx};
    border: 1px solid {field_bd};
    border-radius: 3px;
    padding: 4px 6px;
}}
QMainWindow#zubcutAuxiliaryWindow QComboBox,
QMainWindow#zubcutAuxiliaryWindow QSpinBox,
QMainWindow#zubcutAuxiliaryWindow QLineEdit,
QDialog QComboBox,
QDialog QSpinBox,
QDialog QLineEdit {{
    font-weight: normal;
    background-color: {bg};
    color: {tx};
    border: 1px solid {field_bd};
    border-radius: 3px;
    padding: 4px 6px;
}}
QMainWindow#zubcutAuxiliaryWindow QComboBox:focus,
QMainWindow#zubcutAuxiliaryWindow QSpinBox:focus,
QMainWindow#zubcutAuxiliaryWindow QLineEdit:focus,
QDialog QComboBox:focus,
QDialog QSpinBox:focus,
QDialog QLineEdit:focus {{
    border: 1px solid {field_bd};
}}
QMainWindow#zubcutAuxiliaryWindow QSpinBox::up-button,
QMainWindow#zubcutAuxiliaryWindow QSpinBox::down-button,
QDialog QSpinBox::up-button,
QDialog QSpinBox::down-button {{
    background-color: {bg};
    border: 1px solid {field_bd};
    width: 16px;
}}
QMainWindow#zubcutAuxiliaryWindow QSpinBox::up-button:hover,
QMainWindow#zubcutAuxiliaryWindow QSpinBox::down-button:hover,
QDialog QSpinBox::up-button:hover,
QDialog QSpinBox::down-button:hover {{
    background-color: {admin_bg};
}}
QMainWindow#zubcutAuxiliaryWindow QSpinBox::up-arrow,
QMainWindow#zubcutAuxiliaryWindow QDoubleSpinBox::up-arrow,
QDialog QSpinBox::up-arrow,
QDialog QDoubleSpinBox::up-arrow {{
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiM5YTlhOWEiIGQ9Ik0wIDYgTDQuNSAwIEw5IDYgWiIvPjwvc3ZnPg==);
    border: none;
    width: 9px;
    height: 6px;
    margin: 0 1px 1px 1px;
}}
QMainWindow#zubcutAuxiliaryWindow QSpinBox::down-arrow,
QMainWindow#zubcutAuxiliaryWindow QDoubleSpinBox::down-arrow,
QDialog QSpinBox::down-arrow,
QDialog QDoubleSpinBox::down-arrow {{
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiM5YTlhOWEiIGQ9Ik0wIDAgTDQuNSA2IEw5IDAgWiIvPjwvc3ZnPg==);
    border: none;
    width: 9px;
    height: 6px;
    margin: 1px 1px 0 1px;
}}
QMainWindow#zubcutAuxiliaryWindow QComboBox::drop-down,
QDialog QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border: none;
    border-left: 1px solid {field_bd};
}}
QMainWindow#zubcutAuxiliaryWindow QComboBox QAbstractItemView,
QDialog QComboBox QAbstractItemView {{
    border: 1px solid {field_bd};
    background-color: #000000;
    selection-background-color: {admin_bg};
    selection-color: {sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QComboBox QAbstractItemView::item:selected,
QDialog QComboBox QAbstractItemView::item:selected {{
    background-color: {admin_bg};
    color: {sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QComboBox QAbstractItemView::item:selected:active,
QMainWindow#zubcutAuxiliaryWindow QComboBox QAbstractItemView::item:selected:!active,
QDialog QComboBox QAbstractItemView::item:selected:active,
QDialog QComboBox QAbstractItemView::item:selected:!active {{
    background-color: {admin_bg};
    color: {sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QComboBox QAbstractItemView::item:hover,
QDialog QComboBox QAbstractItemView::item:hover {{
    background-color: {admin_bg};
    color: {sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QComboBox QAbstractItemView::item:hover:!selected,
QDialog QComboBox QAbstractItemView::item:hover:!selected {{
    background-color: {admin_bg};
    color: {sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QListView::item:hover,
QMainWindow#zubcutAuxiliaryWindow QListView::item:selected,
QMainWindow#zubcutAuxiliaryWindow QListView::item:selected:active,
QMainWindow#zubcutAuxiliaryWindow QListView::item:selected:!active,
QDialog QListView::item:hover,
QDialog QListView::item:selected,
QDialog QListView::item:selected:active,
QDialog QListView::item:selected:!active {{
    background-color: {admin_bg};
    color: {sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QTableWidget,
QDialog QTableWidget {{
    font-weight: normal;
    background-color: #000000;
    alternate-background-color: {tbl_alt};
    color: {tx};
    gridline-color: #141414;
}}
QMainWindow#zubcutAuxiliaryWindow QTableWidget::item:selected,
QDialog QTableWidget::item:selected {{
    font-weight: normal;
    background-color: {_aux_sel_bg};
    color: {_aux_sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QHeaderView::section,
QDialog QHeaderView::section {{
    font-weight: normal;
    background-color: #000000;
    color: {mute};
    border: none;
    border-bottom: 1px solid #2a2a2a;
    padding: 4px;
}}
/* Logs window: kill qdarkstyle blue-grey list / editor / splitter chrome. */
QMainWindow#zubcutAuxiliaryWindow QSplitter#logsSplitter {{
    background-color: {panel};
    border: none;
}}
QMainWindow#zubcutAuxiliaryWindow QSplitter#logsSplitter::handle {{
    background-color: {bd};
    border: none;
    margin: 2px 0;
    height: 3px;
}}
QMainWindow#zubcutAuxiliaryWindow QSplitter#logsSplitter::handle:hover {{
    background-color: {sel_bg};
}}
QMainWindow#zubcutAuxiliaryWindow QWidget#logsDetailWrap {{
    background-color: transparent;
}}
QMainWindow#zubcutAuxiliaryWindow QListWidget#logsHistoryList {{
    background-color: #000000;
    alternate-background-color: {tbl_alt};
    color: {tx};
    border: 1px solid {bd};
    border-radius: 4px;
    outline: none;
    padding: 2px;
    selection-background-color: {admin_bg};
    selection-color: {sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QListWidget#logsHistoryList::item {{
    padding: 3px 6px;
}}
QMainWindow#zubcutAuxiliaryWindow QListWidget#logsHistoryList::item:hover,
QMainWindow#zubcutAuxiliaryWindow QListWidget#logsHistoryList::item:selected,
QMainWindow#zubcutAuxiliaryWindow QListWidget#logsHistoryList::item:selected:active,
QMainWindow#zubcutAuxiliaryWindow QListWidget#logsHistoryList::item:selected:!active {{
    background-color: {admin_bg};
    color: {sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QPlainTextEdit#logsDetailPane {{
    background-color: #000000;
    color: {tx};
    border: 1px solid {field_bd};
    border-radius: 4px;
    padding: 6px;
    selection-background-color: {admin_bg};
    selection-color: {sel_fg};
}}
QMainWindow#zubcutAuxiliaryWindow QPlainTextEdit#logsDetailPane:focus {{
    border: 1px solid {field_bd};
}}
QMainWindow#zubcutAuxiliaryWindow QLabel#logsDetailHeading {{
    color: {admin_bg};
    background-color: transparent;
}}
QMainWindow#zubcutAuxiliaryWindow QLabel#logsHintLabel,
QMainWindow#zubcutAuxiliaryWindow QLabel#logsDiagHint {{
    color: {mute};
    background-color: transparent;
}}
QMainWindow#zubcutAuxiliaryWindow QFrame#logsDiagPanel {{
    background-color: #1a1a1a;
    border: 1px solid {bd};
    border-radius: 4px;
}}
QMainWindow#zubcutAuxiliaryWindow QLabel#logsDiagHeading {{
    color: {tx};
    background-color: transparent;
    font-weight: 600;
}}
QMainWindow#zubcutAuxiliaryWindow QPushButton#logsDiagQuickBtn {{
    background-color: #2b2b2b;
    color: {tx};
    border: 1px solid {bd};
    border-radius: 4px;
    padding: 6px 12px;
    min-height: 24px;
}}
QMainWindow#zubcutAuxiliaryWindow QPushButton#logsDiagQuickBtn:hover {{
    background-color: #3d3d3d;
    border: 1px solid {sel_bg};
}}
QMainWindow#zubcutAuxiliaryWindow QPushButton#logsDiagQuickBtn:pressed {{
    background-color: {sel_bg};
    color: {sel_fg};
}}
"""


def _lag_dupe_dialog_chrome_qss() -> str:
    """
    Lag Switch / Dupe: solid black client (no translucent bleed), teal grey-green borders
    (UI_TOGGLE_BORDER_ACCENT), stable 1px borders to avoid hover text shift.
    """
    acc = getattr(_zcut_constants, 'UI_TOGGLE_BORDER_ACCENT', '#316E69')
    sel_bg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_BG', '#316E69')
    fill, h_fill, p_fill = '#1a1a1a', '#3d524f', '#354846'
    panel = '#0d0d0d'
    return f"""
QDialog#zubcutLagDupeDialog {{
    background-color: #000000;
    font-weight: normal;
}}
QDialog#zubcutLagDupeDialog QWidget#zubcutDialogBody {{
    background-color: #000000;
}}
/* qdark scroll viewport defaults to blue-grey; force charcoal/black like the rest of this dialog. */
QDialog#zubcutLagDupeDialog QScrollArea,
QDialog#zubcutLagDupeDialog QScrollArea#zubcutAdvLagScroll {{
    background-color: #000000;
    border: none;
}}
QDialog#zubcutLagDupeDialog QScrollArea > QWidget > QWidget {{
    background-color: #000000;
}}
QDialog#zubcutLagDupeDialog QAbstractScrollArea#qt_scrollarea_viewport {{
    background-color: #000000;
    border: none;
}}
QDialog#zubcutLagDupeDialog QWidget#zubcutAdvLagScrollInner {{
    background-color: #000000;
}}
/* qdarkstyle paints QLabel with a blue-grey base; force neutral so intro / rows match this dialog. */
QDialog#zubcutLagDupeDialog QWidget#zubcutAdvLagIntroWrap {{
    background-color: #000000;
}}
QDialog#zubcutLagDupeDialog QLabel {{
    background-color: #000000;
    padding: 1px 0;
    margin: 0;
}}
QDialog#zubcutLagDupeDialog QDialogButtonBox {{
    background-color: #000000;
}}
QDialog#zubcutLagDupeDialog QPushButton {{
    background-color: {fill};
    color: #e8eaed;
    border: 1px solid {acc};
    border-radius: 4px;
    padding: 6px 10px;
    outline: none;
}}
QDialog#zubcutLagDupeDialog QPushButton:hover {{
    background-color: {h_fill};
    border: 1px solid {acc};
    color: #f2f2f2;
}}
QDialog#zubcutLagDupeDialog QPushButton:pressed {{
    background-color: {p_fill};
    border: 1px solid {acc};
    color: #e8eaed;
}}
QDialog#zubcutLagDupeDialog QPushButton:disabled {{
    background-color: {fill};
    border: 1px solid {acc};
    color: #9a9a9a;
}}
QDialog#zubcutLagDupeDialog QGroupBox {{
    background-color: {panel};
    border: 1px solid {acc};
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 8px;
    color: #e8eaed;
}}
QDialog#zubcutLagDupeDialog QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
}}
QDialog#zubcutLagDupeDialog QCheckBox {{
    spacing: 0px;
    padding: 0px;
    margin: 0;
    outline: none;
}}
QDialog#zubcutLagDupeDialog QGroupBox QCheckBox {{
    color: #5D706E;
    background-color: transparent;
}}
QDialog#zubcutLagDupeDialog QGroupBox QCheckBox:hover {{
    color: {sel_bg};
    background-color: transparent;
}}
/* Match main-window experimental checkboxes: muted teal border, not near-white. */
QDialog#zubcutLagDupeDialog QCheckBox::indicator,
QDialog#zubcutLagDupeDialog QGroupBox QCheckBox::indicator {{
    image: none;
    width: 14px;
    height: 14px;
    border: 1px solid #5D706E;
    background-color: transparent;
    margin: 0px;
}}
QDialog#zubcutLagDupeDialog QCheckBox::indicator:unchecked,
QDialog#zubcutLagDupeDialog QGroupBox QCheckBox::indicator:unchecked {{
    image: none;
    border: 1px solid #5D706E;
    background-color: transparent;
}}
QDialog#zubcutLagDupeDialog QCheckBox::indicator:hover,
QDialog#zubcutLagDupeDialog QGroupBox QCheckBox::indicator:hover,
QDialog#zubcutLagDupeDialog QCheckBox::indicator:unchecked:hover,
QDialog#zubcutLagDupeDialog QGroupBox QCheckBox::indicator:unchecked:hover {{
    image: none;
    border: 1px solid {sel_bg};
    background-color: transparent;
}}
QDialog#zubcutLagDupeDialog QCheckBox::indicator:checked,
QDialog#zubcutLagDupeDialog QGroupBox QCheckBox::indicator:checked {{
    image: none;
    background-color: {sel_bg};
    border: 1px solid #5D706E;
}}
/* Advanced lag: row enable vs direction — larger / accent-framed “On”, compact “In/Out”. */
QWidget#zubcutAdvLagDirStrip {{
    background-color: #0a1010;
    border: 1px solid #2a4542;
    border-radius: 5px;
}}
QDialog#zubcutLagDupeDialog QCheckBox#zubcutAdvLagChkOn::indicator {{
    image: none;
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid {acc};
    background-color: #101818;
}}
QDialog#zubcutLagDupeDialog QCheckBox#zubcutAdvLagChkOn::indicator:unchecked {{
    background-color: transparent;
}}
QDialog#zubcutLagDupeDialog QCheckBox#zubcutAdvLagChkOn::indicator:checked {{
    background-color: {sel_bg};
    border: 1px solid {acc};
}}
QDialog#zubcutLagDupeDialog QCheckBox#zubcutAdvLagChkOn::indicator:hover,
QDialog#zubcutLagDupeDialog QCheckBox#zubcutAdvLagChkOn::indicator:unchecked:hover {{
    border: 1px solid {sel_bg};
}}
QDialog#zubcutLagDupeDialog QCheckBox#zubcutAdvLagChkDir::indicator {{
    image: none;
    width: 13px;
    height: 13px;
    border-radius: 2px;
    border: 1px solid #5D706E;
    background-color: transparent;
}}
QDialog#zubcutLagDupeDialog QCheckBox#zubcutAdvLagChkDir::indicator:checked {{
    background-color: {sel_bg};
    border: 1px solid #5D706E;
}}
QDialog#zubcutLagDupeDialog QCheckBox#zubcutAdvLagChkDir::indicator:hover,
QDialog#zubcutLagDupeDialog QCheckBox#zubcutAdvLagChkDir::indicator:unchecked:hover {{
    border: 1px solid {sel_bg};
}}
QDialog#zubcutLagDupeDialog QSpinBox,
QDialog#zubcutLagDupeDialog QDoubleSpinBox,
QDialog#zubcutLagDupeDialog QKeySequenceEdit {{
    background-color: {fill};
    color: #e8eaed;
    border: 1px solid {acc};
    border-radius: 3px;
    padding: 4px 6px;
    outline: none;
}}
QDialog#zubcutLagDupeDialog QSpinBox:focus,
QDialog#zubcutLagDupeDialog QDoubleSpinBox:focus,
QDialog#zubcutLagDupeDialog QKeySequenceEdit:focus {{
    border: 1px solid {acc};
}}
QDialog#zubcutLagDupeDialog QSpinBox::up-button,
QDialog#zubcutLagDupeDialog QSpinBox::down-button,
QDialog#zubcutLagDupeDialog QDoubleSpinBox::up-button,
QDialog#zubcutLagDupeDialog QDoubleSpinBox::down-button {{
    background-color: {fill};
    border: 1px solid {acc};
    width: 16px;
}}
QDialog#zubcutLagDupeDialog QSpinBox::up-button:hover,
QDialog#zubcutLagDupeDialog QSpinBox::down-button:hover,
QDialog#zubcutLagDupeDialog QDoubleSpinBox::up-button:hover,
QDialog#zubcutLagDupeDialog QDoubleSpinBox::down-button:hover {{
    background-color: {h_fill};
}}
QDialog#zubcutLagDupeDialog QSpinBox::up-arrow,
QDialog#zubcutLagDupeDialog QDoubleSpinBox::up-arrow {{
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiNhZWI0YmYiIGQ9Ik0wIDYgTDQuNSAwIEw5IDYgWiIvPjwvc3ZnPg==);
    border: none;
    width: 9px;
    height: 6px;
    margin: 0 1px 1px 1px;
}}
QDialog#zubcutLagDupeDialog QSpinBox::down-arrow,
QDialog#zubcutLagDupeDialog QDoubleSpinBox::down-arrow {{
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiNhZWI0YmYiIGQ9Ik0wIDAgTDQuNSA2IEw5IDAgWiIvPjwvc3ZnPg==);
    border: none;
    width: 9px;
    height: 6px;
    margin: 1px 1px 0 1px;
}}
QDialog#zubcutLagDupeDialog QSlider::groove:horizontal {{
    background-color: #1a1a1a;
    height: 4px;
    border-radius: 2px;
}}
QDialog#zubcutLagDupeDialog QSlider::sub-page:horizontal {{
    background-color: #000000;
    border-radius: 2px;
    height: 4px;
}}
QDialog#zubcutLagDupeDialog QSlider::add-page:horizontal {{
    background-color: #1a1a1a;
    border-radius: 2px;
    height: 4px;
}}
QDialog#zubcutLagDupeDialog QSlider::handle:horizontal {{
    background-color: #000000;
    border: 1px solid {acc};
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QDialog#zubcutLagDupeDialog QSlider::handle:horizontal:hover {{
    background-color: {h_fill};
    border: 1px solid {acc};
}}
QDialog#zubcutLagDupeDialog QPushButton#zubcutMitmToggle {{
    min-width: 52px;
    max-width: 72px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: bold;
    border-radius: 14px;
}}
QDialog#zubcutLagDupeDialog QPushButton#zubcutMitmToggle:checked {{
    background-color: {h_fill};
    color: #e8fffa;
    border: 1px solid {acc};
}}
QDialog#zubcutLagDupeDialog QPushButton#zubcutMitmToggle:!checked {{
    background-color: #222222;
    color: #8a8a8a;
    border: 1px solid #3a3a3a;
}}
QDialog#zubcutLagDupeDialog QPushButton#zubcutMitmToggle:hover {{
    border: 1px solid {acc};
}}
QDialog#zubcutLagDupeDialog QPushButton#zubcutMitmToggle:disabled {{
    color: #5a5a5a;
    border: 1px solid #333333;
}}
"""


def _installer_download_dialog_qss() -> str:
    """Frameless installer download dialog: dark body + progress chunk (no native white caption)."""
    acc = getattr(_zcut_constants, 'UI_TOGGLE_BORDER_ACCENT', '#316E69')
    return f"""
QDialog#zubcutInstallerDownloadDialog {{
    background-color: #000000;
}}
QDialog#zubcutInstallerDownloadDialog QWidget#zubcutDialogBody {{
    background-color: #141414;
}}
QDialog#zubcutInstallerDownloadDialog QWidget#zubcutDialogBody QLabel {{
    color: #e8eaed;
}}
QDialog#zubcutInstallerDownloadDialog QWidget#zubcutDialogBody QProgressBar {{
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    background-color: #2b2b2b;
    text-align: center;
    color: #e8eaed;
    min-height: 18px;
}}
QDialog#zubcutInstallerDownloadDialog QWidget#zubcutDialogBody QProgressBar::chunk {{
    background-color: {acc};
    border-radius: 3px;
}}
QDialog#zubcutInstallerDownloadDialog QWidget#zubcutDialogBody QPushButton {{
    background-color: #2b2b2b;
    color: #e8eaed;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 6px 14px;
}}
QDialog#zubcutInstallerDownloadDialog QWidget#zubcutDialogBody QPushButton:hover {{
    background-color: #383838;
    border: 1px solid #383838;
}}
"""


def _context_menu_qss() -> str:
    """
    Right-click / tray menus: kill qdarkstyle blue panel (#37414F) and blue highlight (#1A72BB).

    Hover stays pure black; accents use row-selection teal; item text uses Me/Router sage.
    Also overrides qdark checkbox/radio indicator images (those keep a blue tint on Windows).
    """
    sel_bg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_BG', '#316E69')
    me_fg = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_BG', '#5D706E')
    me_hi = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_FG', '#eef1f0')
    return f"""
QMenu {{
    background-color: #141414;
    color: {me_fg};
    border: 1px solid {sel_bg};
    padding: 4px;
    margin: 0px;
    selection-background-color: #000000;
    selection-color: {me_fg};
}}
QMenu::item {{
    background-color: #141414;
    color: {me_fg};
    padding: 5px 24px 5px 12px;
    border: 1px solid transparent;
}}
QMenu::item:selected,
QMenuBar::item:selected {{
    background-color: #000000;
    color: {me_fg};
}}
QMenu::item:pressed,
QMenuBar::item:pressed {{
    background-color: {sel_bg};
    color: {me_hi};
}}
QMenu::item:disabled {{
    color: #6a6a6a;
    background-color: #141414;
}}
QMenu::separator {{
    height: 1px;
    margin: 4px 8px;
    background-color: {sel_bg};
}}
QMenu::icon {{
    padding-left: 8px;
}}
QMenu::indicator {{
    width: 12px;
    height: 12px;
    margin-left: 6px;
    border: 1px solid {me_fg};
    background-color: transparent;
    image: none;
}}
QMenu::indicator:non-exclusive:unchecked,
QMenu::indicator:exclusive:unchecked {{
    image: none;
    background-color: transparent;
    border: 1px solid {me_fg};
}}
QMenu::indicator:non-exclusive:unchecked:selected,
QMenu::indicator:exclusive:unchecked:selected,
QMenu::indicator:non-exclusive:unchecked:hover,
QMenu::indicator:exclusive:unchecked:hover {{
    image: none;
    border: 1px solid {sel_bg};
    background-color: transparent;
}}
QMenu::indicator:non-exclusive:checked,
QMenu::indicator:exclusive:checked {{
    image: none;
    background-color: {sel_bg};
    border: 1px solid {me_fg};
}}
QMenu::indicator:non-exclusive:checked:selected,
QMenu::indicator:exclusive:checked:selected,
QMenu::indicator:non-exclusive:checked:hover,
QMenu::indicator:exclusive:checked:hover {{
    image: none;
    background-color: {sel_bg};
    border: 1px solid {me_hi};
}}
QMenuBar {{
    background-color: #141414;
    color: {me_fg};
    border: none;
    selection-background-color: #000000;
}}
QMenuBar::item {{
    background: transparent;
    color: {me_fg};
    padding: 4px 8px;
}}
"""


def theme_popup_menu(menu) -> None:
    """
    Apply charcoal/teal QSS + palette on a QMenu instance.

    Windows popup menus often ignore app-global stylesheets; setting the sheet on
    the menu itself is required for right-click / tray menus to leave qdark blue.
    """
    if menu is None:
        return
    try:
        from PyQt5.QtGui import QColor, QPalette
    except Exception:
        return
    sheet = _context_menu_qss()
    try:
        menu.setStyleSheet(sheet)
    except Exception:
        pass
    sel_bg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_BG', '#316E69')
    me_fg = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_BG', '#5D706E')
    try:
        pal = menu.palette()
        panel = QColor('#141414')
        text = QColor(me_fg)
        black = QColor('#000000')
        accent = QColor(sel_bg)
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            pal.setColor(group, QPalette.Window, panel)
            pal.setColor(group, QPalette.Base, panel)
            pal.setColor(group, QPalette.Button, panel)
            pal.setColor(group, QPalette.Text, text)
            pal.setColor(group, QPalette.WindowText, text)
            pal.setColor(group, QPalette.ButtonText, text)
            pal.setColor(group, QPalette.Highlight, black)
            pal.setColor(group, QPalette.HighlightedText, text)
            pal.setColor(group, QPalette.Light, accent)
            pal.setColor(group, QPalette.Mid, accent)
        menu.setPalette(pal)
        menu.setAutoFillBackground(True)
    except Exception:
        pass


def zubcut_dark_stylesheet():
    base = load_stylesheet() + '\n' + translucent_main_chrome_qss()
    if _experimental_charcoal_ui():
        base = base + '\n' + _EXPERIMENTAL_CHARCOAL_QSS
    base = base + '\n' + _main_chrome_action_buttons_qss()
    base = base + '\n' + _chrome_status_strip_and_tabs_qss()
    base = base + '\n' + _table_scan_header_qss()
    base = base + '\n' + _table_scan_focus_frame_qss()
    base = base + '\n' + _auxiliary_windows_qss()
    base = base + '\n' + _lag_dupe_dialog_chrome_qss()
    base = base + '\n' + _installer_download_dialog_qss()
    # After charcoal/qdark so menu rules win over leftover blue highlights.
    base = base + '\n' + _context_menu_qss()
    return base


def apply_app_global_dark_stylesheet():
    """
    Install the unified theme on QApplication (not only the main window).

    On Windows, a stylesheet set only on QMainWindow often fails to repaint
    QPushButton :hover for descendants; applying it here fixes toolbar / bottom-row hovers.
    """
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(zubcut_dark_stylesheet())


def application_theme_stylesheet():
    app = QApplication.instance()
    return app.styleSheet() if app else ''


from tools.frameless_chrome import register_window_surface_effects, sync_translucent_chrome



def is_admin():
    """
    Check if current user is Admin
    """
    if sys.platform.startswith('win'):
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    # On macOS/Linux, assume current user context (no UAC)
    return True


def _elevate_skip_requested() -> bool:
    v = os.environ.get('ZUBCUT_SKIP_ELEVATE', '').strip().lower()
    return v in ('1', 'true', 'yes', 'on')


def spawn_windows_elevated(exe: str, params: str = '', cwd: str | None = None) -> bool:
    """
    Start ``exe`` with UAC elevation (``runas``). Used for startup and Settings/Clumsy restart.
  """
    if not sys.platform.startswith('win'):
        return False
    work_dir = cwd if cwd is not None else ''
    ret = ctypes.windll.shell32.ShellExecuteW(
        None,
        'runas',
        exe,
        params or '',
        work_dir,
        1,  # SW_SHOWNORMAL
    )
    return int(ret) > 32


def _windows_relaunch_command() -> tuple[str, str, str]:
    """(exe, params, cwd) for relaunching this ZubCut process elevated."""
    from subprocess import list2cmdline

    exe = sys.executable
    if getattr(sys, 'frozen', False):
        cwd = os.path.dirname(os.path.abspath(exe))
        params = list2cmdline(sys.argv[1:]) if len(sys.argv) > 1 else ''
    else:
        cwd = os.getcwd()
        params = list2cmdline(sys.argv[1:])
    return exe, params, cwd


def ensure_windows_elevated() -> bool:
    """
    On Windows, re-launch this process with UAC elevation when not already Admin.
    Returns True if the current process may continue (already elevated or non-Windows).
    Returns False if elevation was declined or failed.
    """
    if not sys.platform.startswith('win'):
        return True
    if _elevate_skip_requested() or is_admin():
        return True

    exe, params, cwd = _windows_relaunch_command()
    if not spawn_windows_elevated(exe, params, cwd):
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f'{APP_DISPLAY_NAME} must run as Administrator for network tools and Clumsy mode.\n\n'
                'Click Yes on the UAC prompt, or right-click the app and choose Run as administrator.',
                f'{APP_DISPLAY_NAME} — Administrator required',
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
        return False
    sys.exit(0)


def restart_zubcut(main_window=None) -> bool:
    """
    Start a new elevated ZubCut process and quit this one.

    Settings Clumsy-mode toggle and similar flows must relaunch with ``runas`` so the new
    instance is Administrator (WinDivert / ICS). A plain ``Popen`` from an elevated parent
    does not always inherit the admin token on Windows.
    """
    if not sys.platform.startswith('win'):
        import subprocess

        exe, _params, cwd = _windows_relaunch_command()
        try:
            subprocess.Popen([exe, *sys.argv[1:]], cwd=cwd, close_fds=True)
        except Exception as e:
            print(f'restart_zubcut: failed to spawn process: {e}')
            return False
    else:
        exe, params, cwd = _windows_relaunch_command()
        if not spawn_windows_elevated(exe, params, cwd):
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f'{APP_DISPLAY_NAME} could not restart as Administrator.\n\n'
                    'Approve the UAC prompt, or close ZubCut and open it again with Run as administrator.',
                    f'{APP_DISPLAY_NAME} — restart failed',
                    0x10,
                )
            except Exception:
                pass
            return False

    app = None
    try:
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
    except Exception:
        pass
    if main_window is not None and hasattr(main_window, 'quit_all'):
        main_window.quit_all()
    elif app is not None:
        app.quit()
    return True

def npcap_exists():
    """
    Check for Npcap driver (Windows only)
    """
    if sys.platform.startswith('win'):
        return path.exists(NPCAP_PATH)
    # macOS/Linux uses libpcap (bundled); always True
    return True

_SINGLE_INSTANCE_MUTEX = None


def duplicate_zubcut():
    """
    Return True when another ZubCut instance already holds the single-instance lock.

    Windows: named mutex. Non-Windows: advisory lock file under DOCUMENTS_PATH.
    """
    global _SINGLE_INSTANCE_MUTEX
    if sys.platform.startswith('win'):
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            ERROR_ALREADY_EXISTS = 183
            name = f'Global\\{APP_BUNDLE_NAME}SingleInstance'
            handle = kernel32.CreateMutexW(None, False, name)
            if not handle:
                return False
            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(handle)
                return True
            _SINGLE_INSTANCE_MUTEX = handle
            return False
        except Exception:
            return False
    try:
        lock_path = path.join(DOCUMENTS_PATH, f'{APP_BUNDLE_NAME.lower()}.single.lock')
        makedirs(DOCUMENTS_PATH, exist_ok=True)
        fp = open(lock_path, 'a+', encoding='utf-8')
        try:
            import fcntl

            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fp.close()
            return True
        except Exception:
            fp.close()
            return False
        _SINGLE_INSTANCE_MUTEX = fp
        return False
    except Exception:
        return False

def check_documents_dir():
    """
    Check if documents folder exists in order to store settings
    """
    makedirs(DOCUMENTS_PATH, exist_ok=True)
    if not path.exists(SETTINGS_PATH):
        export_settings()

def import_settings():
    """
    Get stored settings
    """
    check_documents_dir()
    return load(open(SETTINGS_PATH, encoding='utf-8'))


def import_settings_as_dict() -> dict:
    """Normalize on-disk settings to a dict (legacy list/array formats included)."""
    from constants import SETTINGS_KEYS, SETTINGS_VALS

    check_documents_dir()
    try:
        raw = load(open(SETTINGS_PATH, encoding='utf-8'))
    except (JSONDecodeError, OSError):
        raw = None
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, list) and raw:
        n = min(len(SETTINGS_KEYS), len(raw))
        return dict(zip(SETTINGS_KEYS[:n], raw[:n]))
    return dict(zip(SETTINGS_KEYS, SETTINGS_VALS))


def export_settings(values=None):
    """
    Store current settings (or create new)
    """
    keys = SETTINGS_KEYS
    values = values if values else SETTINGS_VALS
    payload = dict(zip(keys, values))
    with open(SETTINGS_PATH, 'w', encoding='utf-8') as fp:
        dump(payload, fp)
        fp.flush()
        try:
            import os

            os.fsync(fp.fileno())
        except OSError:
            pass

def set_settings(key, value):
    """
    Update certain setting item
    """
    defaults = dict(zip(SETTINGS_KEYS, SETTINGS_VALS))
    try:
        s = import_settings()
    except (JSONDecodeError, OSError):
        s = {}
    merged = {**defaults, **{k: s[k] for k in SETTINGS_KEYS if k in s}}
    merged[key] = value
    export_settings([merged[k] for k in SETTINGS_KEYS])


def set_settings_many(updates: dict) -> None:
    """Apply multiple keys with one settings read and one write (avoids UI stalls)."""
    if not updates:
        return
    defaults = dict(zip(SETTINGS_KEYS, SETTINGS_VALS))
    try:
        s = import_settings()
    except (JSONDecodeError, OSError):
        s = {}
    merged = {**defaults, **{k: s[k] for k in SETTINGS_KEYS if k in s}}
    merged.update(updates)
    export_settings([merged[k] for k in SETTINGS_KEYS])

def _setting_key_fallback(key: str):
    """Defaults for keys missing from an older build's SETTINGS_KEYS (no crash)."""
    if key.endswith('_timer_on') or key.endswith('_on'):
        return False
    if key.endswith('_timer_lag_ms') or key.endswith('_timer_pause_ms'):
        return 1000
    if key.endswith('_timer_repeat_forever'):
        return True
    if key.endswith('_timer_runs'):
        return -1
    if key.endswith('_ms') or key.endswith('_pct'):
        return 0
    if 'mbps' in key:
        return 0.0
    if key.endswith('_in') or key.endswith('_out'):
        return True
    return False


def get_settings(key, default=None):
    """
    Get certain setting item by key.

    Values missing from the on-disk JSON are filled from SETTINGS_VALS so new keys
    never raise KeyError (Advanced Lag / MITM scheduler reads many keys on each tick).
    """
    defaults = dict(zip(SETTINGS_KEYS, SETTINGS_VALS))
    try:
        check_documents_dir()
        with open(SETTINGS_PATH, encoding='utf-8') as fp:
            raw = load(fp)
        if not isinstance(raw, dict):
            raw = {}
    except (JSONDecodeError, OSError):
        raw = {}
    merged = {**defaults, **{k: raw[k] for k in SETTINGS_KEYS if k in raw}}
    if key in merged:
        return merged[key]
    if key in defaults:
        return defaults[key]
    if default is not None:
        return default
    return _setting_key_fallback(key)

def repair_settings(repair_iface: bool = True):
    """
    Merge defaults when settings are missing keys or JSON is invalid.
    """
    original = dict(zip(SETTINGS_KEYS, SETTINGS_VALS))
    try:
        s = import_settings_as_dict()
        for key in SETTINGS_KEYS:
            if key in s:
                original[key] = s[key]
        # MITM caps were stored as Kbps; migrate to Mbps if present in old JSON.
        if 'mitm_cap_up_mbps' not in s and 'mitm_cap_up_kbps' in s:
            try:
                original['mitm_cap_up_mbps'] = float(s['mitm_cap_up_kbps']) / 1000.0
            except (TypeError, ValueError):
                pass
        if 'mitm_cap_down_mbps' not in s and 'mitm_cap_down_kbps' in s:
            try:
                original['mitm_cap_down_mbps'] = float(s['mitm_cap_down_kbps']) / 1000.0
            except (TypeError, ValueError):
                pass
        # Clumsy-style Advanced Lag keys: derive from legacy mitm_* when missing from JSON.
        if 'mitm_adv_delay_on' not in s:
            try:
                ena = bool(s.get('mitm_delay_enabled', False))
                up = int(s.get('mitm_delay_up_ms') or 0)
                down = int(s.get('mitm_delay_down_ms') or 0)
                original['mitm_adv_delay_on'] = bool(ena and (up > 0 or down > 0))
                original['mitm_adv_delay_out'] = up > 0
                original['mitm_adv_delay_in'] = down > 0
                original['mitm_adv_delay_ms'] = max(up, down)
            except (TypeError, ValueError):
                pass
        if 'mitm_adv_jitter_on' not in s:
            original['mitm_adv_jitter_on'] = False
            original['mitm_adv_jitter_in'] = True
            original['mitm_adv_jitter_out'] = True
            original['mitm_adv_jitter_ms'] = 0
        if 'mitm_adv_cap_on' not in s:
            try:
                ce = bool(s.get('mitm_cap_enabled', False))
                cu = float(s.get('mitm_cap_up_mbps') or 0.0)
                cd = float(s.get('mitm_cap_down_mbps') or 0.0)
                original['mitm_adv_cap_on'] = bool(ce and (cu > 0.0 or cd > 0.0))
                original['mitm_adv_cap_out'] = cu > 0.0
                original['mitm_adv_cap_in'] = cd > 0.0
                original['mitm_adv_cap_out_mbps'] = cu
                original['mitm_adv_cap_in_mbps'] = cd
            except (TypeError, ValueError):
                pass
        if 'mitm_adv_loss_on' not in s:
            original['mitm_adv_loss_on'] = False
            original['mitm_adv_loss_in'] = True
            original['mitm_adv_loss_out'] = True
            original['mitm_adv_loss_pct'] = 0
        for _pre in ('mitm_adv_delay', 'mitm_adv_jitter', 'mitm_adv_cap', 'mitm_adv_loss'):
            if f'{_pre}_timer_on' not in s:
                original[f'{_pre}_timer_on'] = False
            if f'{_pre}_timer_lag_ms' not in s:
                original[f'{_pre}_timer_lag_ms'] = 1000
            if f'{_pre}_timer_pause_ms' not in s:
                original[f'{_pre}_timer_pause_ms'] = 1000
            if f'{_pre}_timer_repeat_forever' not in s:
                original[f'{_pre}_timer_repeat_forever'] = True
            if f'{_pre}_timer_runs' not in s:
                original[f'{_pre}_timer_runs'] = -1
        # Advanced Lag timer: old "repeat forever" meant infinite lag+pause; runs=-1 encodes that now.
        if not s.get('mitm_adv_timer_schema_v2'):
            original['mitm_adv_timer_schema_v2'] = True
            for _pre in (
                'mitm_adv_delay',
                'mitm_adv_jitter',
                'mitm_adv_cap',
                'mitm_adv_loss',
            ):
                fk = f'{_pre}_timer_repeat_forever'
                if fk in s and bool(s.get(fk)):
                    original[f'{_pre}_timer_runs'] = -1
    except (JSONDecodeError, OSError):
        pass
    try:
        from tools.utils import repair_saved_iface_name, repair_nickname_last_ips_from_arp

        if repair_iface:
            original['iface'] = repair_saved_iface_name(original.get('iface', ''))
        original['nickname_last_ip'] = repair_nickname_last_ips_from_arp(
            original.get('nickname_last_ip') or {},
            original.get('nicknames') or {},
        )
    except Exception:
        pass
    export_settings([original[k] for k in SETTINGS_KEYS])

def migrate_settings_file():
    if path.exists(SETTINGS_PATH):
        return
    makedirs(DOCUMENTS_PATH, exist_ok=True)
    if path.exists(OLD_SETTINGS_PATH):
        try:
            rename(OLD_SETTINGS_PATH, SETTINGS_PATH)
            return
        except Exception as e:
            print(f'Migrating settings error: {e}')
    for legacy in LEGACY_SETTINGS_CANDIDATES:
        if legacy and path.exists(legacy):
            try:
                shutil.copy2(legacy, SETTINGS_PATH)
                return
            except Exception as e:
                print(f'Migrating settings from {legacy}: {e}')

def add_to_startup(exe_path):
    """
    Add ZubCut to autostart (Windows).
    """
    if sys.platform.startswith('win') and winreg:
        key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                HKEY_AUTOSTART_PATH,
                0,
                winreg.KEY_SET_VALUE
            )
        winreg.SetValueEx(
            key,
            AUTOSTART_REG_VALUE,
            0,
            winreg.REG_SZ, exe_path
        )

def remove_from_startup():
    """
    Remove ZubCut from autostart (Windows).
    """
    if sys.platform.startswith('win') and winreg:
        key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                HKEY_AUTOSTART_PATH,
                0,
                winreg.KEY_WRITE
            )
        try:
            winreg.DeleteValue(key, AUTOSTART_REG_VALUE)
        except FileNotFoundError:
            pass