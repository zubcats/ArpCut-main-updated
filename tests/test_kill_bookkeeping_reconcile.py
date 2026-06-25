"""Kill UI/backend bookkeeping (no Qt, no networking imports)."""
from __future__ import annotations

import unittest


class _FakeForwarder:
    def __init__(self, running: bool = True):
        self.running = running


def _parse_pk(pk: str) -> str:
    return pk.split('|', 1)[0] if '|' in pk else pk


def _explicit_kill_backend_live(app, mac: str) -> bool:
    mac = str(mac or '').strip()
    if not mac:
        return False
    if mac in getattr(app, '_ics_kill_profile_macs', set()):
        gate = getattr(app, '_ics_lag_gate', None)
        if gate is not None and getattr(gate, 'is_running', lambda: False)():
            return True
        if mac in getattr(app.killer, 'killed', {}):
            return True
    return mac in getattr(app.killer, 'killed', {})


def _sync_killed_devices(app) -> None:
    pending = getattr(app, '_kill_pending_profiles', set())
    for pk in list(app.killed_devices.keys()):
        if not app.killed_devices.get(pk):
            continue
        mac = _parse_pk(pk)
        if not mac:
            app.killed_devices.pop(pk, None)
            continue
        if pk in pending:
            continue
        if mac in getattr(app, '_ics_kill_profile_macs', set()):
            continue
        if _explicit_kill_backend_live(app, mac):
            continue
        app.killed_devices[pk] = False


class TestKillBookkeepingReconcile(unittest.TestCase):
    def test_sync_clears_ghost_kill_profile(self) -> None:
        killer = type('K', (), {'killed': {}, 'forwarders': {}})()
        app = type(
            'A',
            (),
            {
                'killed_devices': {},
                '_kill_pending_profiles': set(),
                '_ics_kill_profile_macs': set(),
                '_ics_lag_gate': None,
                'killer': killer,
            },
        )()
        pk = 'AA:BB:CC:DD:EE:FF|192.168.1'
        app.killed_devices[pk] = True
        _sync_killed_devices(app)
        self.assertFalse(app.killed_devices.get(pk))

    def test_sync_keeps_live_kill_profile(self) -> None:
        killer = type('K', (), {'killed': {}, 'forwarders': {}})()
        app = type(
            'A',
            (),
            {
                'killed_devices': {},
                '_kill_pending_profiles': set(),
                '_ics_kill_profile_macs': set(),
                '_ics_lag_gate': None,
                'killer': killer,
            },
        )()
        mac = 'AA:BB:CC:DD:EE:FF'
        pk = 'AA:BB:CC:DD:EE:FF|192.168.1'
        app.killed_devices[pk] = True
        killer.killed[mac] = {'mac': mac, 'ip': '192.168.1.165'}
        killer.forwarders[mac] = _FakeForwarder(running=True)
        _sync_killed_devices(app)
        self.assertTrue(app.killed_devices.get(pk))

    def test_sync_keeps_arp_only_kill_without_forwarder(self) -> None:
        killer = type('K', (), {'killed': {}, 'forwarders': {}})()
        app = type(
            'A',
            (),
            {
                'killed_devices': {},
                '_kill_pending_profiles': set(),
                '_ics_kill_profile_macs': set(),
                '_ics_lag_gate': None,
                'killer': killer,
            },
        )()
        mac = 'AA:BB:CC:DD:EE:FF'
        pk = 'AA:BB:CC:DD:EE:FF|192.168.1'
        app.killed_devices[pk] = True
        killer.killed[mac] = {'mac': mac, 'ip': '192.168.1.165'}
        killer.forwarders[mac] = _FakeForwarder(running=False)
        _sync_killed_devices(app)
        self.assertTrue(app.killed_devices.get(pk))
