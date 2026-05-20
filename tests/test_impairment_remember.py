"""Remember-kill and rekill must not ARP-spoof ICS / WinDivert victims."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.ics_impairment_policy import (
    DeviceImpairmentPlan,
    PATH_HOTSPOT,
    should_restore_remembered_kill,
)


class TestImpairmentRemember(unittest.TestCase):
    def test_should_not_restore_arp_for_windivert_plan(self) -> None:
        plan = DeviceImpairmentPlan(
            path=PATH_HOTSPOT,
            table_ip='192.168.1.50',
            resolved_ip='192.168.137.42',
            downstream_prefix='192.168.137.',
            clumsy_topology='hotspot',
            use_windivert=True,
            use_arp_mitm=False,
            use_block_ip=False,
            use_mitm_forwarder=False,
            windivert_ready=True,
        )
        dev = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.137.42'}
        with mock.patch(
            'tools.ics_impairment_policy.classify_device_impairment',
            return_value=plan,
        ):
            self.assertFalse(should_restore_remembered_kill(dev, None))

    def test_should_restore_arp_for_regular_lan(self) -> None:
        dev = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.1.50'}
        with mock.patch(
            'tools.ics_impairment_policy.classify_device_impairment'
        ) as clf:
            from tools.ics_impairment_policy import _regular_plan

            clf.return_value = _regular_plan('192.168.1.50', '192.168.1.50')
            self.assertTrue(should_restore_remembered_kill(dev, None))


if __name__ == '__main__':
    unittest.main()
