"""Charcoal/teal theme wiring — menus and shared palette must not regress to qdark blue."""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestUiThemeQss(unittest.TestCase):
    def test_context_menu_qss_uses_selection_and_me_palette(self) -> None:
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('def _context_menu_qss', src)
        self.assertIn('_context_menu_qss()', src)
        block = src[src.index('def _context_menu_qss'): src.index('def zubcut_dark_stylesheet')]
        self.assertIn('UI_TABLE_SELECTION_BG', block)
        self.assertIn('ADMIN_DEVICE_TABLE_ROW_BG', block)
        # Only the returned QSS template — docstring may mention banned qdark blues.
        qss = block[block.index('return f"""') :]
        self.assertIn('background-color: #000000', qss)
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


if __name__ == '__main__':
    unittest.main()
