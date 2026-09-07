from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Tuple

from constants import DOCUMENTS_PATH

_STATE_PATH = os.path.join(DOCUMENTS_PATH, 'clumsy_ics_state.json')
_CLUMSY_SETTINGS_RESTART_MARKER = 'clumsy_settings_restart.flag'
_MARKER = 'ZUBCUT_JSON:'
_NO_ICS_TOUCH = 'ZubCut does not change Windows sharing or Mobile Hotspot.'


def clumsy_settings_restart_marker_path() -> str:
    return os.path.join(DOCUMENTS_PATH, _CLUMSY_SETTINGS_RESTART_MARKER)


def mark_clumsy_settings_restart_pending() -> None:
    """Written before Settings-driven restart so startup does not clear clumsy_mode."""
    if os.name != 'nt':
        return
    try:
        os.makedirs(DOCUMENTS_PATH, exist_ok=True)
        path = clumsy_settings_restart_marker_path()
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('pending\n')
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass


def consume_clumsy_settings_restart_pending() -> bool:
    if os.path.isfile(clumsy_settings_restart_marker_path()):
        try:
            os.remove(clumsy_settings_restart_marker_path())
        except OSError:
            pass
        return True
    return False


def clumsy_settings_restart_pending() -> bool:
    """True while a Settings-driven restart has not yet finished starting."""
    try:
        return os.path.isfile(clumsy_settings_restart_marker_path())
    except OSError:
        return False


def _parse_marker_json(text: str) -> Dict[str, Any]:
    """
    Extract the last ZUBCUT_JSON payload from PowerShell output.

    Windows PowerShell may split ``Write-Output 'MARKER' + ($json)`` into two
    lines (marker only, then JSON), which would otherwise make json.loads fail
    and treat a successful ICS script as failure.
    """
    from tools.user_errors import safe_text_lines

    if text is None:
        return {}
    text = str(text)
    if not text:
        return {}
    lines = [ln.lstrip('\ufeff') for ln in safe_text_lines(text)]
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if not line.startswith(_MARKER):
            continue
        tail = line[len(_MARKER) :].strip()
        if tail:
            try:
                return json.loads(tail)
            except Exception:
                pass
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if nxt:
                try:
                    return json.loads(nxt)
                except Exception:
                    pass
        idx = text.rfind(_MARKER)
        if idx >= 0:
            blob = text[idx + len(_MARKER) :].strip()
            try:
                return json.loads(blob)
            except Exception:
                pass
        break
    return {}


def clumsy_ics_state_path() -> str:
    return _STATE_PATH


