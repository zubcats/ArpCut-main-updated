"""ZubCut PC Wi-Fi link diagnostic — band + security for this machine only.

Parses ``netsh wlan show interfaces`` (no Admin required). Writes a report
under Desktop\\ZubCut Diagnostics and opens Notepad so the user can
screenshot / send it to support.
Does **not** inspect victim devices (band/security of a PS5 is not available
from ARP).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.diag_paths import DIAGNOSTICS_FOLDER_NAME, ensure_zubcut_diagnostics_dir


def _norm(text: str) -> str:
    return (text or '').replace('\r\n', '\n').replace('\r', '\n')


def band_from_channel(channel: int | None) -> str | None:
    """Best-effort band from Wi-Fi channel number when netsh omits Band."""
    if channel is None or channel <= 0:
        return None
    if channel <= 14:
        return '2.4 GHz'
    # 6 GHz preferred scanning channels are often reported as 1–233 with a Band
    # field; without Band, channels 15+ are treated as 5 GHz (common home case).
    # Channels above 177 are unusual for 5 GHz and may indicate 6 GHz numbering.
    if channel > 177:
        return '6 GHz'
    return '5 GHz'


def parse_wlan_interfaces(text: str) -> list[dict[str, Any]]:
    """Parse ``netsh wlan show interfaces`` into per-adapter dicts."""
    text = _norm(text)
    if not text.strip():
        return []
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if re.match(r'^\s*Name\s*:', line, re.I) and current:
            blocks.append('\n'.join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append('\n'.join(current))

    out: list[dict[str, Any]] = []
    for block in blocks:
        info: dict[str, Any] = {}
        for line in block.splitlines():
            # netsh uses indented "Key                   : value" lines.
            if not re.match(r'^\s+\S', line) or ':' not in line:
                continue
            key, _, val = line.partition(':')
            key_n = re.sub(r'\s+', ' ', key.strip().lower())
            val_n = val.strip()
            if not key_n:
                continue
            info[key_n] = val_n
        name = str(info.get('name') or '').strip()
        if not name:
            continue
        state = (info.get('state') or '').lower()
        ssid = info.get('ssid') or ''
        bssid = info.get('bssid') or ''
        auth = info.get('authentication') or ''
        cipher = info.get('cipher') or ''
        radio = info.get('radio type') or info.get('radio') or ''
        band = info.get('band') or ''
        signal = info.get('signal') or ''
        profile = info.get('profile') or ''
        guid = info.get('guid') or ''
        rx = info.get('receive rate (mbps)') or info.get('receive rate') or ''
        tx = info.get('transmit rate (mbps)') or info.get('transmit rate') or ''
        channel_s = info.get('channel') or ''
        channel: int | None = None
        m = re.search(r'(\d+)', channel_s)
        if m:
            try:
                channel = int(m.group(1))
            except ValueError:
                channel = None
        if not band:
            derived = band_from_channel(channel)
            band = derived or ''
        connected = state == 'connected' and bool(ssid)
        out.append(
            {
                'name': name,
                'state': info.get('state') or '',
                'connected': connected,
                'ssid': ssid,
                'bssid': bssid,
                'band': band,
                'channel': channel,
                'radio_type': radio,
                'authentication': auth,
                'cipher': cipher,
                'signal': signal,
                'profile': profile,
                'guid': guid,
                'rx_mbps': rx,
                'tx_mbps': tx,
            }
        )
    return out


def security_strength(authentication: str) -> str:
    """Return 'strong', 'weak', or 'unknown' for SUMMARY guidance."""
    a = str(authentication or '').strip().lower()
    if not a:
        return 'unknown'
    if 'wpa3' in a or 'wpa2' in a:
        return 'strong'
    if a in ('open', 'none') or 'wep' in a:
        return 'weak'
    # Legacy WPA (not WPA2/3)
    if re.search(r'\bwpa\b', a) and 'wpa2' not in a and 'wpa3' not in a:
        return 'weak'
    return 'unknown'


def _ethernet_uplink_aliases() -> list[str]:
    """Best-effort list of live Ethernet IPv4 adapter aliases (Wi-Fi link context)."""
    if not sys.platform.startswith('win'):
        return []
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform.startswith('win') else 0
    startupinfo = None
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    except Exception:
        startupinfo = None
    try:
        proc = subprocess.run(
            [
                'powershell',
                '-NoProfile',
                '-Command',
                (
                    "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | "
                    "ForEach-Object { "
                    "  $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue; "
                    "  if ($a -and $a.Status -eq 'Up' -and $a.MediaType -match '802.3|Ethernet') { "
                    "    $_.InterfaceAlias "
                    "  } "
                    "}"
                ),
            ],
            capture_output=True,
            text=True,
            errors='replace',
            timeout=25,
            shell=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        names = []
        for line in (proc.stdout or '').splitlines():
            n = line.strip()
            if n and n not in names:
                names.append(n)
        return names
    except Exception:
        return []


def format_wifi_link_report(
    adapters: list[dict[str, Any]],
    *,
    raw: str = '',
    ethernet_aliases: list[str] | None = None,
) -> str:
    lines: list[str] = []
    lines.append('========================================================================')
    lines.append(' ZubCut Wi-Fi Link (this PC only)')
    lines.append('========================================================================')
    lines.append(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append('Victim/PS5 band & security cannot be read from the LAN — PC link only.')
    lines.append('No LAN IPs are listed in this report.')
    lines.append('')
    lines.append('>>> SCREENSHOT THIS SUMMARY <<<')
    lines.append('------------------------------------------------------------------------')

    eth = [str(x) for x in (ethernet_aliases or []) if str(x).strip()]
    connected = [a for a in adapters if a.get('connected')]
    if not adapters:
        lines.append('[FAIL] No Wi-Fi interface info (netsh wlan returned nothing)')
    elif not connected:
        if eth:
            lines.append(
                '[WARN] No connected Wi-Fi link — Ethernet uplink is up: '
                + ', '.join(eth)
            )
        else:
            lines.append(
                '[WARN] No connected Wi-Fi link — Wi-Fi may be off (no Ethernet uplink detected)'
            )
        for a in adapters:
            nm = a.get('name') or '(unknown)'
            st = a.get('state') or '?'
            lines.append(f'[INFO] {nm}: state={st}')
    else:
        for a in connected:
            band = a.get('band') or '(unknown)'
            auth = a.get('authentication') or '(unknown)'
            cipher = a.get('cipher') or '(unknown)'
            ch = a.get('channel')
            ch_s = str(ch) if ch is not None else '?'
            ssid = a.get('ssid') or '(unknown)'
            radio = a.get('radio_type') or '(unknown)'
            sig = a.get('signal') or '?'
            rx = a.get('rx_mbps') or '?'
            tx = a.get('tx_mbps') or '?'
            strength = security_strength(str(auth))
            lines.append(f"[PASS] Connected: {a.get('name') or 'Wi-Fi'}")
            lines.append(f'[INFO] SSID: {ssid}')
            lines.append(f'[INFO] Band: {band} (channel {ch_s})')
            lines.append(f'[INFO] Security: {auth} / {cipher}')
            if strength == 'weak':
                lines.append(
                    '[WARN] Weak/open Wi-Fi security — prefer WPA2-Personal or WPA3-Personal'
                )
            elif strength == 'strong':
                lines.append('[PASS] Security looks like WPA2/WPA3')
            lines.append(f'[INFO] Radio: {radio}  Signal: {sig}')
            lines.append(f'[INFO] Rates: rx {rx} Mbps / tx {tx} Mbps')
            if a.get('guid'):
                lines.append(f"[INFO] Adapter GUID: {a['guid']}")
            if a.get('bssid'):
                # AP radio id — useful for band/BSS matching; not a LAN host IP.
                lines.append(f"[INFO] BSSID: {a['bssid']}")
            band_l = str(band).lower()
            if '6' in band_l and 'ghz' in band_l:
                lines.append(
                    '[WARN] PC is on 6 GHz — if the console is on 5 GHz of the same SSID, '
                    'MITM can be one-sided; prefer both on the same 5 GHz BSS when possible.'
                )
            elif '2.4' in band_l:
                lines.append('[INFO] PC is on 2.4 GHz')
            elif '5' in band_l:
                lines.append('[INFO] PC is on 5 GHz')
        if eth:
            lines.append('[INFO] Ethernet also up: ' + ', '.join(eth))

    lines.append('------------------------------------------------------------------------')
    lines.append('')
    lines.append('--- All WLAN interfaces ---')
    if not adapters:
        lines.append('  (none)')
    for a in adapters:
        lines.append(
            '  {name}: state={state} ssid={ssid} band={band} ch={ch} auth={auth} '
            'rx={rx} tx={tx} guid={guid}'.format(
                name=a.get('name') or '?',
                state=a.get('state') or '?',
                ssid=a.get('ssid') or '-',
                band=a.get('band') or '-',
                ch=a.get('channel') if a.get('channel') is not None else '-',
                auth=a.get('authentication') or '-',
                rx=a.get('rx_mbps') or '-',
                tx=a.get('tx_mbps') or '-',
                guid=(str(a.get('guid') or '-')[:48]),
            )
        )
    lines.append('')
    lines.append('--- Recommended next steps ---')
    lines.append('  Send this .txt screenshot / file to ZubCut support.')
    lines.append('  This report is the ZubCut PC Wi-Fi link only (not the console).')
    lines.append('========================================================================')
    if raw.strip():
        lines.append('')
        lines.append('--- Raw: netsh wlan show interfaces ---')
        lines.append(raw.rstrip())
        lines.append('========================================================================')
    return '\r\n'.join(lines) + '\r\n'


def _run_netsh_wlan_interfaces() -> str:
    creationflags = 0
    startupinfo = None
    if sys.platform.startswith('win'):
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        except Exception:
            startupinfo = None
    try:
        proc = subprocess.run(
            ['netsh', 'wlan', 'show', 'interfaces'],
            capture_output=True,
            text=True,
            errors='replace',
            timeout=20,
            shell=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        return (proc.stdout or '') + (proc.stderr or '')
    except Exception as exc:
        return f'(netsh failed: {exc})'


def _open_notepad(path: Path) -> None:
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


def run_wifi_link_diag(*, open_report: bool = True) -> tuple[bool, str, Path | None]:
    """
    Collect PC Wi-Fi link info, write report under Desktop\\ZubCut Diagnostics.

    Returns ``(ok, status_message, report_path)``.
    """
    if not sys.platform.startswith('win'):
        return False, 'Wi-Fi link check is Windows-only.', None
    raw = _run_netsh_wlan_interfaces()
    adapters = parse_wlan_interfaces(raw)
    eth = _ethernet_uplink_aliases()
    report = format_wifi_link_report(adapters, raw=raw, ethernet_aliases=eth)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    try:
        diag_dir = ensure_zubcut_diagnostics_dir()
        path = diag_dir / f'ZubCut-Wifi-Link-{stamp}.txt'
        path.write_text(report, encoding='utf-8', newline='\n')
    except Exception as exc:
        return False, f'Wi-Fi link check could not write report: {exc}', None
    if open_report:
        _open_notepad(path)
    folder = DIAGNOSTICS_FOLDER_NAME
    connected = [a for a in adapters if a.get('connected')]
    if connected:
        a = connected[0]
        band = a.get('band') or '?'
        auth = a.get('authentication') or '?'
        msg = (
            f'Wi-Fi link: {a.get("ssid") or "?"} on {band}, security {auth} — '
            f'report in Desktop\\{folder}\\{path.name}.'
        )
        return True, msg, path
    if adapters:
        return (
            True,
            f'Wi-Fi link: no active Wi-Fi connection — '
            f'report in Desktop\\{folder}\\{path.name}.',
            path,
        )
    return (
        False,
        f'Wi-Fi link: could not read WLAN interfaces — '
        f'see Desktop\\{folder}\\{path.name}.',
        path,
    )


def launch_wifi_link_diag() -> tuple[bool, str]:
    """Logs-button entry point (no UAC)."""
    ok, msg, _path = run_wifi_link_diag(open_report=True)
    return ok, msg
