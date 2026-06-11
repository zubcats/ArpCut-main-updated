import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.utils import _is_bad_iface_display_name, repair_saved_iface_name


class TestIfaceRepair(unittest.TestCase):
    def test_bad_description_label(self) -> None:
        self.assertTrue(_is_bad_iface_display_name('Description . . . . . . . . . . .'))

    def test_repair_saved_iface_not_empty(self) -> None:
        name = repair_saved_iface_name('Description . . . . . . . . . . .')
        self.assertTrue(name)
        self.assertFalse(_is_bad_iface_display_name(name))