def read_clumsy_ics_state() -> Dict[str, Any]:
    try:
        with open(_STATE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def normalize_clumsy_topology(topology: str | None) -> str:
    t = (topology or '').strip().lower()
    if t in ('hotspot', 'wifi', 'wi-fi', 'wlan', 'mobile'):
        return 'hotspot'
    return 'ethernet'


def describe_clumsy_console_path() -> str:
    """Human-readable path from last leftover Clumsy state file (Settings readout)."""
    state = read_clumsy_ics_state()
    topo = str(state.get('topology') or '').strip().lower()
    up = str(state.get('upstream_name') or '').strip()
    down = str(state.get('downstream_name') or '').strip()
    uplink = str(state.get('uplink_kind') or '').strip().lower()
    if topo == 'hotspot':
        if uplink == 'ethernet' or 'ethernet' in up.lower():
            return 'Ethernet → Mobile Hotspot (PS5 on PC hotspot Wi‑Fi)'
        return 'Wi‑Fi → Mobile Hotspot (PS5 on PC hotspot Wi‑Fi)'
    if topo == 'ethernet':
        up_l = up or 'Internet'
        down_l = down or 'Ethernet to console'
        return f'{up_l} → {down_l} (PS5 on LAN cable)'
    return 'Clumzy Mode does not configure Windows sharing or hotspot'


def read_clumsy_topology() -> str:
    """Last leftover console path from the old Clumsy state file (hotspot vs ethernet)."""
    state = read_clumsy_ics_state()
    t = str(state.get('topology') or '').strip().lower()
    if t in ('hotspot', 'ethernet'):
        return t
    try:
        from tools.utils_gui import get_settings

        legacy = str(get_settings('clumsy_topology') or '').strip().lower()
        if legacy in ('hotspot', 'ethernet'):
            return normalize_clumsy_topology(legacy)
    except Exception:
        pass
    return 'hotspot'


def _clumsy_error_has_hotspot_hints(detail: str) -> bool:
    low = (detail or '').lower()
    if 'valid hotspot path for clumsy mode' in low:
        return True
    return (
        ('connect the ps5' in low or 'connect your console' in low)
        and ('mobile hotspot' in low or 'clumsy mode does' in low)
    )


def format_clumsy_ics_error(detail: str, *, topology: str | None = None) -> str:
    """User-facing hints. ZubCut does not enable or repair Windows sharing."""
    topo = normalize_clumsy_topology(topology) if topology else read_clumsy_topology()
    d = (detail or '').strip()
    lines = [d] if d else []
    low = d.lower()
    if topo == 'hotspot' and not _clumsy_error_has_hotspot_hints(d):
        lines.extend(
            [
                '',
                'Valid hotspot path for Clumsy mode:',
                '• PC has internet on Wi‑Fi or Ethernet to your router',
                '• Mobile Hotspot is ON; console on PC hotspot Wi‑Fi (not home router)',
                '• ZubCut does not enable or repair Windows Internet sharing',
                '• Run ZubCut as Administrator, then enable Clumzy Mode',
            ]
        )
    if topo == 'ethernet' and 'lan port' not in low and 'ethernet' not in low:
        lines.extend(
            [
                '',
                'For PS5 → Ethernet cable → this PC:',
                '• Plug the PS5 into a spare Ethernet port (not the port to your router)',
                '• Turn OFF Mobile Hotspot if you are using the cable',
                '• Run ZubCut as Administrator, then enable Clumzy Mode again',
            ]
        )
    if 'repair hotspot' not in low and topo not in ('hotspot', 'ethernet'):
        lines.extend(
            [
                '',
                'Enable Clumzy Mode in Settings (run as Administrator). ZubCut does not '
                'configure Windows sharing or Mobile Hotspot.',
            ]
        )
    if '0x80040201' in low or 'abonnenten' in low or 'subscribers' in low:
        if topo == 'ethernet':
            lines.extend(
                [
                    '',
                    'This Windows sharing error is often fixed by:',
                    '• Turn off Mobile hotspot (Settings → Network → Mobile hotspot)',
                    '• Network connections → your internet adapter → Properties → Sharing: '
                    'uncheck sharing, Apply, then try Clumzy Mode again',
                    '• Set both Ethernet adapters to Private network, then retry',
                ]
            )
    if 'administrator' not in low and 'admin' not in low:
        lines.extend(['', '• Run ZubCut as Administrator (right-click → Run as administrator)'])
    return '\n'.join(lines)


def purge_clumsy_stale_attack_blocks(extra_ips=None, *, for_clumsy_enable: bool = False) -> dict:
    """
    Remove leftover Kill/Dupe/Lag firewall blocks and WinDivert gate.
    Does not enable, disable, or repair Windows sharing or Mobile Hotspot.
    """
    summary: dict = {'firewall_rules_removed': 0, 'unblocked_ips': []}
    if not sys.platform.startswith('win'):
        return summary
    ips: set[str] = set()
    if extra_ips:
        for ip in extra_ips:
            s = str(ip or '').strip()
            if s:
                ips.add(s)
    try:
        import re
        import subprocess

        from tools.utils import _windows_subprocess_no_window_kwargs

        out = subprocess.check_output(
            ['arp', '-a'],
            text=True,
            errors='replace',
            timeout=15,
            **_windows_subprocess_no_window_kwargs(),
        )
        for m in re.finditer(r'\b(192\.168\.(?:137|173)\.\d{1,3})\b', out):
            ip = m.group(1)
            if not ip.endswith('.255') and ip not in ('192.168.137.1', '192.168.173.1'):
                ips.add(ip)
    except Exception:
        pass
    try:
        if for_clumsy_enable:
            from tools.pfctl import unblock_all_for, unblock_ip

            for ip in sorted(ips):
                try:
                    unblock_ip(ip)
                    unblock_all_for(ip)
                except Exception:
                    pass
        else:
            from tools.pfctl import teardown_all_zubcut_network_attacks

            summary = teardown_all_zubcut_network_attacks(extra_ips=sorted(ips))
    except Exception:
        pass
    try:
        from tools.ics_windivert_shaper import _windivert_sc_stop_and_delete

        _windivert_sc_stop_and_delete()
    except Exception:
        pass
    return summary


def prepare_pc_mobile_hotspot() -> Tuple[bool, str]:
    """Old Clumsy leftover. ZubCut never starts or configures Mobile Hotspot."""
    return True, _NO_ICS_TOUCH


def ensure_clumsy_ics_enabled(topology: str | None = None) -> Tuple[bool, str]:
    """Old Clumsy leftover. Clumzy Mode does not configure ICS or sharing."""
    return True, _NO_ICS_TOUCH


def repair_clumsy_network_sharing() -> Tuple[bool, str]:
    """Old Clumsy leftover. ZubCut never repairs Windows sharing."""
    return True, _NO_ICS_TOUCH


def ensure_wlan_autoconfig_healthy() -> Tuple[bool, str]:
    """Old Clumsy leftover. ZubCut does not start or heal WlanSvc."""
    return True, _NO_ICS_TOUCH


def maybe_ensure_wlan_autoconfig_on_startup() -> None:
    """Old Clumsy leftover. Startup must not touch WlanSvc or sharing."""
    return


def rollback_clumsy_ics() -> Tuple[bool, str]:
    return True, _NO_ICS_TOUCH


def reset_clumsy_mode_on_startup() -> None:
    """Keep Clumzy Mode across quit/relaunch.

    A marker file (and legacy clumsy_persist_across_restart) is still consumed
    after a Settings restart so the new process can take the single-instance lock.
    The checkbox itself is no longer cleared on a cold start.
    """
    if os.name != 'nt':
        return
    try:
        from tools.utils_gui import import_settings_as_dict, set_settings_many

        consume_clumsy_settings_restart_pending()
        raw = import_settings_as_dict()
        if bool(raw.get('clumsy_persist_across_restart')):
            set_settings_many({'clumsy_persist_across_restart': False})
    except Exception:
        pass


def clear_stale_softap_when_tethering_off() -> Tuple[bool, str]:
    """Old Clumsy leftover. ZubCut never strips SoftAP addresses or ICS."""
    return True, _NO_ICS_TOUCH


def maybe_repair_stale_clumsy_ics_on_startup() -> None:
    """Old Clumsy leftover. Startup must not repair ICS or clear SoftAP."""
    return
