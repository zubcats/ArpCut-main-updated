"""Capture stack diagnostic (Logs → Capture stack).

Probes Npcap sniffer + L2 socket on the Settings adapter using this app's
Scapy/Npcap stack. Runs in-process (Admin required) — not a separate .ps1.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _is_admin() -> bool:
    if not sys.platform.startswith('win'):
        return False
    try:
        from tools.utils_gui import is_admin

        return bool(is_admin())
    except Exception:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False


def _saved_iface_name() -> str:
    try:
        from tools.utils_gui import get_settings

        return str(get_settings('iface', '') or '').strip()
    except Exception:
        return ''


def probe_capture_stack(
    *,
    iface=None,
    admin: bool | None = None,
) -> dict[str, Any]:
    """
    Run sniffer + L2 open probes.

    Returns a dict with sniffer_ok, l2_ok, tokens_tried, errors, etc.
    """
    if admin is None:
        admin = _is_admin()
    out: dict[str, Any] = {
        'admin': bool(admin),
        'skipped': False,
        'sniffer_ok': False,
        'l2_ok': False,
        'tokens_tried': [],
        'iface_name': '',
        'iface_label': '',
    }
    if not sys.platform.startswith('win'):
        out['skipped'] = True
        out['note'] = 'Windows-only'
        return out
    if not admin:
        out['skipped'] = True
        out['note'] = 'Run ZubCut as Administrator for Npcap capture tests.'
        return out

    saved = _saved_iface_name()
    face = iface
    if face is None and saved:
        try:
            from tools.utils import get_iface_by_name, refresh_netface_live_ip

            face = get_iface_by_name(saved)
            if face is not None:
                refresh_netface_live_ip(face)
        except Exception as exc:
            out['iface_error'] = str(exc)
            face = None
    if face is None:
        out['skipped'] = True
        out['note'] = 'No Settings adapter — pick Wi-Fi/Ethernet in Settings → Apply.'
        out['saved_iface'] = saved or '(not set)'
        return out

    out['iface_name'] = str(getattr(face, 'name', '') or saved or '')
    out['iface_label'] = str(getattr(face, 'description', '') or out['iface_name'])
    out['saved_iface'] = saved or out['iface_name']

    try:
        from scapy.all import AsyncSniffer, conf
        from tools.utils import npcap_iface_tokens
    except Exception as exc:
        out['error'] = f'Scapy/Npcap not available: {exc}'
        return out

    tokens = npcap_iface_tokens(face)
    out['tokens_tried'] = list(tokens)
    sniff_err = None
    for tok in tokens[:3]:
        try:
            sn = AsyncSniffer(iface=tok, filter='arp', store=False, timeout=1)
            sn.start()
            time.sleep(0.35)
            sn.stop()
            out['sniffer_ok'] = True
            out['sniff_iface'] = tok
            break
        except Exception as exc:
            sniff_err = str(exc)
    if sniff_err and not out['sniffer_ok']:
        out['sniffer_error'] = sniff_err

    l2_errors: list[str] = []
    for tok in tokens[:3]:
        try:
            sock = conf.L2socket(iface=tok)
            sock.close()
            out['l2_ok'] = True
            out['l2_iface'] = tok
            break
        except Exception as exc:
            l2_errors.append(str(exc))
    if l2_errors and not out['l2_ok']:
        out['l2_errors'] = l2_errors
    return out


def format_capture_stack_report(probe: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append('========================================================================')
    lines.append(' ZubCut Capture Stack Diagnostic')
    lines.append('========================================================================')
    lines.append(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append('Probes Npcap sniffer + L2 send socket on the Settings adapter.')
    lines.append('No LAN IPs are listed in this report.')
    lines.append('')
    lines.append('>>> SCREENSHOT THIS SUMMARY <<<')
    lines.append('------------------------------------------------------------------------')
    admin = bool(probe.get('admin'))
    lines.append(f"[{'PASS' if admin else 'FAIL'}] Running as Administrator")
    saved = str(probe.get('saved_iface') or '(not set)')
    label = str(probe.get('iface_label') or probe.get('iface_name') or saved)
    if probe.get('skipped'):
        note = str(probe.get('note') or 'skipped')
        lines.append(f'[WARN] Capture probe skipped: {note}')
        lines.append(f'[INFO] Settings adapter: {saved}')
    else:
        lines.append(f'[INFO] Settings adapter: {label}')
        sniff_ok = bool(probe.get('sniffer_ok'))
        l2_ok = bool(probe.get('l2_ok'))
        lines.append(f"[{'PASS' if sniff_ok else 'FAIL'}] Npcap sniffer (ARP filter)")
        lines.append(f"[{'PASS' if l2_ok else 'FAIL'}] Npcap L2 send socket")
        if sniff_ok and probe.get('sniff_iface'):
            lines.append(f"[INFO] Sniff bound: {probe['sniff_iface']}")
        if l2_ok and probe.get('l2_iface'):
            lines.append(f"[INFO] L2 bound: {probe['l2_iface']}")
        if not sniff_ok and probe.get('sniffer_error'):
            lines.append(f"[INFO] Sniffer error: {probe['sniffer_error']}")
        if sniff_ok and not l2_ok:
            lines.append(
                '[WARN] Sniff works but L2 send failed — ARP Kill/Lag cannot inject poison'
            )
        if probe.get('error'):
            lines.append(f"[FAIL] {probe['error']}")
    lines.append('------------------------------------------------------------------------')
    lines.append('')
    lines.append('--- Tokens tried ---')
    tokens = probe.get('tokens_tried') or []
    if not tokens:
        lines.append('  (none)')
    for t in tokens:
        lines.append(f'  {t}')
    lines.append('')
    lines.append('--- Recommended next steps ---')
    if not admin:
        lines.append('  1. Restart ZubCut as Administrator, then run Capture stack again.')
    if probe.get('skipped') and 'No Settings adapter' in str(probe.get('note') or ''):
        lines.append('  2. Settings → pick the connected Wi-Fi/Ethernet row → Apply → Rescan.')
    if not probe.get('skipped') and not probe.get('sniffer_ok'):
        lines.append(
            '  3. Reinstall Npcap (enable Wi-Fi adapter), remove WinPcap/Win10Pcap, reboot.'
        )
    if probe.get('sniffer_ok') and not probe.get('l2_ok'):
        lines.append(
            '  4. Reinstall Npcap with WinPcap API-compatible mode, run ZubCut as Admin.'
        )
    lines.append('  Send this .txt screenshot / file to ZubCut support.')
    lines.append('========================================================================')
    return '\r\n'.join(lines) + '\r\n'


def _open_report(path: Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    except Exception:
        pass
    try:
        subprocess.Popen(
            ['notepad.exe', str(path)],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def run_capture_stack_diag(*, open_report: bool = True) -> tuple[bool, str, Path | None]:
    """Write report under Desktop\\ZubCut Diagnostics; optionally open Notepad."""
    if not sys.platform.startswith('win'):
        return False, 'Capture stack is Windows-only.', None
    from tools.diag_paths import ensure_zubcut_diagnostics_dir

    probe = probe_capture_stack()
    text = format_capture_stack_report(probe)
    diag = ensure_zubcut_diagnostics_dir()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    path = diag / f'ZubCut-Capture-Stack-{stamp}.txt'
    path.write_text(text, encoding='utf-8', newline='\r\n')
    if open_report:
        _open_report(path)
    ok = (not probe.get('skipped')) and bool(probe.get('sniffer_ok')) and bool(
        probe.get('l2_ok')
    )
    if probe.get('skipped'):
        msg = (
            f'Capture stack report saved ({probe.get("note")}) — '
            f'Desktop\\ZubCut Diagnostics\\{path.name}'
        )
        return False, msg, path
    if ok:
        msg = (
            f'Capture stack PASS — Desktop\\ZubCut Diagnostics\\{path.name}'
        )
        return True, msg, path
    msg = (
        f'Capture stack found issues — screenshot SUMMARY in '
        f'Desktop\\ZubCut Diagnostics\\{path.name}'
    )
    return False, msg, path


def launch_capture_stack_diag() -> tuple[bool, str]:
    """Logs-button entry point."""
    ok, msg, _path = run_capture_stack_diag(open_report=True)
    return ok, msg
