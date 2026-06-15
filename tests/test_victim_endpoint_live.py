"""Stale PS5 Ethernet row (.248) must not arm MITM after console moves to Wi‑Fi (.165)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.nicknames import stale_nickname_favorite_should_skip
from tools.utils import victim_endpoint_live_for_mitm


class TestVictimEndpointLive(unittest.TestCase):
    def test_stale_248_unreachable_fails_mitm(self) -> None:
        eth_mac = "00:E4:21:44:ED:0C"
        with (
            mock.patch("tools.utils.ipv4_ping_reachable", return_value=False),
            mock.patch("tools.utils.lookup_ip_from_arp_table", return_value=""),
        ):
            ok, reason = victim_endpoint_live_for_mitm(
                "192.168.1.248", eth_mac, "192.168.1.56"
            )
        self.assertFalse(ok)
        self.assertIn("not reachable", reason.lower())

    def test_wifi_165_live_when_ping_ok(self) -> None:
        wifi_mac = "DC:E9:94:AB:E6:C4"
        with (
            mock.patch("tools.utils.ipv4_ping_reachable", return_value=True),
            mock.patch("tools.utils.lookup_mac_from_arp_table", return_value=wifi_mac),
            mock.patch("tools.utils.lookup_ip_from_arp_table", return_value="192.168.1.165"),
        ):
            ok, _ = victim_endpoint_live_for_mitm(
                "192.168.1.165", wifi_mac, "192.168.1.56"
            )
        self.assertTrue(ok)

    def test_moved_device_hint_when_mac_has_new_ip(self) -> None:
        eth_mac = "00:E4:21:44:ED:0C"
        with (
            mock.patch("tools.utils.ipv4_ping_reachable", return_value=False),
            mock.patch(
                "tools.utils.lookup_ip_from_arp_table", return_value="192.168.1.165"
            ),
        ):
            ok, reason = victim_endpoint_live_for_mitm(
                "192.168.1.248", eth_mac, "192.168.1.56"
            )
        self.assertFalse(ok)
        self.assertIn("192.168.1.165", reason)

    def test_phantom_favorite_skipped_when_ip_unpingable(self) -> None:
        eth_mac = "00:E4:21:44:ED:0C"
        with (
            mock.patch("tools.utils.lookup_ip_from_arp_table", return_value=""),
            mock.patch("tools.utils.lookup_mac_from_arp_table", return_value=""),
            mock.patch("tools.utils.ipv4_ping_reachable", return_value=False),
        ):
            skip = stale_nickname_favorite_should_skip(
                eth_mac, "192.168.1.248", "192.168.1.56"
            )
        self.assertTrue(skip)


if __name__ == "__main__":
    unittest.main()
