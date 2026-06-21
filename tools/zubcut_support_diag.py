#!/usr/bin/env python3
"""
ZubCut support diagnostic — checks adapter, Npcap, settings, MITM path, and firewall.

Writes a human-readable .txt log and machine-readable .json to send to support.
Run from repo:  py tools/zubcut_support_diag.py
Optional:      py tools/zubcut_support_diag.py --victim-ip 192.168.1.165
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
        'tool_version': 1,
        'timestamp_utc': _utc_stamp(),
        'platform': sys.platform,
        'python': sys.version.split()[0],
        'admin': is_admin(),
        'cwd': os.getcwd(),
        'repo_root': str(ROOT),
        'issues': [],
        'sections': {},
        'recommendations': [],
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
        except Exception as exc:
            os_net['error'] = str(exc)
    report['sections']['os_network'] = os_net

    # --- Npcap ---
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

    # --- WinDivert (hotspot / ICS) ---
    wd_sec: dict[str, Any] = {}
    if sys.platform.startswith('win'):
        try:
            from tools.clumsy_inline import windivert_bundled_next_to_app, windivert_app_dir

            wd_sec['bundle_dir'] = windivert_app_dir()
            wd_sec['bundle_complete'] = bool(windivert_bundled_next_to_app())
        except Exception as exc:
            wd_sec['error'] = str(exc)
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
        recs.append('Right-click Run-ZubCut-Support-Diag.cmd → Run as administrator.')
    if npcap_sec.get('installed') is False:
        recs.append('Install Npcap from https://npcap.com/ (enable your Wi‑Fi adapter).')
    if iface_sec.get('saved_iface') and not iface_sec['saved_iface'].get('matches_best_live'):
        recs.append(
            f"Settings → Network: select {iface_sec.get('best_live', {}).get('label', 'the live Wi‑Fi row')} → Apply → Rescan."
        )
    if any(v.get('mitm_live_ok') is False for v in victims if isinstance(v, dict)):
        recs.append('Rescan devices; target the PS5 row whose IP pings reliably (not an old Ethernet IP).')
    if any(v.get('ping', {}).get('flaky') for v in victims if isinstance(v, dict)):
        recs.append('Lag Switch needs stable ping to PS5 — wake console, disable router client isolation if enabled.')
    recs.append('Confirm the main table "Me" row IP matches ipconfig on the adapter you use for the router.')
    report['recommendations'] = recs

    return report


def format_text_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append('=' * 72)
    lines.append(' ZubCut Support Diagnostic')
    lines.append('=' * 72)
    lines.append(f"Generated (UTC): {report.get('timestamp_utc')}")
    lines.append(f"Platform: {report.get('platform')}   Python: {report.get('python')}")
    lines.append(f"Administrator: {'yes' if report.get('admin') else 'NO'}")
    lines.append('')
    lines.append('Send this .txt file AND the matching .json to ZubCut support.')
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
        lines.append(f"  >> saved in Settings: {saved.get('label')} (matches recommended: {saved.get('matches_best_live')})")
    lines.append('')

    mitm = report.get('sections', {}).get('mitm', {})
    lines.append('--- Router / MITM ---')
    lines.append(f"  my IP: {mitm.get('my_ip')}")
    lines.append(f"  gateway: {mitm.get('gateway_ip')}  MAC: {mitm.get('gateway_mac')}")
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
    cap = report.get('sections', {}).get('capture_probe', {})
    if not cap.get('skipped'):
        lines.append(f"  sniffer test: {cap.get('sniffer_ok')}   L2 send test: {cap.get('l2_ok')}")
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
