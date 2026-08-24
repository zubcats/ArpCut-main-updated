"""LAN Kill poison/restore frames: unicast + Wi‑Fi broadcast, request + reply."""
from __future__ import annotations

import os
import sys
import threading
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.ifaces import NetFace
from networking.killer import Killer


def _face(name: str, guid: str, ip: str, mac: str) -> NetFace:
    return NetFace(
        {
            'name': name,
            'guid': guid,
            'mac': mac,
            'ips': [ip],
        }
    )


class TestKillPoisonFrames(unittest.TestCase):
    def _poison_block(self) -> str:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        return src[src.index('def _poison_frames'): src.index('def _poison_arp_now')]

    def test_poison_frames_keep_unicast_and_wifi_victim_broadcast(self) -> None:
        block = self._poison_block()
        self.assertIn("dst=victim['mac']", block)
        self.assertIn("dst=self.router['mac']", block)
        self.assertIn('iface_is_wireless', block)
        self.assertIn('ff:ff:ff:ff:ff:ff', block)
        self.assertIn("pdst=victim['ip']", block)
        self.assertIn('_poison_hwsrc', block)
        self.assertIn('src=src', block)
        self.assertIn('hwsrc=src', block)

    def test_poison_frames_include_request_and_reply(self) -> None:
        block = self._poison_block()
        self.assertIn('op=1', block)
        self.assertIn('op=2', block)
        # Both ends of the MITM pair get request + reply; router-side is reinforced.
        self.assertGreaterEqual(block.count('op=1'), 2)
        self.assertGreaterEqual(block.count('op=2'), 2)
        self.assertIn('to_router_req', block)
        self.assertGreaterEqual(block.count('to_router_req'), 2)


class TestKillRestoreFrames(unittest.TestCase):
    def _restore_block(self) -> str:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        return src[src.index('def _restore_frames'): src.index('def _restore_arp_now')]

    def _unkill_block(self) -> str:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        return src[src.index('def unkill'): src.index('def reinforce_restore')]

    def _killer(self, *, wifi: bool) -> Killer:
        k = Killer.__new__(Killer)
        name = 'Wi-Fi' if wifi else 'Ethernet'
        k.iface = _face(
            name,
            r'\Device\NPF_{5B106E08-62B0-4A70-B2AC-AEDD80B5B255}',
            '192.168.1.56',
            'aa:aa:aa:aa:aa:aa',
        )
        k.router = {'ip': '192.168.1.1', 'mac': '74:24:9f:3a:a3:75'}
        k.killed = {}
        k._op_seq = {}
        k._socket = None
        k._socket_lock = threading.RLock()
        return k

    def test_restore_frames_use_honest_hwsrc_not_pc_mac(self) -> None:
        block = self._restore_block()
        self.assertIn('hwsrc=router_mac', block)
        self.assertIn('hwsrc=victim_mac', block)
        self.assertIn('iface_is_wireless', block)
        self.assertIn('ff:ff:ff:ff:ff:ff', block)
        self.assertIn('op=1', block)
        self.assertIn('op=2', block)
        self.assertIn('_refresh_router_mac_for_mitm', self._unkill_block())

    def test_wifi_restore_broadcasts_honest_gateway_to_victim(self) -> None:
        from scapy.all import ARP, Ether

        k = self._killer(wifi=True)
        victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        frames = k._restore_frames(victim)
        self.assertTrue(frames)
        bcast = [f for f in frames if str(f[Ether].dst).lower() == 'ff:ff:ff:ff:ff:ff']
        self.assertGreaterEqual(len(bcast), 2)
        honest_gw = [
            f
            for f in bcast
            if str(f[ARP].psrc) == '192.168.1.1'
            and str(f[ARP].hwsrc).lower() == '74:24:9f:3a:a3:75'
            and str(f[ARP].pdst) == '192.168.1.248'
        ]
        self.assertTrue(honest_gw, 'Wi-Fi restore must broadcast honest gateway mapping')
        for f in frames:
            if str(f[ARP].psrc) == '192.168.1.1':
                self.assertEqual(str(f[ARP].hwsrc).lower(), '74:24:9f:3a:a3:75')
                self.assertNotEqual(str(f[ARP].hwsrc).lower(), 'aa:aa:aa:aa:aa:aa')

    def test_ethernet_restore_stays_unicast(self) -> None:
        from scapy.all import Ether

        k = self._killer(wifi=False)
        victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        frames = k._restore_frames(victim)
        bcast = [f for f in frames if str(f[Ether].dst).lower() == 'ff:ff:ff:ff:ff:ff']
        self.assertEqual(bcast, [])
        self.assertGreaterEqual(len(frames), 4)

    def test_restore_now_sends_all_restore_frames(self) -> None:
        k = self._killer(wifi=True)
        victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        k._op_seq[victim['mac']] = 1
        sent = []
        k._send_packet = sent.append  # type: ignore[method-assign]
        k._restore_arp_now(victim, seq=1, repeats=1, delay_s=0)
        self.assertEqual(len(sent), len(k._restore_frames(victim)))

    def test_unkill_all_uses_per_device_unkill_for_lan(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        block = src[src.index('def unkill_all'): src.index('def store')]
        self.assertIn('self.unkill(victim, ics_mode=False)', block)


if __name__ == '__main__':
    unittest.main()
