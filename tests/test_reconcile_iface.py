"""Settings adapter vs Me row sync."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestReconcileIface(unittest.TestCase):
    def test_single_iface_pins_saved_settings_name(self) -> None:
        from tools.utils import reconcile_scanner_with_settings_iface

        only = mock.Mock()
        only.name = 'Wi-Fi-NPF'
        only.guid = '{abc}'
        only.ip = '192.168.1.44'

        class _Scanner:
            def __init__(self) -> None:
                self.iface = mock.Mock(name='stale', guid='old', ip='')
                self.my_ip = '192.168.1.44'

            def refresh_local_topology(self) -> None:
                self.my_ip = '192.168.1.44'

            def add_me(self) -> None:
                pass

            def add_router(self) -> None:
                pass

        scanner = _Scanner()
        settings: dict = {'iface': 'ghost-npf-name'}

        def _get_settings(key: str):
            return settings.get(key, '')

        def _set_settings(key: str, value: str) -> None:
            settings[key] = value

        with (
            mock.patch('tools.utils.get_ifaces_cached', return_value=[only]),
            mock.patch('tools.utils.get_iface_by_name', return_value=only),
            mock.patch('tools.utils.refresh_netface_live_ip'),
            mock.patch('tools.utils._iface_live_ipv4', return_value='192.168.1.44'),
            mock.patch('tools.utils_gui.get_settings', side_effect=_get_settings),
            mock.patch('tools.utils_gui.set_settings', side_effect=_set_settings),
        ):
            hint = reconcile_scanner_with_settings_iface(scanner, None)

        self.assertEqual(settings['iface'], 'Wi-Fi-NPF')
        self.assertEqual(scanner.iface, only)
        self.assertIn('adapter', hint.lower())

    def test_does_not_pin_leftover_hotspot_when_clumsy_off(self) -> None:
        from tools.utils import reconcile_scanner_with_settings_iface

        hotspot = mock.Mock()
        hotspot.name = 'Local Area Connection* 10'
        hotspot.guid = '{hot}'
        hotspot.ip = '0.0.0.0'

        wifi = mock.Mock()
        wifi.name = 'Wi-Fi'
        wifi.guid = '{wifi}'
        wifi.ip = '192.168.1.56'

        class _Scanner:
            def __init__(self) -> None:
                self.iface = hotspot
                self.my_ip = ''

            def refresh_local_topology(self, **_kwargs) -> None:
                self.my_ip = '192.168.1.56'

            def add_me(self) -> None:
                pass

            def add_router(self) -> None:
                pass

        scanner = _Scanner()
        settings: dict = {'iface': 'Wi-Fi'}

        def _get_settings(key: str):
            return settings.get(key, '')

        def _set_settings(key: str, value: str) -> None:
            settings[key] = value

        with (
            mock.patch('tools.utils.get_ifaces_cached', return_value=[hotspot]),
            mock.patch('tools.utils.get_iface_by_name', return_value=wifi),
            mock.patch('tools.utils.refresh_netface_live_ip'),
            mock.patch('tools.utils._iface_live_ipv4', return_value='192.168.1.56'),
            mock.patch('tools.utils._softap_bind_allowed', return_value=False),
            mock.patch('tools.utils_gui.get_settings', side_effect=_get_settings),
            mock.patch('tools.utils_gui.set_settings', side_effect=_set_settings),
        ):
            reconcile_scanner_with_settings_iface(scanner, None)

        self.assertEqual(settings['iface'], 'Wi-Fi')
        self.assertEqual(scanner.iface, wifi)


if __name__ == '__main__':
    unittest.main()
