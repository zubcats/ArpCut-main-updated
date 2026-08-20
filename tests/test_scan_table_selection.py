"""Scan table clicks must select User/PS5 rows even after a Me/Router currentIndex."""
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
from _gui_source import load_gui_file, method_src

from tools.qtools import resolve_scan_table_click_row, scan_table_item_flags


class TestResolveScanTableClickRow(unittest.TestCase):
    def test_prefers_clicked_user_row_over_admin_current(self) -> None:
        # Router=0, Me=1, PS5=2 — current stuck on Me, user clicked PS5.
        self.assertEqual(resolve_scan_table_click_row(3, 2, 1), 2)

    def test_falls_back_to_current_when_click_is_invalid(self) -> None:
        self.assertEqual(resolve_scan_table_click_row(3, -1, 2), 2)

    def test_rejects_out_of_range(self) -> None:
        self.assertEqual(resolve_scan_table_click_row(2, 5, 9), -1)
        self.assertEqual(resolve_scan_table_click_row(0, 0, 0), -1)

    def test_item_flags_keep_me_router_selectable(self) -> None:
        from PyQt5.QtCore import Qt

        flags = scan_table_item_flags()
        self.assertTrue(int(flags) & int(Qt.ItemIsEnabled))
        self.assertTrue(int(flags) & int(Qt.ItemIsSelectable))


class TestScanTableSelectionSource(unittest.TestCase):
    def test_fill_table_does_not_strip_selectable(self) -> None:
        src = load_gui_file('main.py')
        self.assertNotIn('selectable=False', src)
        fill = method_src('fillTableCell')
        self.assertIn('scan_table_item_flags()', fill)
        self.assertNotIn('ql.setFlags(Qt.ItemIsEnabled)', fill)

    def test_device_clicked_uses_clicked_item_row(self) -> None:
        clicked = method_src('deviceClicked')
        self.assertIn('item=None', clicked)
        self.assertIn('resolve_scan_table_click_row', clicked)
        self.assertIn('item.row()', clicked)
        self.assertIn("_schedule_impairment_stack_warm('select')", clicked)
        self.assertIn("_schedule_npcap_prewarm('select')", clicked)

    def test_kill_uses_current_row_not_selected_items(self) -> None:
        kill = method_src('kill')
        unkill = method_src('unkill')
        self.assertIn('_get_selected_device()', kill)
        self.assertIn('_get_selected_device()', unkill)
        self.assertNotIn('selectedItems()', kill)
        self.assertNotIn('selectedItems()', unkill)


class TestScanTableQtSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _table(self, *, admin_selectable: bool):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem

        t = QTableWidget(3, 1)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        for row, label in enumerate(('Router', 'Me', 'PS5')):
            item = QTableWidgetItem(label)
            if admin_selectable or row == 2:
                item.setFlags(scan_table_item_flags())
            else:
                item.setFlags(Qt.ItemIsEnabled)
            t.setItem(row, 0, item)
        return t

    def test_user_row_selectable_after_admin_current(self) -> None:
        t = self._table(admin_selectable=True)
        t.setCurrentCell(1, 0)
        t.selectRow(2)
        t.setCurrentCell(2, 0)
        self.assertEqual(t.currentRow(), 2)
        self.assertTrue(t.selectedItems())
        self.assertEqual(t.selectedItems()[0].text(), 'PS5')

    def test_mixed_flags_leave_me_unselectable(self) -> None:
        """Me/Router without ItemIsSelectable is the Qt 5.15 currentIndex trap."""
        from PyQt5.QtCore import Qt

        t = self._table(admin_selectable=False)
        t.setCurrentCell(1, 0)
        self.assertFalse(bool(t.item(1, 0).flags() & Qt.ItemIsSelectable))
        self.assertTrue(bool(t.item(2, 0).flags() & Qt.ItemIsSelectable))
        self.assertTrue(bool(t.item(1, 0).flags() & Qt.ItemIsEnabled))


if __name__ == '__main__':
    unittest.main()
