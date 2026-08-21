"""LAN readiness checks for first-run clarity (never on Kill hot path).

PC checks (on open): Admin / Npcap / WinPcap leftovers / iface / forwarding /
HVCI / WinDivert bundle / routes / gateway MAC+subnet / Wi‑Fi WPA3·MLO.
Device-path checks: MAC / subnet / cached Wi‑Fi policy — once per IP per scan.

Does not auto-enable Clumsy mode or change impairment settings.
"""
from __future__ import annotations

import ipaddress
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class ReadinessFinding:
    """One readiness line for UI / logs."""

    level: str  # 'ok' | 'warn' | 'fail'
    message: str
    code: str = ''  # ZC-* when applicable

    def format_line(self) -> str:
        prefix = f'{self.code}: ' if self.code else ''
        return f'{prefix}{self.message}'


_VIRTUAL_IFACE_NEEDLES = (
    'vpn',
    'wintun',
    'wireguard',
    'tap-windows',
    'tap0901',
    'tap adapter',
    'nordlynx',
    'proton',
    'mullvad',
    'openvpn',
    'fortinet',
    'anyconnect',
    'globalprotect',
    'hyper-v',
    'vethernet',
    'default switch',
    'vmware',
    'virtualbox',
    'vboxnet',
    'tailscale',
    'zerotier',
    'hamachi',
    'wsl',
    'docker',
)


def iface_looks_virtual(name: str = '', guid: str = '') -> bool:
    blob = f'{name} {guid}'.lower()
    return any(n in blob for n in _VIRTUAL_IFACE_NEEDLES)


def ipv4_same_subnet(a: str, b: str, prefix_len: int = 24) -> bool:
    """True when both are IPv4 and share the same network prefix."""
    try:
        na = ipaddress.ip_network(f'{str(a).strip()}/{int(prefix_len)}', strict=False)
        ib = ipaddress.ip_address(str(b).strip())
        return ib in na
    except Exception:
        return False


def hvci_memory_integrity_enabled() -> Optional[bool]:
    """True/False when registry readable; None if unknown / non-Windows."""
    if not sys.platform.startswith('win'):
        return None
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity',
            0,
            winreg.KEY_READ,
        )
        try:
            val, _ = winreg.QueryValueEx(key, 'Enabled')
            return int(val or 0) != 0
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None


def ip_forwarding_registry_on() -> bool:
    """Cheap registry-only forwarding probe (no netsh)."""
    if not sys.platform.startswith('win'):
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters',
            0,
            winreg.KEY_READ,
        )
        try:
            val, _ = winreg.QueryValueEx(key, 'IPEnableRouter')
            return int(val or 0) != 0
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def count_default_routes_ipv4() -> Optional[int]:
    """Count active IPv4 default routes; None if probe fails."""
    if not sys.platform.startswith('win'):
        return None
    try:
        from tools.utils import run_command

        proc = run_command(
            [
                'powershell',
                '-NoProfile',
                '-Command',
                "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |"
                ' Measure-Object).Count',
            ],
            shell=False,
            timeout=4,
        )
        text = str(getattr(proc, 'stdout', None) or '').strip()
        if text.isdigit():
            return int(text)
    except Exception:
        return None
    return None


def winpcap_leftover_present() -> bool:
    """True when a WinPcap/Win10Pcap uninstall key is still registered (conflicts with Npcap)."""
    if not sys.platform.startswith('win'):
        return False
    try:
        import winreg

        for path in (
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst',
            r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst',
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Win10Pcap',
            r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Win10Pcap',
        ):
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
                winreg.CloseKey(key)
                return True
            except OSError:
                continue
    except Exception:
        return False
    return False


def probe_wifi_link_hint_codes() -> list[str]:
    """Cheap netsh Wi‑Fi hints (WPA3 / Wi‑Fi 7 MLO). Empty when not on Wi‑Fi or probe fails."""
    if not sys.platform.startswith('win'):
        return []
    hints: list[str] = []
    try:
        from tools.utils import run_command
        from tools.support_wifi_link_diag import (
            parse_wlan_interfaces,
            security_zubcut_class,
        )

        proc = run_command(
            ['netsh', 'wlan', 'show', 'interfaces'],
            shell=False,
            timeout=5,
        )
        raw = str(getattr(proc, 'stdout', None) or '')
        for a in parse_wlan_interfaces(raw):
            if not bool(a.get('connected')):
                continue
            auth = str(a.get('authentication') or '')
            if security_zubcut_class(auth) == 'wpa3':
                hints.append('ZC-WPA3')
            radio = str(a.get('radio_type') or '').lower()
            band = str(a.get('band') or '').lower()
            if (
                '802.11be' in radio
                or 'wi-fi 7' in radio
                or 'wifi 7' in radio
                or 'mlo' in radio
                or 'multi-link' in radio
                or ('6' in band and 'ghz' in band)
            ):
                hints.append('ZC-MLO')
    except Exception:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for h in hints:
        if h not in seen:
            seen.add(h)
            ordered.append(h)
    return ordered


