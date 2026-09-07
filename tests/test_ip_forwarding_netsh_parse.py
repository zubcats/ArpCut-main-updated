"""IP forwarding netsh apply must parse stdout; disable sync-flips active NIC."""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def _load_killer_forwarding_helpers():
    """Exec only the netsh helpers — avoid importing scapy via networking.killer."""
    path = os.path.join(_SRC, 'networking', 'killer.py')
    with open(path, encoding='utf-8') as f:
        src = f.read()
    start = src.index('def _iface_indexes_from_netsh')
    end = src.index('def disable_ip_forwarding')
    chunk = src[start:end]
    ns: dict = {
        'sys': sys,
        'threading': __import__('threading'),
        'run_command': lambda *a, **k: SimpleNamespace(returncode=0, stdout='', stderr=''),
        'safe_daemon_target': lambda fn, *a, **k: fn,
    }
    # Minimal globals used by the extracted block.
    exec(chunk, ns)  # noqa: S102
    return ns


class TestIpForwardingNetshParse(unittest.TestCase):
    def test_indexes_parsed_from_stdout(self) -> None:
        ns = _load_killer_forwarding_helpers()
        sample = (
            '\nIdx     Met         MTU          State                Name\n'
            '---  ----------  ----------  ------------  ---------------------------\n'
            ' 12          25        1500  connected     Wi-Fi\n'
            ' 15          35        1500  connected     Ethernet\n'
        )
        idxs = ns['_iface_indexes_from_netsh'](sample)
        self.assertIn('12', idxs)
        self.assertIn('15', idxs)

    def test_apply_uses_stdout_not_repr(self) -> None:
        ns = _load_killer_forwarding_helpers()
        sample = (
            'Idx     Met         MTU          State                Name\n'
            ' 12          25        1500  connected     Wi-Fi\n'
        )
        calls = []

        def _fake_run(cmd, **_kw):
            calls.append(cmd)
            if cmd[:3] == ['netsh', 'interface', 'ipv4'] and 'show' in cmd:
                return SimpleNamespace(returncode=0, stdout=sample, stderr='')
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        set_calls = []

        def _fake_set(key, enabled):
            set_calls.append((key, enabled))
            return True

        ns['run_command'] = _fake_run
        ns['_netsh_set_iface_forwarding'] = _fake_set
        # Re-bind apply to use our fakes (it closed over names in ns).
        exec(
            'def _apply_windows_ip_forwarding_ifaces(enabled, *, priority_iface=None):\n'
            '    try:\n'
            "        show = run_command(['netsh', 'interface', 'ipv4', 'show', 'interfaces'], shell=False, timeout=6)\n"
            "        show_s = str(getattr(show, 'stdout', None) or '')\n"
            '    except Exception:\n'
            "        show_s = ''\n"
            '    for key in _priority_iface_keys(priority_iface, show_s):\n'
            '        _netsh_set_iface_forwarding(key, enabled)\n'
            '    indexes = _iface_indexes_from_netsh(show_s)\n'
            '    for idx in indexes:\n'
            '        _netsh_set_iface_forwarding(idx, enabled)\n',
            ns,
        )
        ns['_apply_windows_ip_forwarding_ifaces'](False, priority_iface='Wi-Fi')
        self.assertTrue(set_calls)
        self.assertTrue(any(c[0] in ('Wi-Fi', '12') for c in set_calls))

    def test_source_sync_flips_priority_before_worker(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        fn = src[
            src.index('def _set_windows_ip_forwarding') : src.index(
                'def _iface_forwarding_enabled_netsh'
            )
        ]
        self.assertIn('if not enabled and prio and not blocking:', fn)
        self.assertIn('_netsh_set_iface_forwarding(prio, False)', fn)

    def test_source_priority_only_never_falls_through_all_nics(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        apply = src[
            src.index('def _apply_windows_ip_forwarding_ifaces') : src.index(
                '_forwarding_priority_iface'
            )
        ]
        # SoftAP-safe: priority_only must return before all-NIC index loop.
        self.assertIn('if priority_only:', apply)
        self.assertLess(
            apply.index('if priority_only:'),
            apply.index('_iface_indexes_from_netsh'),
        )

    def test_source_is_ip_forwarding_uses_singular_show(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        helper = src[
            src.index('def _iface_forwarding_enabled_netsh') : src.index(
                'def is_ip_forwarding_enabled'
            )
        ]
        fn = src[
            src.index('def is_ip_forwarding_enabled') : src.index(
                'def enable_ip_forwarding'
            )
        ]
        self.assertIn('_iface_forwarding_enabled_netsh', fn)
        self.assertIn("'show', 'interface'", helper.replace('"', "'"))
        # Must not rely on plural listing having a Forwarding column.
        self.assertNotIn("'forwarding' in text and 'enabled' in text", fn)

    def test_iface_forwarding_enabled_parses_singular(self) -> None:
        ns = _load_killer_forwarding_helpers()
        detail = (
            'Interface Wi-Fi Parameters\n'
            'Forwarding                  : enabled\n'
            'Advertising                 : disabled\n'
        )
        self.assertTrue(ns['_iface_forwarding_enabled_netsh'].__code__.co_argcount >= 1)
        with patch.dict(ns, {
            'run_command': lambda *a, **k: SimpleNamespace(
                returncode=0, stdout=detail, stderr=''
            )
        }):
            # Re-exec just the singular helper with patched run_command.
            path = os.path.join(_SRC, 'networking', 'killer.py')
            with open(path, encoding='utf-8') as f:
                src = f.read()
            chunk = src[
                src.index('def _iface_forwarding_enabled_netsh') : src.index(
                    'def is_ip_forwarding_enabled'
                )
            ]
            local = {
                'run_command': lambda *a, **k: SimpleNamespace(
                    returncode=0, stdout=detail, stderr=''
                )
            }
            exec(chunk, local)  # noqa: S102
            self.assertTrue(local['_iface_forwarding_enabled_netsh']('12'))
            disabled = detail.replace(': enabled', ': disabled')
            local['run_command'] = lambda *a, **k: SimpleNamespace(
                returncode=0, stdout=disabled, stderr=''
            )
            exec(chunk, local)  # noqa: S102
            self.assertFalse(local['_iface_forwarding_enabled_netsh']('12'))

    def test_iface_forwarding_enabled_parses_german(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        chunk = src[
            src.index('def _iface_forwarding_enabled_netsh') : src.index(
                'def is_ip_forwarding_enabled'
            )
        ]
        detail = (
            'Schnittstelle WLAN-Parameter\n'
            'Weiterleitung               : aktiviert\n'
            'Ankündigung                 : deaktiviert\n'
        )
        local = {
            'run_command': lambda *a, **k: SimpleNamespace(
                returncode=0, stdout=detail, stderr=''
            )
        }
        exec(chunk, local)  # noqa: S102
        self.assertTrue(local['_iface_forwarding_enabled_netsh']('12'))
        local['run_command'] = lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=detail.replace(': aktiviert', ': deaktiviert'),
            stderr='',
        )
        exec(chunk, local)  # noqa: S102
        self.assertFalse(local['_iface_forwarding_enabled_netsh']('12'))


if __name__ == '__main__':
    unittest.main()
