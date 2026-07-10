"""Advanced Lag OFF must halt shaping before clearing UI flags."""
from __future__ import annotations

import os
import sys
import unittest

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _gui_source import load_main_window_source, methods_through, method_src


class TestMitmShapingStop(unittest.TestCase):
    def test_stop_halt_traffic_before_ui_clear(self) -> None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        src = load_main_window_source()
        fn = method_src("stop_mitm_shaping")
        halt = fn.index("_halt_mitm_shaping_traffic_now")
        clear = fn.index("self.mitm_shaping_active = False")
        self.assertLess(halt, clear, "shaping must stop before mitm_shaping_active clears")

    def test_halt_helper_stops_forwarder_and_unkill(self) -> None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        src = load_main_window_source()
        fn = method_src("_halt_mitm_shaping_traffic_now")
        self.assertIn("_stop_forwarder", fn)
        self.assertIn("unkill", fn)


if __name__ == "__main__":
    unittest.main()