def _append_wifi_hint_findings(
    findings: list[ReadinessFinding], wifi_link_hints: Optional[Iterable[str]]
) -> None:
    for code in list(wifi_link_hints or []):
        c = str(code or '').strip().upper()
        if c == 'ZC-WPA3':
            findings.append(
                ReadinessFinding(
                    level='warn',
                    code='ZC-WPA3',
                    message=(
                        'WPA3 Wi‑Fi often blocks ARP MITM — set the SSID to WPA2-Personal for LAN Kill.'
                    ),
                )
            )
        elif c == 'ZC-MLO':
            findings.append(
                ReadinessFinding(
                    level='warn',
                    code='ZC-MLO',
                    message=(
                        'Wi‑Fi 7 MLO can break ARP MITM — disable multi-link on the router '
                        'or use Ethernet.'
                    ),
                )
            )
        elif c == 'ZC-ISOLATION':
            findings.append(
                ReadinessFinding(
                    level='warn',
                    code='ZC-ISOLATION',
                    message=(
                        'AP/client isolation (guest Wi‑Fi) can block ARP MITM — '
                        'use the main LAN SSID or Ethernet.'
                    ),
                )
            )


def collect_pc_readiness(
    *,
    is_admin: bool,
    iface_name: str = '',
    iface_guid: str = '',
    iface_ip: str = '',
    router_ip: str = '',
    router_mac: str = '',
    wifi_link_hints: Optional[Iterable[str]] = None,
    probe_wifi: bool = True,
) -> list[ReadinessFinding]:
    """PC-only checks (no victim). Safe to run in a background thread.

    Covers the high-signal Quick-check failure modes that matter on open:
    Admin/Npcap/iface/forwarding/HVCI/routes, plus WinPcap leftovers, WinDivert
    bundle gaps, gateway MAC, PC↔gateway subnet, and this PC's Wi‑Fi WPA3/MLO.
    """
    findings: list[ReadinessFinding] = []
    if not sys.platform.startswith('win'):
        return findings

    try:
        from tools.utils_gui import (
            ensure_npcap_service_running,
            npcap_admin_only_enabled,
            npcap_exists,
        )
    except Exception:
        ensure_npcap_service_running = None  # type: ignore
        npcap_admin_only_enabled = None  # type: ignore
        npcap_exists = None  # type: ignore

    if not is_admin:
        findings.append(
            ReadinessFinding(
                level='fail',
                code='ZC-ADMIN',
                message='Administrator rights required — relaunch ZubCut elevated (UAC).',
            )
        )

    npcap_ok = True
    if callable(npcap_exists):
        try:
            npcap_ok = bool(npcap_exists())
        except Exception:
            npcap_ok = True
    if not npcap_ok:
        findings.append(
            ReadinessFinding(
                level='fail',
                code='ZC-NPCAP',
                message='Npcap missing or not loadable — install Npcap (WinPcap API-compatible mode).',
            )
        )
    else:
        admin_only = False
        if callable(npcap_admin_only_enabled):
            try:
                admin_only = bool(npcap_admin_only_enabled())
            except Exception:
                admin_only = False
        if admin_only and not is_admin:
            findings.append(
                ReadinessFinding(
                    level='fail',
                    code='ZC-NPCAP-ADMIN',
                    message=(
                        'Npcap AdminOnly is ON — run ZubCut as Administrator, '
                        'or reinstall Npcap without AdminOnly.'
                    ),
                )
            )
        svc_ok = True
        if callable(ensure_npcap_service_running):
            try:
                # Query/start best-effort; does not block Kill path (background only).
                svc_ok = bool(ensure_npcap_service_running())
            except Exception:
                svc_ok = True
        if not svc_ok:
            findings.append(
                ReadinessFinding(
                    level='fail',
                    code='ZC-NPCAP-SVC',
                    message='Npcap driver service is not running — reboot or reinstall Npcap.',
                )
            )

    if winpcap_leftover_present():
        findings.append(
            ReadinessFinding(
                level='fail',
                code='ZC-WINPCAP',
                message=(
                    'WinPcap/Win10Pcap is still installed — uninstall it, reboot, keep Npcap only.'
                ),
            )
        )

    name = str(iface_name or '').strip()
    ip = str(iface_ip or '').strip()
    if ip in ('0.0.0.0', '127.0.0.1') or ip.startswith('169.254.'):
        ip = ''
    if not name or name == 'NULL':
        findings.append(
            ReadinessFinding(
                level='fail',
                code='ZC-IFACE',
                message='Selected adapter is missing or has no usable IPv4 — pick a live NIC in Settings.',
            )
        )
    else:
        if not ip:
            findings.append(
                ReadinessFinding(
                    level='fail',
                    code='ZC-IFACE',
                    message='Selected adapter has no usable IPv4 (APIPA/missing) — pick a live NIC in Settings.',
                )
            )
        if iface_looks_virtual(name, str(iface_guid or '')):
            findings.append(
                ReadinessFinding(
                    level='warn',
                    code='ZC-ROUTE',
                    message=(
                        f'Selected adapter looks like VPN/virtual ({name}) — '
                        'LAN Kill usually fails. Pick your real LAN/Wi‑Fi NIC in Settings.'
                    ),
                )
            )

    if ip_forwarding_registry_on():
        findings.append(
            ReadinessFinding(
                level='warn',
                code='ZC-FWD',
                message=(
                    'Windows IP forwarding is ON — Kill may lag instead of full cut. '
                    'Relaunch as Admin so ZubCut can turn it off.'
                ),
            )
        )

    hvci = hvci_memory_integrity_enabled()
    if hvci is True:
        findings.append(
            ReadinessFinding(
                level='warn',
                code='ZC-WD-HVCI',
                message=(
                    'Memory Integrity / HVCI is ON — WinDivert (Clumsy/hotspot) may fail. '
                    'LAN ARP Kill is unaffected.'
                ),
            )
        )

    try:
        from tools.clumsy_inline import (
            clumsy_bundle_incomplete,
            clumsy_mode_enabled,
            windivert_bundle_complete,
        )

        # Avoid false ZC-WD in source/dev runs: clumsy_bundle_offered() is True
        # whenever not frozen, even with no windivert folder beside cwd.
        if clumsy_mode_enabled() and not windivert_bundle_complete():
            findings.append(
                ReadinessFinding(
                    level='warn',
                    code='ZC-WD',
                    message=(
                        'Clumsy mode is ON but WinDivert is unavailable — hotspot cut '
                        'needs Admin + a complete WinDivert bundle.'
                    ),
                )
            )
        elif getattr(sys, 'frozen', False) and clumsy_bundle_incomplete():
            findings.append(
                ReadinessFinding(
                    level='warn',
                    code='ZC-WD',
                    message=(
                        'WinDivert bundle missing from this install — Clumsy/hotspot cut '
                        'will fail. Repair/reinstall ZubCut (LAN ARP Kill still works).'
                    ),
                )
            )
    except Exception:
        pass

    routes = count_default_routes_ipv4()
    if routes is not None and routes > 1:
        findings.append(
            ReadinessFinding(
                level='warn',
                code='ZC-ROUTE',
                message=(
                    f'Multiple default gateways ({routes}) — VPN or a second NIC may steal '
                    'the MITM/hotspot path. Disconnect VPN or fix adapter metrics.'
                ),
            )
        )

    gw_ip = str(router_ip or '').strip()
    gw_mac = str(router_mac or '').strip()
    if gw_ip and ip and not ipv4_same_subnet(ip, gw_ip, 24):
        findings.append(
            ReadinessFinding(
                level='fail',
                code='ZC-ROUTE',
                message=(
                    f'PC ({ip}) and gateway ({gw_ip}) are not on the same subnet — '
                    'pick the LAN router adapter in Settings (not modem/VPN).'
                ),
            )
        )
    if gw_ip:
        try:
            from tools.utils import mac_address_is_usable
        except Exception:

            def mac_address_is_usable(mac: Any) -> bool:  # type: ignore
                s = str(mac or '').strip().lower().replace('-', ':')
                return bool(s) and s not in ('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff')

        if not mac_address_is_usable(gw_mac):
            findings.append(
                ReadinessFinding(
                    level='fail',
                    code='ZC-GWMAC',
                    message=(
                        'Router MAC unknown — ARP MITM cannot arm. '
                        'Check Npcap + cable/Wi‑Fi driver, then Rescan.'
                    ),
                )
            )

    hints = list(wifi_link_hints or [])
    if probe_wifi and not hints:
        hints = probe_wifi_link_hint_codes()
    _append_wifi_hint_findings(findings, hints)

    try:
        from tools.user_errors import note_zc_findings

        note_zc_findings(findings, source='pc_readiness')
    except Exception:
        pass
    return findings


