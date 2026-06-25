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
            mock.patch("tools.utils.lookup_mac_from_arp_table", return_value=""),
        ):
            ok, reason = victim_endpoint_live_for_mitm(
                "192.168.1.248", eth_mac, "192.168.1.56"
            )
        self.assertFalse(ok)
        self.assertIn('ping', reason.lower())

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

    def test_arp_fallback_when_ping_silent_but_mac_matches(self) -> None:
        wifi_mac = "DC:E9:94:AB:E6:C4"
        with (
            mock.patch("tools.utils.ipv4_ping_reachable", return_value=False),
            mock.patch("tools.utils.lookup_mac_from_arp_table", return_value=wifi_mac),
            mock.patch("tools.utils.lookup_ip_from_arp_table", return_value="192.168.1.165"),
        ):
            ok, reason = victim_endpoint_live_for_mitm(
                "192.168.1.165", wifi_mac, "192.168.1.56"
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_moved_device_hint_when_mac_has_new_ip(self) -> None:
        eth_mac = "00:E4:21:44:ED:0C"
        with (
            mock.patch("tools.utils.ipv4_ping_reachable", return_value=False),
            mock.patch(
                "tools.utils.lookup_ip_from_arp_table", return_value="192.168.1.248"
            ),
        ):
            ok, reason = victim_endpoint_live_for_mitm(
                "192.168.1.165", eth_mac, "192.168.1.56"
            )
        self.assertFalse(ok)
        self.assertIn("192.168.1.248", reason)

    def test_resolve_live_lan_follows_nickname_sibling(self) -> None:
        from tools.utils import resolve_live_lan_victim

        wifi_mac = "DC:E9:94:AB:E6:C4"
        eth_mac = "00:E4:21:44:ED:0C"
        stale = {
            "ip": "192.168.1.165",
            "mac": wifi_mac,
            "name": "PS5 DUPE",
        }
        live_row = {
            "ip": "192.168.1.248",
            "mac": eth_mac,
            "name": "PS5 DUPE",
        }
        devices = [stale, live_row]

        def _live(ip, mac, _iface):
            if ip == "192.168.1.248" and mac == eth_mac:
                return True, ""
            return False, "offline"

        with (
            mock.patch("tools.utils.victim_endpoint_live_for_mitm", side_effect=_live),
            mock.patch("tools.utils._arp_refresh_device_record"),
            mock.patch("tools.utils.lookup_ip_from_arp_table", return_value=""),
        ):
            resolved, hint = resolve_live_lan_victim(
                stale, devices, "192.168.1.56"
            )
        self.assertEqual(resolved.get("ip"), "192.168.1.248")
        self.assertEqual(resolved.get("mac"), eth_mac)
        self.assertIn("PS5 DUPE", hint)

    def test_resolve_live_lan_reverse_arp_ip_move(self) -> None:
        from tools.utils import resolve_live_lan_victim

        eth_mac = "00:E4:21:44:ED:0C"
        stale = {"ip": "192.168.1.165", "mac": eth_mac, "name": "-"}
        calls = {"n": 0}

        def _live(ip, mac, _iface):
            if ip == "192.168.1.248" and mac == eth_mac:
                return True, ""
            return False, "offline"

        def _reverse(mac, _iface):
            if mac == eth_mac:
                return "192.168.1.248"
            return ""

        with (
            mock.patch("tools.utils.victim_endpoint_live_for_mitm", side_effect=_live),
            mock.patch("tools.utils._arp_refresh_device_record"),
            mock.patch("tools.utils.lookup_ip_from_arp_table", side_effect=_reverse),
        ):
            resolved, hint = resolve_live_lan_victim(stale, [], "192.168.1.56")
        self.assertEqual(resolved.get("ip"), "192.168.1.248")
        self.assertIn("248", hint)

    def test_resolve_live_lan_single_playstation_fallback(self) -> None:
        from tools.utils import resolve_live_lan_victim

        wifi_mac = "DC:E9:94:AB:E6:C4"
        eth_mac = "00:E4:21:44:ED:0C"
        stale = {
            "ip": "192.168.1.165",
            "mac": wifi_mac,
            "name": "-",
            "type": "Game console (PlayStation)",
            "vendor": "Sony Interactive Entertainment Inc.",
        }
        eth_row = {
            "ip": "192.168.1.248",
            "mac": eth_mac,
            "name": "-",
            "type": "Game console (PlayStation)",
            "vendor": "Sony Interactive Entertainment Inc.",
        }

        def _live(ip, mac, _iface):
            if ip == "192.168.1.248" and mac == eth_mac:
                return True, ""
            return False, "offline"

        with (
            mock.patch("tools.utils.victim_endpoint_live_for_mitm", side_effect=_live),
            mock.patch("tools.utils._arp_refresh_device_record"),
            mock.patch("tools.utils.lookup_ip_from_arp_table", return_value=""),
        ):
            resolved, hint = resolve_live_lan_victim(
                stale, [stale, eth_row], "192.168.1.56"
            )
        self.assertEqual(resolved.get("ip"), "192.168.1.248")
        self.assertIn("PlayStation", hint)

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
