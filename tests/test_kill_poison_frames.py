"""LAN Kill poison/restore frames: unicast poison, honest restore, request + reply."""
from __future__ import annotations

import os
import sys
import threading
import unittest
from unittest import mock

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

    def test_poison_send_aborts_mid_burst_after_unkill(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        now = src[src.index('def _poison_arp_now('): src.index('def _poison_arp_now_async')]
        worker = src[src.index('def _kill_arp_worker'): src.index('def unkill(')]
        self.assertIn('victim[\'mac\'] not in self.killed', now)
        self.assertIn('for frame in frames:', now)
        self.assertLess(now.index('for frame in frames:'), now.rindex('not in self.killed'))
        self.assertIn('for frame in frames:', worker)
        self.assertIn('self._op_seq.get(victim[\'mac\']) != seq', worker)

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
        self.assertIn('op=1', block)
        self.assertIn('op=2', block)
        self.assertIn('ff:ff:ff:ff:ff:ff', block)
        self.assertNotIn("psrc=victim_ip", block[block.index("if wifi"):] if 'if wifi' in block else '')
        self.assertNotIn('_refresh_router_mac_for_mitm', self._unkill_block())
        lan = self._unkill_block()
        self.assertIn('_ensure_restore_pass', lan)
        self.assertIn('_pin_local_gateway_neighbor_async', lan)
        self.assertIn('_unkill_restore_worker', lan)
        self.assertNotIn('self._restore_arp_now(', lan)
        self.assertLess(lan.index('self._next_op_seq'), lan.index('_ensure_restore_pass'))
        ics = lan[lan.index('if ics_mode:'): lan.index('else:')]
        self.assertIn('self._stop_forwarder(mac)', ics)

    def test_wifi_restore_broadcasts_honest_gateway_like_poison(self) -> None:
        from scapy.all import ARP, Ether

        k = self._killer(wifi=True)
        victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        frames = k._restore_frames(victim)
        self.assertTrue(frames)
        bcast = [f for f in frames if str(f[Ether].dst).lower() == 'ff:ff:ff:ff:ff:ff']
        self.assertEqual(len(bcast), 4)
        as_router = [
            f for f in bcast if str(f[Ether].src).lower() == '74:24:9f:3a:a3:75'
        ]
        self.assertEqual(len(as_router), 2)
        for f in bcast:
            self.assertEqual(str(f[ARP].psrc), '192.168.1.1')
            self.assertEqual(str(f[ARP].hwsrc).lower(), '74:24:9f:3a:a3:75')
            self.assertEqual(str(f[ARP].pdst), '192.168.1.248')
            self.assertEqual(str(f[ARP].hwdst).lower(), '00:e4:21:44:ed:0c')
            self.assertNotEqual(str(f[ARP].hwsrc).lower(), 'aa:aa:aa:aa:aa:aa')
        # Must not GARP the PS5 IP from this PC (re-poisons the router).
        victim_garp = [
            f
            for f in frames
            if str(f[ARP].psrc) == '192.168.1.248'
            and str(f[Ether].dst).lower() == 'ff:ff:ff:ff:ff:ff'
        ]
        self.assertEqual(victim_garp, [])

    def test_restore_uses_kill_on_gateway_when_cache_points_at_pc(self) -> None:
        from scapy.all import ARP

        k = self._killer(wifi=True)
        k._restore_router = {'ip': '192.168.1.1', 'mac': '74:24:9F:3A:A3:75'}
        k.router = {'ip': '192.168.1.1', 'mac': 'AA:AA:AA:AA:AA:AA'}
        victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        frames = k._restore_frames(victim)
        self.assertTrue(frames)
        for f in frames:
            if str(f[ARP].psrc) == '192.168.1.1':
                self.assertEqual(str(f[ARP].hwsrc).lower(), '74:24:9f:3a:a3:75')

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

        class _Sock:
            closed = False

            def send(self, frame):
                sent.append(frame)

        k._socket = _Sock()
        k._restore_arp_now(victim, seq=1, repeats=1, delay_s=0)
        self.assertEqual(len(sent), len(k._restore_frames(victim)))

    def test_unicast_followup_restore_skips_broadcast_and_router_sa(self) -> None:
        from scapy.all import ARP, Ether

        k = self._killer(wifi=True)
        victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        frames = k._restore_frames(victim, unicast_only=True)
        self.assertTrue(frames)
        router = '74:24:9f:3a:a3:75'
        pc = 'aa:aa:aa:aa:aa:aa'
        for f in frames:
            self.assertNotEqual(str(f[Ether].dst).lower(), 'ff:ff:ff:ff:ff:ff')
            self.assertEqual(str(f[Ether].src).lower(), pc)
            self.assertNotEqual(str(f[Ether].src).lower(), router)
            if str(f[ARP].psrc) == '192.168.1.1':
                self.assertEqual(str(f[ARP].hwsrc).lower(), router)

    def test_wifi_poison_broadcasts_are_victim_targeted(self) -> None:
        from scapy.all import ARP, Ether

        k = self._killer(wifi=True)
        victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        frames = k._poison_frames(victim)
        bcast = [f for f in frames if str(f[Ether].dst).lower() == 'ff:ff:ff:ff:ff:ff']
        self.assertEqual(len(bcast), 2)
        for f in bcast:
            self.assertEqual(str(f[ARP].pdst), '192.168.1.248')
            self.assertEqual(str(f[ARP].hwdst).lower(), '00:e4:21:44:ed:0c')
            self.assertEqual(str(f[ARP].psrc), '192.168.1.1')

    def test_lan_unkill_flips_to_pass_through(self) -> None:
        k = self._killer(wifi=True)
        k._unkill_relays = set()
        k._restore_pass_until = {}
        victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        k.killed = {victim['mac']: victim}
        k._op_seq = {victim['mac']: 0}
        k.forwarders = {victim['mac']: mock.Mock(running=True)}
        k.l2_socket_ready = lambda: False  # type: ignore[method-assign]
        k.prewarm_l2_socket = lambda join_ms=0: False  # type: ignore[method-assign]
        k._unkill_restore_worker = lambda *a, **kw: None  # type: ignore[method-assign]
        k._sync_iface_for_victim = lambda *a, **kw: None  # type: ignore[method-assign]
        k._refresh_router_mac_for_mitm = lambda: None  # type: ignore[method-assign]
        k._unblock_victim_firewall = mock.Mock()  # type: ignore[method-assign]
        k._stop_forwarder = mock.Mock()  # type: ignore[method-assign]
        k.resume_percent_cut_live = mock.Mock(return_value=True)  # type: ignore[method-assign]
        k._hold_restore_pass = mock.Mock()  # type: ignore[method-assign]
        k._pin_local_gateway_neighbor_async = mock.Mock()  # type: ignore[method-assign]
        with mock.patch('networking.killer.enable_ip_forwarding') as enable:
            k.unkill(victim, ics_mode=False)
        k._unblock_victim_firewall.assert_called_once()
        k._stop_forwarder.assert_not_called()
        k.resume_percent_cut_live.assert_called_once_with(victim['mac'])
        k._hold_restore_pass.assert_called_once()
        k._pin_local_gateway_neighbor_async.assert_called_once()
        enable.assert_not_called()
        self.assertNotIn(victim['mac'], k._unkill_relays)
        self.assertNotIn(victim['mac'], k.killed)

    def test_seal_hard_drop_skips_when_not_killed(self) -> None:
        k = self._killer(wifi=True)
        mac = '00:e4:21:44:ed:0c'
        fw = mock.Mock(running=True, drop_from_victim=False, drop_to_victim=False)
        k.forwarders = {mac: fw}
        k.killed = {}
        self.assertFalse(k._seal_hard_drop(mac))
        self.assertFalse(fw.drop_from_victim)

    def test_apply_percent_cut_after_off_does_not_rearm(self) -> None:
        k = self._killer(wifi=True)
        victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        k.killed = {}
        k.kill = mock.Mock()  # type: ignore[method-assign]
        self.assertFalse(k.apply_percent_cut(victim, pass_percent=0, arm_if_needed=False))
        k.kill.assert_not_called()

    def test_seal_hard_drop_reverts_after_unkill(self) -> None:
        k = self._killer(wifi=True)
        mac = '00:e4:21:44:ed:0c'
        fw = mock.Mock(running=True, drop_from_victim=False, drop_to_victim=False)
        fw.pass_all_live = mock.Mock()
        k.forwarders = {mac: fw}

        class _RaceDict(dict):
            def __contains__(self, key, _n=[0]):
                _n[0] += 1
                if _n[0] == 1:
                    return True
                return False

        k.killed = _RaceDict({mac: {'mac': mac}})
        self.assertFalse(k._seal_hard_drop(mac))
        fw.pass_all_live.assert_called()

    def test_idle_reconcile_keeps_pass_through_forwarders(self) -> None:
        path = os.path.join(_SRC, 'gui', 'impairment_mitm.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        start = src.index('def _reconcile_idle_mitm_state')
        block = src[start : start + 4000]
        self.assertIn('disable_percent_cut', block)
        self.assertIn('if pass_all:', block)
        self.assertNotIn('_restore_pass_until', block)
        self.assertNotIn('_unkill_relays', block)

    def test_unkill_all_uses_per_device_unkill_for_lan(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        block = src[src.index('def unkill_all'): src.index('def store')]
        self.assertIn('self.unkill(victim, ics_mode=False)', block)


if __name__ == '__main__':
    unittest.main()
