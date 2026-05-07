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

from tools.utils import terminal
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
    background-color: #5D706E;
    border-radius: 3px;
}
QMenu::item:selected, QMenuBar::item:selected {
    background-color: #000000;
}
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
QLabel#lblleft, QLabel#lblcenter, QLabel#lblright {{
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
"""


def _lag_dupe_dialog_chrome_qss() -> str:
    """
    Lag Switch / Dupe: solid black client (no translucent bleed), teal grey-green borders
    (UI_TOGGLE_BORDER_ACCENT), stable 1px borders to avoid hover text shift.
    """
    acc = getattr(_zcut_constants, 'UI_TOGGLE_BORDER_ACCENT', '#316E69')
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
    spacing: 6px;
    padding: 2px 0;
    margin: 0;
    outline: none;
}}
QDialog#zubcutLagDupeDialog QLabel {{
    padding: 1px 0;
    margin: 0;
}}
QDialog#zubcutLagDupeDialog QSpinBox,
QDialog#zubcutLagDupeDialog QKeySequenceEdit {{
    background-color: {fill};
    color: #e8eaed;
    border: 1px solid {acc};
    border-radius: 3px;
    padding: 4px 6px;
    outline: none;
}}
QDialog#zubcutLagDupeDialog QSpinBox:focus,
QDialog#zubcutLagDupeDialog QKeySequenceEdit:focus {{
    border: 1px solid {acc};
}}
QDialog#zubcutLagDupeDialog QSpinBox::up-button,
QDialog#zubcutLagDupeDialog QSpinBox::down-button {{
    background-color: {fill};
    border: 1px solid {acc};
    width: 16px;
}}
QDialog#zubcutLagDupeDialog QSpinBox::up-button:hover,
QDialog#zubcutLagDupeDialog QSpinBox::down-button:hover {{
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


def _update_top_level_round_mask(widget):
    """Clip the entire top-level window to a rounded rect (fixes square corners / bleed-through)."""
    if widget is None or not widget.isWindow():
        return
    if widget.isMaximized() or widget.isFullScreen():
        widget.clearMask()
        return
    w, h = widget.width(), widget.height()
    if w < 2 or h < 2:
        return
    r = min(float(_WINDOW_CORNER_RADIUS), max(2.0, min(float(w), float(h)) / 2.0 - 1.0))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, float(w), float(h)), r, r)
    # QRegion expects an integer polygon on PyQt5; PolygonF can raise at runtime.
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


class _WindowChromeEventFilter(QObject):
    """First Show: DWM hints. Show/resize/state: rounded QWidget mask for frameless windows."""

    def __init__(self, parent_widget):
        super().__init__(parent_widget)
        self._dwm_applied = False

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Show and not self._dwm_applied:
            self._dwm_applied = True
            _apply_win32_dwm_window_chrome(obj)
        if t in (QEvent.Show, QEvent.Resize, QEvent.WindowStateChange):
            _update_top_level_round_mask(obj)
        return False


def _apply_win32_dwm_window_chrome(widget):
    """
    Same DWM calls on every Windows version we support: immersive dark + optional round-corners hint.
    Older builds ignore attributes they do not implement. Rounded outline is always from the Qt mask.
    """
    if not sys.platform.startswith('win'):
        return
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        hwnd_p = ctypes.c_void_p(hwnd)
    except Exception:
        return

    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(
            hwnd_p,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark),
            ctypes.sizeof(dark),
        )
    except Exception:
        pass

    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        preference = ctypes.c_uint(DWMWCP_ROUND)
        dwm.DwmSetWindowAttribute(
            hwnd_p,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
    except Exception:
        pass


def register_window_surface_effects(window_widget):
    """Translucent client + DWM hints (same path on all Windows); Qt mask provides the real rounded clip."""
    if window_widget is None:
        return
    use_translucent = getattr(window_widget, '_zubcut_use_translucent_surface', True)
    window_widget.setAttribute(Qt.WA_TranslucentBackground, bool(use_translucent))
    if getattr(window_widget, '_zubcut_round_filter_installed', False):
        return
    window_widget._zubcut_round_filter_installed = True
    window_widget.installEventFilter(_WindowChromeEventFilter(window_widget))


def sync_translucent_chrome(windows):
    """Per-pixel alpha with the desktop behind the dark theme chrome."""
    for w in windows:
        register_window_surface_effects(w)



def is_admin():
    """
    Check if current user is Admin
    """
    if sys.platform.startswith('win'):
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    # On macOS/Linux, assume current user context (no UAC)
    return True

def npcap_exists():
    """
    Check for Npcap driver (Windows only)
    """
    if sys.platform.startswith('win'):
        return path.exists(NPCAP_PATH)
    # macOS/Linux uses libpcap (bundled); always True
    return True

def duplicate_zubcut():
    """Single-instance guard (reserved; not implemented)."""
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
    return load(open(SETTINGS_PATH))

def export_settings(values=None):
    """
    Store current settings (or create new)
    """
    keys = SETTINGS_KEYS
    values = values if values else SETTINGS_VALS
    json = dict(zip(keys, values))
    dump(json, open(SETTINGS_PATH, 'w'))

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

def get_settings(key):
    """
    Get certain setting item by key
    """
    return import_settings()[key]

def restart_zubcut(main_window=None):
    """
    Start a new ZubCut process and quit this one (Windows-friendly detach).
    Used when Clumsy mode (or similar) must fully reset runtime state.
    """
    import subprocess

    app = None
    try:
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
    except Exception:
        pass

    exe = sys.executable
    cwd = os.path.dirname(exe) if getattr(sys, 'frozen', False) else os.getcwd()
    try:
        if sys.platform.startswith('win'):
            cf = getattr(subprocess, 'DETACHED_PROCESS', 0)
            subprocess.Popen(
                [exe],
                cwd=cwd,
                close_fds=True,
                creationflags=cf,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen([exe], cwd=cwd, close_fds=True)
    except Exception as e:
        print(f'restart_zubcut: failed to spawn process: {e}')
        return
    if main_window is not None and hasattr(main_window, 'quit_all'):
        main_window.quit_all()
    elif app is not None:
        app.quit()


def repair_settings():
    """
    Merge defaults when settings are missing keys or JSON is invalid.
    """
    original = dict(zip(SETTINGS_KEYS, SETTINGS_VALS))
    try:
        s = import_settings()
        for key in SETTINGS_KEYS:
            if key in s:
                original[key] = s[key]
    except (JSONDecodeError, OSError):
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