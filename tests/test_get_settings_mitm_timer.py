"""get_settings must not crash on Advanced Lag timer keys."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import utils_gui as ug


class TestGetSettingsMitmTimer(unittest.TestCase):
    def test_missing_timer_key_returns_default_not_keyerror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'settings.json')
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump({}, fh)
            with patch.object(ug, 'SETTINGS_PATH', path), patch.object(
                ug, 'DOCUMENTS_PATH', tmp
            ):
                ug.check_documents_dir()
                val = ug.get_settings('mitm_adv_delay_timer_on')
        self.assertIs(val, False)

    def test_unknown_timer_key_fallback(self) -> None:
        self.assertEqual(ug._setting_key_fallback('mitm_adv_delay_timer_lag_ms'), 1000)
        self.assertEqual(ug._setting_key_fallback('mitm_adv_delay_timer_runs'), -1)


if __name__ == '__main__':
    unittest.main()
