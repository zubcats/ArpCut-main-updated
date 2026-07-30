#!/usr/bin/env python3
"""
ZubCut support diagnostic — adapter, Npcap/WinPcap, MITM, Clumsy/WinDivert, firewall.

Writes a screenshot-friendly .txt (and .json) to the Desktop by default.

Repo:
  py tools/zubcut_support_diag.py
  py tools/zubcut_support_diag.py --victim-ip 192.168.1.165

Installed app:
  ZubCut.exe --support-diag
  ZubCut.exe --support-diag --victim-ip 192.168.1.165

Or double-click: tools\\Run-ZubCut-Support-Diag.bat (elevates + opens the report).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TOOL_VERSION = 2


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _file_stamp() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M%S')


def is_admin() -> bool:
    if sys.platform.startswith('win'):
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _reg_uninstall_display_names() -> list[dict[str, str]]:
    """Installed programs that look like packet-capture stacks."""
    if not sys.platform.startswith('win'):
        return []
    out: list[dict[str, str]] = []
    try:
        import winreg
    except ImportError:
        return out
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
        ),
    ]
    needles = ('winpcap', 'npcap', 'win10pcap', 'nmap', 'wireshark')
    seen: set[str] = set()
    for hive, path in roots:
        try:
            base = winreg.OpenKey(hive, path)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(base, sub) as key:
                        name, _ = winreg.QueryValueEx(key, 'DisplayName')
                except OSError:
                    continue
                display = str(name or '').strip()
                low = display.lower()
                if not display or not any(n in low for n in needles):
                    continue
                if display in seen:
                    continue
                seen.add(display)
                out.append({'display_name': display, 'key': sub})
        finally:
            winreg.CloseKey(base)
    return out


def _winpcap_registry_present() -> dict[str, Any]:
    """Detect classic WinPcap uninstall key used by the ZubCut installer."""
    info: dict[str, Any] = {'uninstall_key_present': False, 'uninstall_string': None}
    if not sys.platform.startswith('win'):
        return info
    try:
        import winreg
    except ImportError:
        return info
    for hive, path in (
        (
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst',
        ),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst',
        ),
    ):
        try:
            with winreg.OpenKey(hive, path) as key:
                info['uninstall_key_present'] = True
                try:
                    val, _ = winreg.QueryValueEx(key, 'UninstallString')
                    info['uninstall_string'] = str(val or '') or None
                except OSError:
                    pass
                return info
        except OSError:
            continue
    return info


def _find_zubcut_install_dirs() -> list[str]:
    candidates: list[str] = []
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.dirname(sys.executable))
    for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        base = os.environ.get(env) or ''
        if not base:
            continue
        for name in ('ZubCut', 'zubcut'):
            p = os.path.join(base, name)
            if os.path.isdir(p) and p not in candidates:
                candidates.append(p)
    return candidates


def _windivert_files_on_disk() -> dict[str, Any]:
    found: list[dict[str, Any]] = []
    dirs = _find_zubcut_install_dirs()
    for base in dirs:
        wd = os.path.join(base, 'windivert')
        dll = os.path.join(wd, 'WinDivert.dll')
        sysf = os.path.join(wd, 'WinDivert64.sys')
        found.append(
            {
                'dir': wd,
                'dll': os.path.isfile(dll),
                'sys': os.path.isfile(sysf),
                'complete': os.path.isfile(dll) and os.path.isfile(sysf),
            }
        )
    return {
        'install_dirs_checked': dirs,
        'bundles': found,
        'any_complete': any(b.get('complete') for b in found),
    }


def parse_ipconfig_windows(text: str) -> list[dict[str, str]]:
    """Extract adapter name + IPv4 from Windows ipconfig output."""
    out: list[dict[str, str]] = []
    if not text:
        return out
    current_name = ''
    current_ipv4 = ''
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if 'adapter' in ln.lower() and ln.endswith(':'):
            if current_name:
                out.append({'name': current_name, 'ipv4': current_ipv4})
            current_name = re.sub(
                r'^(.*?adapter\s+)', '', ln.rstrip(':'), flags=re.I
            ).strip()
            current_ipv4 = ''
            continue
        if not current_name:
            continue
        m = re.search(r'IPv4[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})', raw, re.I)
        if m:
            current_ipv4 = m.group(1).strip()
    if current_name:
        out.append({'name': current_name, 'ipv4': current_ipv4})
    return out


def _status(ok: bool | None) -> str:
    if ok is True:
        return 'OK'
    if ok is False:
        return 'FAIL'
    return 'WARN'


def _add_issue(report: dict[str, Any], severity: str, code: str, message: str) -> None:
    report.setdefault('issues', []).append(
        {'severity': severity, 'code': code, 'message': message}
    )


def _ping_trials(ip: str, trials: int = 3) -> dict[str, Any]:
    from tools.utils import ipv4_ping_reachable

    results = []
    for _ in range(max(1, trials)):
        results.append(bool(ipv4_ping_reachable(ip)))
        time.sleep(0.15)
    ok_count = sum(1 for x in results if x)
    return {
        'ip': ip,
        'trials': results,
        'ok_count': ok_count,
        'flaky': 0 < ok_count < len(results),
        'reachable': ok_count > 0,
    }


def collect_report(
    *,
    victim_ip: str | None = None,
    victim_ips: list[str] | None = None,
    skip_capture: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        'tool': 'zubcut_support_diag',
        'tool_version': TOOL_VERSION,
        'timestamp_utc': _utc_stamp(),
        'platform': sys.platform,
        'python': sys.version.split()[0],
        'admin': is_admin(),
        'frozen': bool(getattr(sys, 'frozen', False)),
        'cwd': os.getcwd(),
        'repo_root': str(ROOT),
        'issues': [],
        'sections': {},
        'recommendations': [],
        'summary_lines': [],
    }

    # --- App / build info ---
    app_sec: dict[str, Any] = {}
    try:
        from constants import (
            APP_BUILD_COMMIT,
            APP_BUILD_TIME_ISO,
            APP_DISPLAY_NAME,
            SETTINGS_PATH,
            UPDATE_CHANNEL,
        )

        app_sec.update(
            {
                'display_name': APP_DISPLAY_NAME,
                'update_channel': UPDATE_CHANNEL,
                'build_time': APP_BUILD_TIME_ISO or None,
                'build_commit': (APP_BUILD_COMMIT or '')[:12] or None,
                'settings_path': SETTINGS_PATH,
            }
        )
    except Exception as exc:
        app_sec['import_error'] = str(exc)
        SETTINGS_PATH = None
        _add_issue(report, 'critical', 'constants_import', f'Cannot load app constants: {exc}')

    report['sections']['application'] = app_sec

    # --- Settings ---
    settings_sec: dict[str, Any] = {}
    saved_iface = ''
    nickname_last: dict[str, Any] = {}
    nicknames: dict[str, Any] = {}
    try:
        from tools.utils_gui import import_settings_as_dict

        raw = import_settings_as_dict()
        saved_iface = str(raw.get('iface') or '').strip()
        nickname_last = dict(raw.get('nickname_last_ip') or {})
        nicknames = dict(raw.get('nicknames') or {})
        settings_sec = {
            'iface_saved': saved_iface or None,
            'nickname_last_ip': nickname_last,
            'nicknames': nicknames,
            'clumsy_mode': bool(raw.get('clumsy_mode')),
            'clumsy_topology': str(raw.get('clumsy_topology') or '') or None,
            'count': raw.get('count'),
            'threads': raw.get('threads'),
        }
        if not saved_iface:
            _add_issue(report, 'warn', 'iface_not_set', 'No network adapter saved in Settings.')
    except Exception as exc:
        settings_sec['error'] = str(exc)
        _add_issue(report, 'warn', 'settings_read', f'Could not read zubcut.json: {exc}')

    report['sections']['settings'] = settings_sec

    # --- OS network (ipconfig) ---
    os_net: dict[str, Any] = {'adapters': []}
    if sys.platform.startswith('win'):
        try:
            from tools.utils import terminal

            ipcfg = terminal('ipconfig', shell=True) or ''
            os_net['adapters'] = parse_ipconfig_windows(ipcfg)
            os_net['raw_line_count'] = len(ipcfg.splitlines())
            os_net['has_ics_hotspot_137'] = any(
                str(a.get('ipv4') or '').startswith('192.168.137.')
                for a in os_net['adapters']
            )
            # Gateways from ipconfig (modem+router often shows multiple).
            # Include localized labels — FR "Passerelle par défaut" was a false "(none)".
            gws = re.findall(
                r'(?:Default Gateway|Passerelle par d[eé]faut|Standardgateway|'
                r'Puerta de enlace predeterminada|Gateway predefinito)'
                r'[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})',
                ipcfg,
                flags=re.I,
            )
            if not gws:
                gws = re.findall(
                    r'(?:gateway|passerelle)[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})',
                    ipcfg,
                    flags=re.I,
                )
            os_net['default_gateways'] = sorted(set(gws))
            if len(os_net['default_gateways']) > 1:
                _add_issue(
                    report,
                    'warn',
                    'multiple_gateways',
                    'Multiple default gateways detected (modem+router?). '
                    'Confirm ZubCut Settings uses the LAN router adapter, not the modem.',
                )
        except Exception as exc:
            os_net['error'] = str(exc)
    report['sections']['os_network'] = os_net

    # --- Npcap / WinPcap ---
    npcap_sec: dict[str, Any] = {}
    if sys.platform.startswith('win'):
        try:
            from tools.utils_gui import npcap_exists
            from constants import NPCAP_PATH

            npcap_sec['installed'] = bool(npcap_exists())
            npcap_sec['expected_path'] = NPCAP_PATH
            if not npcap_sec['installed']:
                _add_issue(
                    report,
                    'critical',
                    'npcap_missing',
                    'Npcap is not installed — Kill/Lag/Dupe MITM will not work on Windows.',
                )
        except Exception as exc:
            npcap_sec['error'] = str(exc)
        npcap_sec['winpcap'] = _winpcap_registry_present()
        npcap_sec['related_programs'] = _reg_uninstall_display_names()
        if npcap_sec['winpcap'].get('uninstall_key_present'):
            _add_issue(
                report,
                'critical',
                'winpcap_installed',
                'WinPcap is still installed — it conflicts with Npcap. Uninstall WinPcap, '
                'reboot if asked, keep/install Npcap, then retry ZubCut.',
            )
        elif any(
            'winpcap' in str(p.get('display_name') or '').lower()
            or 'win10pcap' in str(p.get('display_name') or '').lower()
            for p in npcap_sec.get('related_programs') or []
        ):
            _add_issue(
                report,
                'critical',
                'winpcap_program_listed',
                'WinPcap/Win10Pcap appears in Apps & Features — uninstall it (keep Npcap).',
            )
    else:
        npcap_sec['note'] = 'Npcap check is Windows-only; macOS/Linux use libpcap.'
    report['sections']['npcap'] = npcap_sec

    # --- Adapters (Npcap / Scapy) ---
    iface_sec: dict[str, Any] = {'adapters': [], 'saved_iface': {}, 'best_live': {}}
    saved_face = None
    try:
        from tools.utils import (
            format_iface_settings_label,
            get_iface_by_name,
            get_ifaces,
            pick_best_live_iface,
            refresh_netface_live_ip,
            resolve_settings_iface_name,
            mac_address_is_usable,
            _iface_live_ipv4,
        )
        from tools.mitm_probe import iface_is_wireless

        ifaces = list(get_ifaces())
        for iface in ifaces:
            refresh_netface_live_ip(iface)
            lip = _iface_live_ipv4(iface) or str(getattr(iface, 'ip', None) or '').strip()
            mac = str(getattr(iface, 'mac', None) or '').strip()
            ghost = mac.upper() in ('FF:FF:FF:FF:FF:FF', '00:00:00:00:00:00') or lip.startswith(
                '169.254.'
            )
            entry = {
                'label': format_iface_settings_label(iface),
                'name': iface.name,
                'guid': str(getattr(iface, 'guid', None) or '')[:80],
                'ipv4': lip or None,
                'mac': mac or None,
                'wireless': bool(iface_is_wireless(iface)),
                'ghost_or_apipa': ghost,
            }
            iface_sec['adapters'].append(entry)
            if ghost:
                _add_issue(
                    report,
                    'info',
                    'ghost_adapter',
                    f"Npcap ghost/APIPA adapter in list: {entry['label']}",
                )

        best = pick_best_live_iface()
        if best is not None:
            refresh_netface_live_ip(best)
            iface_sec['best_live'] = {
                'label': format_iface_settings_label(best),
                'name': best.name,
                'ipv4': _iface_live_ipv4(best) or getattr(best, 'ip', None),
                'wireless': bool(iface_is_wireless(best)),
            }

        resolved_name = resolve_settings_iface_name(saved_iface) if saved_iface else ''
        if saved_iface:
            saved_face = get_iface_by_name(saved_iface)
            refresh_netface_live_ip(saved_face)
            iface_sec['saved_iface'] = {
                'saved_name': saved_iface,
                'resolved_name': resolved_name or saved_iface,
                'label': format_iface_settings_label(saved_face),
                'ipv4': _iface_live_ipv4(saved_face) or getattr(saved_face, 'ip', None),
                'mac': getattr(saved_face, 'mac', None),
                'wireless': bool(iface_is_wireless(saved_face)),
                'matches_best_live': bool(
                    best is not None and saved_face.name == best.name
                ),
            }
            if best is not None and saved_face.name != best.name:
                _add_issue(
                    report,
                    'warn',
                    'iface_mismatch',
                    f"Settings adapter '{saved_iface}' is not the recommended live adapter "
                    f"('{best.name}'). Open Settings, pick {iface_sec['best_live'].get('label')}, Apply, Rescan.",
                )
            if not mac_address_is_usable(getattr(saved_face, 'mac', None)):
                _add_issue(
                    report,
                    'critical',
                    'saved_iface_bad_mac',
                    'Saved adapter has no usable MAC — pick a different Wi‑Fi/Ethernet row in Settings.',
                )

        # Cross-check ipconfig vs saved ZubCut IP
        saved_ip = str(iface_sec.get('saved_iface', {}).get('ipv4') or '').strip()
        ipconfig_ips = {
            str(a.get('ipv4') or '').strip()
            for a in os_net.get('adapters', [])
            if a.get('ipv4')
        }
        iface_sec['ipconfig_ipv4_set'] = sorted(ipconfig_ips)
        if saved_ip and saved_ip not in ipconfig_ips:
            _add_issue(
                report,
                'warn',
                'ipconfig_mismatch',
                f"ZubCut saved adapter IP {saved_ip} not found in ipconfig — wrong NIC or stale settings.",
            )
        elif saved_ip and saved_ip in ipconfig_ips:
            iface_sec['ipconfig_matches_saved'] = True

    except Exception as exc:
        iface_sec['error'] = str(exc)
        _add_issue(report, 'critical', 'iface_scan', f'Adapter scan failed: {exc}')

    report['sections']['adapters'] = iface_sec

    # --- Router / MITM prereqs ---
    mitm_sec: dict[str, Any] = {}
    try:
        from networking.killer import Killer
        from tools.utils import get_gateway_ip, get_gateway_mac, get_my_ip

        killer = Killer()
        if saved_face is not None:
            killer.iface = saved_face
        gw_ip = get_gateway_ip(killer.iface.guid)
        my_ip = get_my_ip(killer.iface.guid)
        gw_mac = get_gateway_mac(my_ip, gw_ip) if gw_ip else ''
        mitm_sec['my_ip'] = my_ip
        mitm_sec['gateway_ip'] = gw_ip
        mitm_sec['gateway_mac'] = gw_mac
        mitm_sec['gateway_ping'] = _ping_trials(gw_ip) if gw_ip else None
        try:
            from networking.killer import is_ip_forwarding_enabled

            mitm_sec['ip_forwarding_enabled'] = is_ip_forwarding_enabled()
            if mitm_sec['ip_forwarding_enabled']:
                _add_issue(
                    report,
                    'critical',
                    'ip_forwarding_on',
                    'Windows IP forwarding is ON — the PC may route PS5 traffic instead of cutting it. '
                    'Restart ZubCut as Administrator; forwarding is reset automatically on launch.',
                )
        except Exception:
            pass

        if not gw_ip or gw_ip in ('0.0.0.0', ''):
            _add_issue(report, 'critical', 'no_gateway', 'Router/gateway IP not detected.')
        if not gw_mac or str(gw_mac).upper().startswith('FF:'):
            _add_issue(
                report,
                'critical',
                'no_gateway_mac',
                'Router MAC unknown — ping the gateway, run as Administrator, check Npcap.',
            )
    except Exception as exc:
        mitm_sec['error'] = str(exc)

    report['sections']['mitm'] = mitm_sec

    # --- Victim targets (CLI + favorites) ---
    victims: list[dict[str, Any]] = []
    victim_ips_list: list[str] = []
    if victim_ips:
        victim_ips_list.extend(str(x).strip() for x in victim_ips if str(x).strip())
    if victim_ip and victim_ip.strip() not in victim_ips_list:
        victim_ips_list.insert(0, victim_ip.strip())
    for _nick, data in nickname_last.items():
        if isinstance(data, dict):
            lip = str(data.get('ip') or '').strip()
            if lip and lip not in victim_ips_list:
                victim_ips_list.append(lip)
    try:
        from tools.utils import (
            lookup_mac_from_arp_table,
            victim_endpoint_live_for_mitm,
            good_mac,
        )

        iface_ip = str(mitm_sec.get('my_ip') or '').strip()
        for ip in victim_ips_list[:8]:
            mac = lookup_mac_from_arp_table(ip, iface_ip) or ''
            nick = ''
            for k, v in nicknames.items():
                if isinstance(v, dict) and str(v.get('last_ip') or '') == ip:
                    nick = str(k)
                    break
            ping = _ping_trials(ip)
            live_ok, live_reason = victim_endpoint_live_for_mitm(ip, mac, iface_ip)
            victims.append(
                {
                    'ip': ip,
                    'nickname': nick or None,
                    'arp_mac': good_mac(mac) or None,
                    'ping': ping,
                    'mitm_live_ok': live_ok,
                    'mitm_live_reason': live_reason or None,
                }
            )
            if ping.get('flaky'):
                _add_issue(
                    report,
                    'warn',
                    'victim_ping_flaky',
                    f'{ip} ping succeeded {ping["ok_count"]}/3 — Lag Switch may fail randomly. '
                    'Wake PS5, rescan, pick the live row.',
                )
            if not live_ok and live_reason:
                _add_issue(report, 'warn', 'victim_not_live', f'{ip}: {live_reason}')
    except Exception as exc:
        victims.append({'error': str(exc)})

    report['sections']['victims'] = victims

    # --- Firewall ---
    fw_sec: dict[str, Any] = {}
    if sys.platform.startswith('win'):
        try:
            from tools.pfctl import pf_self_check

            fw_sec['accessible'] = bool(pf_self_check())
            if not fw_sec['accessible'] and report['admin']:
                _add_issue(
                    report,
                    'warn',
                    'firewall_check',
                    'Windows Firewall check failed — Dupe/Kill firewall backstop may not apply rules.',
                )
        except Exception as exc:
            fw_sec['error'] = str(exc)
    report['sections']['firewall'] = fw_sec

    # --- Clumsy / ICS / WinDivert ---
    clumsy_sec: dict[str, Any] = {
        'mode_enabled': bool(settings_sec.get('clumsy_mode')),
        'topology_setting': settings_sec.get('clumsy_topology'),
        'hotspot_137_visible': bool(os_net.get('has_ics_hotspot_137')),
    }
    wd_sec: dict[str, Any] = _windivert_files_on_disk()
    if sys.platform.startswith('win'):
        try:
            from tools.clumsy_inline import (
                windivert_bundled_next_to_app,
                windivert_app_dir,
                clumsy_bundle_offered,
                clumsy_runtime_ready,
            )
            from tools.clumsy_ics import read_clumsy_ics_state

            wd_sec['runtime_bundle_dir'] = windivert_app_dir()
            wd_sec['runtime_bundle_complete'] = bool(windivert_bundled_next_to_app())
            clumsy_sec['bundle_offered'] = bool(clumsy_bundle_offered())
            clumsy_sec['runtime_ready'] = bool(clumsy_runtime_ready())
            state = read_clumsy_ics_state() or {}
            clumsy_sec['ics_state'] = {
                'downstream_ipv4': state.get('downstream_ipv4'),
                'downstream_name': state.get('downstream_name'),
                'downstream_prefix': state.get('downstream_prefix'),
                'topology': state.get('topology') or state.get('path'),
            }
        except Exception as exc:
            wd_sec['error'] = str(exc)
            clumsy_sec['error'] = str(exc)

        if clumsy_sec.get('mode_enabled') and not wd_sec.get('any_complete') and not wd_sec.get(
            'runtime_bundle_complete'
        ):
            _add_issue(
                report,
                'critical',
                'windivert_missing',
                'Clumsy mode is ON but WinDivert.dll/sys were not found under ZubCut\\windivert. '
                'Reinstall ZubCut with "Clumsy mode" checked.',
            )
        if clumsy_sec.get('mode_enabled') and not clumsy_sec.get('hotspot_137_visible'):
            _add_issue(
                report,
                'warn',
                'no_hotspot_subnet',
                'Clumsy mode is ON but no 192.168.137.x adapter is visible. '
                'Turn Mobile Hotspot ON (or use Ethernet-console topology), wait for 192.168.137.1, rescan.',
            )

        # Live WinDivertOpen probe when we have a victim IP and admin.
        probe_ip = ''
        for ip in victim_ips_list[:8]:
            if str(ip).startswith('192.168.137.') and ip.endswith('.1') is False:
                probe_ip = ip
                break
        if not probe_ip and victim_ips_list:
            probe_ip = victim_ips_list[0]
        if not probe_ip and clumsy_sec.get('hotspot_137_visible'):
            probe_ip = '192.168.137.2'
        wd_sec['probe_ip'] = probe_ip or None
        if report['admin'] and probe_ip and (
            wd_sec.get('any_complete') or wd_sec.get('runtime_bundle_complete')
        ):
            try:
                from tools.ics_windivert_shaper import probe_windivert_for_victim

                ok, msg = probe_windivert_for_victim(probe_ip)
                wd_sec['open_probe_ok'] = bool(ok)
                wd_sec['open_probe_detail'] = msg
                if not ok:
                    _add_issue(
                        report,
                        'critical',
                        'windivert_open_failed',
                        f'WinDivert open failed for {probe_ip}: {msg}',
                    )
            except Exception as exc:
                wd_sec['open_probe_error'] = str(exc)
        elif clumsy_sec.get('mode_enabled') and not report['admin']:
            _add_issue(
                report,
                'warn',
                'windivert_probe_skipped',
                'Skipped WinDivert open probe — re-run as Administrator.',
            )

    report['sections']['clumsy'] = clumsy_sec
    report['sections']['windivert'] = wd_sec

    # --- Capture probe (Npcap sniff + forwarder) ---
    cap_sec: dict[str, Any] = {'skipped': skip_capture}
    if not skip_capture and saved_face is not None and report['admin']:
        try:
            from scapy.all import AsyncSniffer, conf
            from tools.utils import npcap_iface_tokens

            tokens = npcap_iface_tokens(saved_face)
            cap_sec['tokens_tried'] = tokens
            bpf = 'arp'
            sniff_ok = False
            sniff_err = None
            for tok in tokens[:3]:
                try:
                    sn = AsyncSniffer(iface=tok, filter=bpf, store=False, timeout=1)
                    sn.start()
                    time.sleep(0.35)
                    sn.stop()
                    sniff_ok = True
                    cap_sec['sniff_iface'] = tok
                    break
                except Exception as exc:
                    sniff_err = str(exc)
            cap_sec['sniffer_ok'] = sniff_ok
            if sniff_err and not sniff_ok:
                cap_sec['sniffer_error'] = sniff_err
                _add_issue(
                    report,
                    'warn',
                    'sniffer_failed',
                    'Npcap packet capture test failed — Kill may use ARP+firewall fallback only. '
                    'Reinstall Npcap, enable Wi‑Fi adapter in Npcap installer, run as Administrator.',
                )
            l2_ok = False
            for tok in tokens[:3]:
                try:
                    sock = conf.L2socket(iface=tok)
                    sock.close()
                    l2_ok = True
                    cap_sec['l2_iface'] = tok
                    break
                except Exception as exc:
                    cap_sec.setdefault('l2_errors', []).append(str(exc))
            cap_sec['l2_ok'] = l2_ok
            if sniff_ok and not l2_ok:
                _add_issue(
                    report,
                    'critical',
                    'l2_send_failed',
                    'Npcap can sniff but L2 send failed — ARP Kill/Lag cannot inject poison. '
                    'Reinstall Npcap (WinPcap API-compatible mode), run as Admin.',
                )
        except Exception as exc:
            cap_sec['error'] = str(exc)
    elif not report['admin']:
        cap_sec['note'] = 'Run as Administrator for Npcap capture tests.'
        _add_issue(
            report,
            'warn',
            'not_admin',
            'Not running as Administrator — some checks skipped. Re-run elevated for full report.',
        )
    report['sections']['capture_probe'] = cap_sec

    # --- Recommendations ---
    recs: list[str] = []
    if not report['admin']:
        recs.append('Re-run this diagnostic as Administrator for full capture and MITM checks.')
    if npcap_sec.get('installed') is False:
        recs.append('Install Npcap from https://npcap.com/ (enable your Wi‑Fi adapter).')
    if any(i.get('code') in ('winpcap_installed', 'winpcap_program_listed') for i in report['issues']):
        recs.append('Uninstall WinPcap/Win10Pcap completely, reboot, keep Npcap only.')
    if iface_sec.get('saved_iface') and not iface_sec['saved_iface'].get('matches_best_live'):
        recs.append(
            f"Settings → Network: select {iface_sec.get('best_live', {}).get('label', 'the live Wi‑Fi row')} → Apply → Rescan."
        )
    if any(v.get('mitm_live_ok') is False for v in victims if isinstance(v, dict)):
        recs.append('Rescan devices; target the PS5 row whose IP pings reliably (not an old Ethernet IP).')
    if any(v.get('ping', {}).get('flaky') for v in victims if isinstance(v, dict)):
        recs.append('Lag Switch needs stable ping to PS5 — wake console, disable router client isolation if enabled.')
    if report.get('sections', {}).get('mitm', {}).get('ip_forwarding_enabled'):
        recs.append(
            'Restart ZubCut as Administrator — stale IP forwarding is cleared automatically on launch.'
        )
    if clumsy_sec.get('mode_enabled') and not clumsy_sec.get('hotspot_137_visible'):
        recs.append('For Clumsy: enable Mobile Hotspot, wait for 192.168.137.1, put PS5 on the hotspot Wi‑Fi, rescan.')
    if any(i.get('code') == 'windivert_missing' for i in report['issues']):
        recs.append('Reinstall ZubCut and keep "Clumsy mode" checked so WinDivert is installed.')
    if iface_sec.get('saved_iface', {}).get('wireless') and not clumsy_sec.get('mode_enabled'):
        recs.append(
            'PC is on Wi‑Fi for home-LAN MITM — many modem/router setups block Wi‑Fi→wired PS5 cuts. '
            'Try PC Ethernet + PS5 Wi‑Fi, or Clumsy hotspot.'
        )
    recs.append('Confirm the main table "Me" row IP matches ipconfig on the adapter you use for the router.')
    report['recommendations'] = recs
    report['summary_lines'] = _build_summary_lines(report)
    return report


def _build_summary_lines(report: dict[str, Any]) -> list[str]:
    """Short PASS/FAIL lines for screenshots (also stored in report JSON)."""
    lines: list[str] = []
    sec = report.get('sections') or {}
    admin = bool(report.get('admin'))
    lines.append(f"[{'PASS' if admin else 'FAIL'}] Running as Administrator")
    npcap = sec.get('npcap') or {}
    if 'installed' in npcap:
        lines.append(f"[{'PASS' if npcap.get('installed') else 'FAIL'}] Npcap installed")
    winpcap = (npcap.get('winpcap') or {}).get('uninstall_key_present')
    related = npcap.get('related_programs') or []
    has_wp = bool(winpcap) or any(
        'winpcap' in str(p.get('display_name') or '').lower()
        or 'win10pcap' in str(p.get('display_name') or '').lower()
        for p in related
    )
    lines.append(f"[{'FAIL' if has_wp else 'PASS'}] WinPcap/Win10Pcap absent")
    mitm = sec.get('mitm') or {}
    gw_ok = bool(mitm.get('gateway_ip')) and bool(mitm.get('gateway_mac')) and not str(
        mitm.get('gateway_mac') or ''
    ).upper().startswith('FF:')
    lines.append(f"[{'PASS' if gw_ok else 'FAIL'}] Gateway IP+MAC known")
    if 'ip_forwarding_enabled' in mitm:
        lines.append(
            f"[{'FAIL' if mitm.get('ip_forwarding_enabled') else 'PASS'}] IP forwarding off"
        )
    cap = sec.get('capture_probe') or {}
    if not cap.get('skipped') and admin:
        lines.append(f"[{'PASS' if cap.get('sniffer_ok') else 'FAIL'}] Npcap sniffer")
        lines.append(f"[{'PASS' if cap.get('l2_ok') else 'FAIL'}] Npcap L2 send")
    clumsy = sec.get('clumsy') or {}
    lines.append(f"[{'ON' if clumsy.get('mode_enabled') else 'OFF'}] Clumsy mode setting")
    lines.append(
        f"[{'PASS' if clumsy.get('hotspot_137_visible') else 'WARN'}] Hotspot 192.168.137.x visible"
    )
    wd = sec.get('windivert') or {}
    wd_ok = bool(wd.get('any_complete') or wd.get('runtime_bundle_complete'))
    lines.append(f"[{'PASS' if wd_ok else 'WARN'}] WinDivert bundle on disk")
    if 'open_probe_ok' in wd:
        lines.append(f"[{'PASS' if wd.get('open_probe_ok') else 'FAIL'}] WinDivert open probe")
    victims = sec.get('victims') or []
    live_victims = [v for v in victims if isinstance(v, dict) and v.get('mitm_live_ok')]
    if victims:
        lines.append(
            f"[{'PASS' if live_victims else 'WARN'}] Victim/PS5 live for MITM "
            f"({len(live_victims)}/{len([v for v in victims if isinstance(v, dict) and not v.get('error')])})"
        )
    crit = sum(1 for i in report.get('issues') or [] if i.get('severity') == 'critical')
    warn = sum(1 for i in report.get('issues') or [] if i.get('severity') == 'warn')
    lines.append(f"[INFO] Issues: {crit} critical, {warn} warnings")
    return lines


def format_text_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append('=' * 72)
    lines.append(' ZubCut Support Diagnostic')
    lines.append(f" tool_version={report.get('tool_version')}   frozen={report.get('frozen')}")
    lines.append('=' * 72)
    lines.append(f"Generated (UTC): {report.get('timestamp_utc')}")
    lines.append(f"Platform: {report.get('platform')}   Python: {report.get('python')}")
    lines.append(f"Administrator: {'yes' if report.get('admin') else 'NO — re-run elevated'}")
    lines.append('')
    lines.append('>>> SCREENSHOT THIS SUMMARY (and Issues / Recommended fixes) <<<')
    lines.append('-' * 72)
    for row in report.get('summary_lines') or _build_summary_lines(report):
        lines.append(f"  {row}")
    lines.append('-' * 72)
    lines.append('')
    lines.append('Also send the matching .json file if asked.')
    lines.append('')

    issues = report.get('issues') or []
    if issues:
        lines.append('--- Issues found ---')
        for item in issues:
            lines.append(f"  [{item.get('severity')}] {item.get('code')}: {item.get('message')}")
        lines.append('')

    recs = report.get('recommendations') or []
    if recs:
        lines.append('--- Recommended fixes ---')
        for i, r in enumerate(recs, 1):
            lines.append(f"  {i}. {r}")
        lines.append('')

    app = report.get('sections', {}).get('application', {})
    if app:
        lines.append('--- Application ---')
        for k in ('display_name', 'update_channel', 'build_time', 'build_commit', 'settings_path'):
            if app.get(k):
                lines.append(f"  {k}: {app[k]}")
        lines.append('')

    settings = report.get('sections', {}).get('settings', {})
    lines.append('--- ZubCut settings ---')
    lines.append(f"  saved adapter: {settings.get('iface_saved') or '(not set)'}")
    lines.append(f"  clumsy_mode: {settings.get('clumsy_mode')}")
    lines.append(f"  clumsy_topology: {settings.get('clumsy_topology')}")
    lines.append(f"  device count / threads: {settings.get('count')} / {settings.get('threads')}")
    if settings.get('nicknames'):
        lines.append(f"  nicknames: {json.dumps(settings.get('nicknames'), ensure_ascii=False)}")
    if settings.get('nickname_last_ip'):
        lines.append(
            f"  last known IPs: {json.dumps(settings.get('nickname_last_ip'), ensure_ascii=False)}"
        )
    lines.append('')

    os_net = report.get('sections', {}).get('os_network', {})
    lines.append('--- Windows ipconfig (live adapters) ---')
    for ad in os_net.get('adapters') or []:
        lines.append(f"  {ad.get('name')}: IPv4 {ad.get('ipv4') or '(none)'}")
    if os_net.get('default_gateways'):
        lines.append(f"  default gateways: {', '.join(os_net['default_gateways'])}")
    lines.append(f"  hotspot 192.168.137.x visible: {os_net.get('has_ics_hotspot_137')}")
    lines.append('')

    iface = report.get('sections', {}).get('adapters', {})
    lines.append('--- Npcap adapters (ZubCut Settings dropdown) ---')
    for ad in iface.get('adapters') or []:
        flag = ' [ghost/APIPA — do not pick]' if ad.get('ghost_or_apipa') else ''
        wl = ' Wi‑Fi' if ad.get('wireless') else ''
        lines.append(f"  {ad.get('label')}{wl}{flag}")
    best = iface.get('best_live') or {}
    if best:
        lines.append(f"  >> recommended: {best.get('label')}")
    saved = iface.get('saved_iface') or {}
    if saved:
        lines.append(
            f"  >> saved in Settings: {saved.get('label')} "
            f"(matches recommended: {saved.get('matches_best_live')})"
        )
    lines.append('')

    mitm = report.get('sections', {}).get('mitm', {})
    lines.append('--- Router / MITM ---')
    lines.append(f"  my IP: {mitm.get('my_ip')}")
    lines.append(f"  gateway: {mitm.get('gateway_ip')}  MAC: {mitm.get('gateway_mac')}")
    if 'ip_forwarding_enabled' in mitm:
        lines.append(
            f"  IP forwarding: {'ON (blocks MITM cut)' if mitm.get('ip_forwarding_enabled') else 'off'}"
        )
    gp = mitm.get('gateway_ping') or {}
    if gp:
        lines.append(f"  gateway ping: {gp.get('ok_count')}/{len(gp.get('trials') or [])} ok")
    lines.append('')

    victims = report.get('sections', {}).get('victims') or []
    if victims:
        lines.append('--- Victim / PS5 checks ---')
        for v in victims:
            if v.get('error'):
                lines.append(f"  error: {v['error']}")
                continue
            ping = v.get('ping') or {}
            lines.append(
                f"  {v.get('ip')}  nick={v.get('nickname')}  arp={v.get('arp_mac')}  "
                f"ping={ping.get('ok_count')}/{len(ping.get('trials') or [])}  "
                f"mitm_ok={v.get('mitm_live_ok')}"
            )
            if v.get('mitm_live_reason'):
                lines.append(f"      reason: {v['mitm_live_reason']}")
        lines.append('')

    npcap = report.get('sections', {}).get('npcap', {})
    lines.append(f"--- Npcap installed: {npcap.get('installed')} ---")
    wp = npcap.get('winpcap') or {}
    lines.append(f"  WinPcap uninstall key: {wp.get('uninstall_key_present')}")
    for prog in npcap.get('related_programs') or []:
        lines.append(f"  related program: {prog.get('display_name')}")
    cap = report.get('sections', {}).get('capture_probe', {})
    if not cap.get('skipped'):
        lines.append(f"  sniffer test: {cap.get('sniffer_ok')}   L2 send test: {cap.get('l2_ok')}")
    lines.append('')

    clumsy = report.get('sections', {}).get('clumsy', {})
    lines.append('--- Clumsy / Hotspot ---')
    lines.append(f"  mode enabled: {clumsy.get('mode_enabled')}")
    lines.append(f"  topology setting: {clumsy.get('topology_setting')}")
    lines.append(f"  hotspot 137 visible: {clumsy.get('hotspot_137_visible')}")
    lines.append(f"  runtime ready: {clumsy.get('runtime_ready')}")
    ics = clumsy.get('ics_state') or {}
    if ics:
        lines.append(
            f"  ics state: down={ics.get('downstream_ipv4')} "
            f"name={ics.get('downstream_name')} topo={ics.get('topology')}"
        )
    lines.append('')

    wd = report.get('sections', {}).get('windivert', {})
    lines.append('--- WinDivert ---')
    lines.append(f"  any bundle complete: {wd.get('any_complete') or wd.get('runtime_bundle_complete')}")
    for b in wd.get('bundles') or []:
        lines.append(
            f"  {b.get('dir')}: dll={b.get('dll')} sys={b.get('sys')} complete={b.get('complete')}"
        )
    if wd.get('probe_ip'):
        lines.append(f"  open probe IP: {wd.get('probe_ip')}")
    if 'open_probe_ok' in wd:
        lines.append(f"  open probe: {wd.get('open_probe_ok')} — {wd.get('open_probe_detail')}")
    if wd.get('open_probe_error'):
        lines.append(f"  open probe error: {wd.get('open_probe_error')}")
    lines.append('')

    lines.append('=' * 72)
    return '\n'.join(lines)


def default_out_dir() -> Path:
    desktop = Path.home() / 'Desktop'
    if desktop.is_dir():
        return desktop
    docs = Path.home() / 'Documents'
    return docs if docs.is_dir() else Path.home()


def write_reports(report: dict[str, Any], out_dir: Path, stem: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f'{stem}.txt'
    json_path = out_dir / f'{stem}.json'
    txt_path.write_text(format_text_report(report), encoding='utf-8')
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return txt_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='ZubCut support diagnostic')
    parser.add_argument(
        '--victim-ip',
        action='append',
        dest='victim_ips',
        metavar='IP',
        help='Extra victim IP to ping/check (repeatable)',
    )
    parser.add_argument(
        '--out-dir',
        type=Path,
        default=None,
        help='Output folder (default: Desktop)',
    )
    parser.add_argument(
        '--skip-capture',
        action='store_true',
        help='Skip Npcap sniffer/L2 probe',
    )
    parser.add_argument('--quiet', action='store_true', help='Less console output')
    args = parser.parse_args(argv)

    victim_list = args.victim_ips or []
    report = collect_report(victim_ips=victim_list, skip_capture=args.skip_capture)
    out_dir = args.out_dir or default_out_dir()
    stem = f'ZubCut-Support-Diag-{_file_stamp()}'
    txt_path, json_path = write_reports(report, out_dir, stem)

    if not args.quiet:
        print(format_text_report(report))
        print(f'\nSaved:\n  {txt_path}\n  {json_path}')
    else:
        print(txt_path)
        print(json_path)

    critical = sum(1 for i in report.get('issues', []) if i.get('severity') == 'critical')
    return 1 if critical else 0


if __name__ == '__main__':
    raise SystemExit(main())
