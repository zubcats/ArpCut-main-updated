"""Advanced Lag OFF must halt shaping before clearing UI flags."""
from __future__ import annotations

import os
import unittest


class TestMitmShapingStop(unittest.TestCase):
    def test_stop_halt_traffic_before_ui_clear(self) -> None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(root, "src", "gui", "main.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        fn = src[src.index("def stop_mitm_shaping") : src.index("def _schedule_kill_command")]
        halt = fn.index("_halt_mitm_shaping_traffic_now")
        clear = fn.index("self.mitm_shaping_active = False")
        self.assertLess(halt, clear, "shaping must stop before mitm_shaping_active clears")

    def test_halt_helper_stops_forwarder_and_unkill(self) -> None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(root, "src", "gui", "main.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        fn = src[
            src.index("def _halt_mitm_shaping_traffic_now")
            : src.index("def stop_mitm_shaping")
        ]
        self.assertIn("_stop_forwarder", fn)
        self.assertIn("unkill", fn)


if __name__ == "__main__":
    unittest.main()
