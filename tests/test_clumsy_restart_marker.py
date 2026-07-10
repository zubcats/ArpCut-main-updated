"""Settings-driven restart must keep Clumsy mode enabled."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import clumsy_ics as ics


class TestClumsyRestartMarker(unittest.TestCase):
    def test_marker_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # mark_* is Windows-gated (os.name == 'nt'); force that for Linux CI.
            with patch.object(ics, 'DOCUMENTS_PATH', tmp), patch.object(ics.os, 'name', 'nt'):
                self.assertFalse(ics.consume_clumsy_settings_restart_pending())
                ics.mark_clumsy_settings_restart_pending()
                self.assertTrue(os.path.isfile(ics.clumsy_settings_restart_marker_path()))
                self.assertTrue(ics.consume_clumsy_settings_restart_pending())
                self.assertFalse(os.path.isfile(ics.clumsy_settings_restart_marker_path()))


if __name__ == '__main__':
    unittest.main()
