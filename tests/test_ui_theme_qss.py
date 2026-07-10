"""Charcoal/teal theme wiring — menus and shared palette must not regress to qdark blue."""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _gui_source import load_main_window_source, methods_through, method_src


class TestUiThemeQss(unittest.TestCase):
    def test_context_menu_qss_uses_selection_and_me_palette(self) -> None:
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('def _context_menu_qss', src)
        self.assertIn('def theme_popup_menu', src)
        self.assertIn('_context_menu_qss()', src)
        block = src[src.index('def _context_menu_qss'): src.index('def theme_popup_menu')]
        self.assertIn('UI_TABLE_SELECTION_BG', block)
        self.assertIn('ADMIN_DEVICE_TABLE_ROW_BG', block)
        # Only the returned QSS template — docstring may mention banned qdark blues.
        qss = block[block.index('return f"""') :]
        self.assertIn('background-color: #000000', qss)
        self.assertIn('QMenu::indicator', qss)
        self.assertIn('image: none', qss)
        self.assertNotIn('#1A72BB', qss)
        self.assertNotIn('#37414F', qss)

    def test_generated_stylesheet_overrides_qdark_menu_blue(self) -> None:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from tools.utils_gui import zubcut_dark_stylesheet
        from constants import ADMIN_DEVICE_TABLE_ROW_BG, UI_TABLE_SELECTION_BG

        sheet = zubcut_dark_stylesheet()
        self.assertIn('QMenu {', sheet)
        # Last QMenu::item:selected block must be charcoal hover, not qdark blue.
        last_sel = sheet.rfind('QMenu::item:selected')
        self.assertGreater(last_sel, 0)
        tail = sheet[last_sel : last_sel + 220]
        self.assertIn('background-color: #000000', tail)
        self.assertIn(ADMIN_DEVICE_TABLE_ROW_BG, tail)
        self.assertNotIn('#1A72BB', tail)
        self.assertIn(UI_TABLE_SELECTION_BG, sheet[sheet.rfind('QMenu::item:pressed') :])
        _ = app  # keep app alive for stylesheet helpers

    def test_theme_popup_menu_sets_widget_stylesheet(self) -> None:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication, QMenu

        app = QApplication.instance() or QApplication([])
        from tools.utils_gui import theme_popup_menu
        from constants import ADMIN_DEVICE_TABLE_ROW_BG, UI_TABLE_SELECTION_BG

        menu = QMenu()
        theme_popup_menu(menu)
        sheet = menu.styleSheet()
        self.assertIn('background-color: #141414', sheet)
        self.assertIn(ADMIN_DEVICE_TABLE_ROW_BG, sheet)
        self.assertIn(UI_TABLE_SELECTION_BG, sheet)
        self.assertNotIn('#37414F', sheet)
        self.assertNotIn('#1A72BB', sheet)
        self.assertIn('QMenu::indicator', sheet)
        _ = app

    def test_main_applies_theme_to_all_context_menus(self) -> None:
        src = load_main_window_source()
        self.assertIn('theme_popup_menu', src)
        for fn in (
            '_on_status_log_context_menu',
            '_on_main_flow_toggle_context_menu',
            'table_context_menu',
            '_scan_table_header_context_menu',
        ):
            block = src[src.index(f'def {fn}'):]
            # Stop at next top-level method-ish def at same indent roughly via next "\n    def "
            nxt = block.find('\n    def ', 1)
            chunk = block[:nxt] if nxt > 0 else block[:800]
            self.assertIn('theme_popup_menu(menu)', chunk, msg=fn)
        self.assertIn('theme_popup_menu(tray_menu)', src)


if __name__ == '__main__':
    unittest.main()