def collect_device_path_readiness(
    device: dict,
    *,
    iface_ip: str = '',
    router_ip: str = '',
    router_mac: str = '',
    wifi_link_hints: Optional[Iterable[str]] = None,
    lan_ipv6_enabled: Optional[bool] = None,  # accepted for callers; not surfaced in Ready
    prefix_len: int = 24,
) -> list[ReadinessFinding]:
    """Per-victim LAN path checks (no ping / no scapy). Uses cached Wi‑Fi hints."""
    findings: list[ReadinessFinding] = []

    def _finish(rows: list[ReadinessFinding]) -> list[ReadinessFinding]:
        try:
            from tools.user_errors import note_zc_findings

            note_zc_findings(rows, source='device_readiness')
        except Exception:
            pass
        return rows

    if not isinstance(device, dict):
        return _finish(
            [
                ReadinessFinding(level='fail', message='No device selected for path check.'),
            ]
        )
    if device.get('admin'):
        return _finish(findings)

    try:
        from tools.utils import mac_address_is_usable
    except Exception:

        def mac_address_is_usable(mac: Any) -> bool:  # type: ignore
            s = str(mac or '').strip().lower().replace('-', ':')
            return bool(s) and s not in ('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff')

    victim_ip = str(device.get('ip') or '').strip()
    victim_mac = str(device.get('mac') or '').strip()
    pc_ip = str(iface_ip or '').strip()
    if pc_ip in ('0.0.0.0', '127.0.0.1') or pc_ip.startswith('169.254.'):
        pc_ip = ''
    gw_ip = str(router_ip or '').strip()
    gw_mac = str(router_mac or '').strip()

    if not victim_ip:
        findings.append(
            ReadinessFinding(level='fail', message='Selected device has no IP.'),
        )
        return _finish(findings)

    if not mac_address_is_usable(victim_mac):
        findings.append(
            ReadinessFinding(
                level='fail',
                code='ZC-VMAC',
                message=f'Victim MAC unknown for {victim_ip} — ping the device once, then Rescan.',
            )
        )

    if not mac_address_is_usable(gw_mac):
        findings.append(
            ReadinessFinding(
                level='fail',
                code='ZC-GWMAC',
                message='Router MAC unknown — ARP MITM cannot arm. Check Npcap + cable/Wi‑Fi driver.',
            )
        )

    if pc_ip and victim_ip and not ipv4_same_subnet(pc_ip, victim_ip, prefix_len):
        findings.append(
            ReadinessFinding(
                level='fail',
                code='ZC-ROUTE',
                message=(
                    f'PC ({pc_ip}) and device ({victim_ip}) are not on the same subnet — '
                    'LAN Kill needs a local L2 path.'
                ),
            )
        )
    if pc_ip and gw_ip and not ipv4_same_subnet(pc_ip, gw_ip, prefix_len):
        findings.append(
            ReadinessFinding(
                level='fail',
                code='ZC-ROUTE',
                message=(
                    f'PC ({pc_ip}) and gateway ({gw_ip}) are not on the same subnet — '
                    'pick the LAN router adapter in Settings (not modem/VPN).'
                ),
            )
        )

    _append_wifi_hint_findings(findings, wifi_link_hints)

    if not findings:
        label = str(device.get('name') or device.get('vendor') or victim_ip).strip() or victim_ip
        findings.append(
            ReadinessFinding(
                level='ok',
                message=f'LAN path looks OK for {label} ({victim_ip}).',
            )
        )
    return _finish(findings)


def worst_level(findings: Iterable[ReadinessFinding]) -> str:
    order = {'ok': 0, 'warn': 1, 'fail': 2}
    worst = 'ok'
    for f in findings:
        if order.get(f.level, 0) > order.get(worst, 0):
            worst = f.level
    return worst
