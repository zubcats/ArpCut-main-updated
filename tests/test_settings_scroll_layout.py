"""Settings must stay scrollable / screen-capped so Update stays reachable."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def _load_capped_height_fn():
    """Load pure helper without importing PyQt5-dependent gui.settings."""
    path = os.path.join(_SRC, 'gui', 'settings.py')
    with open(path, encoding='utf-8') as f:
        src = f.read()
    start = src.index('def _capped_settings_window_height')
    end = src.index('def _settings_keybind_mono_font')
    ns: dict = {}
    exec(src[start:end], ns)  # noqa: S102 — test-only extract of pure helper
    return ns['_capped_settings_window_height']


class TestSettingsHeightCap(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Keep off the class dict so Python does not bind it as a method.
        cls._cap_fn = staticmethod(_load_capped_height_fn())

    def test_caps_to_available_screen(self) -> None:
        # 720p-ish laptop with tall content must not open taller than the screen.
        h = self._cap_fn(780, 720, margin=48, min_h=420)
        self.assertEqual(h, 672)
        self.assertLessEqual(h, 720)

    def test_prefers_content_when_screen_is_tall(self) -> None:
        h = self._cap_fn(620, 1080, margin=48, min_h=420)
        self.assertEqual(h, 620)

    def test_tiny_screen_uses_hard_floor_not_content_min(self) -> None:
        h = self._cap_fn(780, 200, margin=48, min_h=420)
        self.assertEqual(h, 280)


class TestSettingsScrollSource(unittest.TestCase):
    def test_settings_uses_scroll_shell_and_no_fixed_tall_lock(self) -> None:
        path = os.path.join(_SRC, 'gui', 'settings.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('def _install_settings_scroll_shell', src)
        self.assertIn('zubcutSettingsScroll', src)
        self.assertIn('_capped_settings_window_height', src)
        block = src[
            src.index('def _finalize_settings_layout') : src.index(
                'def _refresh_clumsy_settings_widgets'
            )
        ]
        self.assertNotIn('setFixedSize', block)
        self.assertIn('_settings_available_height', block)

    def test_auxiliary_qss_themes_settings_scroll(self) -> None:
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('zubcutSettingsScroll', src)
        self.assertIn('zubcutSettingsScrollInner', src)


if __name__ == '__main__':
    unittest.main()
