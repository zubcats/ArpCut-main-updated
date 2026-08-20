import os
import subprocess
from subprocess import STDOUT, check_output, CalledProcessError
from socket import socket
from threading import Thread
from manuf import manuf
import sys
import time
import webbrowser
import re
import ipaddress

from networking.ifaces import NetFace
from constants import *

p = manuf.MacParser()


class _LazyScapyConf:
    """Defer ``scapy.all`` import until first use.

    Importing scapy.arch can hang when Npcap is AdminOnly/wedged. Helpers like
    ``good_mac`` / ``ipv4_same_link`` / ``run_command`` must stay usable without
    loading wpcap — Clumsy/diag/tests and WinDivert paths depend on that.
    """

    __slots__ = ('_real',)

    def __init__(self) -> None:
        object.__setattr__(self, '_real', None)

    def _load(self):
        real = object.__getattribute__(self, '_real')
        if real is None:
            from scapy.all import conf as real

            object.__setattr__(self, '_real', real)
        return real

    def __getattr__(self, name):
        return getattr(self._load(), name)

    def __setattr__(self, name, value):
        setattr(self._load(), name, value)

    def __str__(self) -> str:
        return str(self._load())

    def __repr__(self) -> str:
        return repr(self._load())


conf = _LazyScapyConf()

_ADAPTER_GUID_RE = re.compile(
    r'([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})'
)


def _extract_adapter_guid(token: str) -> str:
    """Bare uppercase GUID from an Npcap path, {GUID}, or Settings leftover."""
    m = _ADAPTER_GUID_RE.search(str(token or ''))
    return m.group(1).upper() if m else ''


def _iface_token_matches(a, b) -> bool:
    sa, sb = str(a or '').strip(), str(b or '').strip()
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    ga, gb = _extract_adapter_guid(sa), _extract_adapter_guid(sb)
    return bool(ga and gb and ga == gb)


def get_if_list():
    from scapy.all import get_if_list as _gil

    return _gil()


def _windows_subprocess_no_window_kwargs():
    """Hide the transient console when spawning cmd.exe (avoids flash on startup / Settings)."""
    if not sys.platform.startswith('win'):
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    kw = {'startupinfo': si}
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    if no_window:
        kw['creationflags'] = no_window
    return kw


def subprocess_text_kwargs(**extra):
    """
    Safe kwargs for subprocess text mode on Windows.

    Without ``errors='replace'``, localized netsh/PowerShell output can raise
    UnicodeDecodeError inside subprocess reader threads (ZC-CNV5TQ).
    """
    kw = {'text': True, 'errors': 'replace'}
    kw.update(extra)
    return kw


def run_command(command, *, shell=True, timeout=None, check=False):
    """
    Run a subprocess without flashing cmd.exe / PowerShell on Windows.

    String commands with shell=True use ``cmd.exe /d /c`` (not COMSPEC) so PCs
    with COMSPEC pointing at PowerShell do not spawn a visible console per call.
    """
    kwargs = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        **subprocess_text_kwargs(),
        'check': check,
    }
    if timeout is not None:
        kwargs['timeout'] = timeout
    if sys.platform.startswith('win'):
        kwargs.update(_windows_subprocess_no_window_kwargs())
        if shell and isinstance(command, str):
            cmd_exe = os.path.join(
                os.environ.get('SystemRoot', r'C:\Windows'),
                'System32',
                'cmd.exe',
            )
            if os.path.isfile(cmd_exe):
                return subprocess.run(
                    [cmd_exe, '/d', '/c', command],
                    shell=False,
                    **kwargs,
                )
    return subprocess.run(command, shell=shell, **kwargs)


def _is_bad_iface_display_name(s: str) -> bool:
    """True if netsh/ipconfig gave a useless label (e.g. 'Description', state words, generic stubs)."""
    from tools.win_locale import is_bad_iface_display_name

    return is_bad_iface_display_name(s)


_VPN_VIRTUAL_IFACE_NEEDLES = (
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
    'veth',
)


def _iface_looks_vpn_or_virtual(iface) -> bool:
    """Soft signal that an adapter is VPN/virtual (still selectable; deprioritized)."""
    blob = (
        f'{getattr(iface, "name", "") or ""} '
        f'{getattr(iface, "guid", "") or ""} '
        f'{getattr(iface, "description", "") or ""}'
    ).lower()
    return any(n in blob for n in _VPN_VIRTUAL_IFACE_NEEDLES)


_SOFTAP_IFACE_NEEDLES = (
    'local area connection*',
    'wi-fi direct',
    'wifi direct',
    'hosted network',
    'microsoft hosted',
    'mobile hotspot',
    'microsoft wi-fi direct',
)


def _is_softap_ipv4(ip: str) -> bool:
    """True for Windows Mobile Hotspot / ICS SoftAP host or client IPv4."""
    s = str(ip or '').strip()
    return s.startswith('192.168.137.') or s.startswith('192.168.173.')


def _iface_name_looks_softap(name: str) -> bool:
    blob = str(name or '').strip().lower()
    return bool(blob) and any(n in blob for n in _SOFTAP_IFACE_NEEDLES)


def _iface_looks_softap(iface) -> bool:
    """True for the Wi-Fi Direct / hosted-network NIC used by Mobile Hotspot."""
    return _iface_name_looks_softap(getattr(iface, 'name', None) or '')


def _softap_bind_allowed() -> bool:
    """LAN Kill uses the home NIC; SoftAP bind is only for Clumsy hotspot."""
    try:
        from tools.clumsy_inline import clumsy_mode_enabled

        return bool(clumsy_mode_enabled())
    except Exception:
        return False


def _ip_ok_for_bind(ip: str) -> bool:
    """Reject leftover ICS 137/173 addresses when Clumsy mode is off."""
    if not _ipv4_usable_for_lan(ip):
        return False
    if _is_softap_ipv4(ip) and not _softap_bind_allowed():
        return False
    return True


def _prefer_windows_friendly_iface_name(*candidates: str) -> str:
    """Longest non-junk Windows adapter name (PowerShell GUID map beats truncated netsh)."""
    best = ''
    for raw in candidates:
        s = str(raw or '').strip()
        if not s or _is_bad_iface_display_name(s):
            continue
        if best and s != best and s in best:
            continue
        if best and best in s and len(s) > len(best):
            best = s
            continue
        if len(s) > len(best):
            best = s
    return best


def _mac_match_ipconfig_adapter(scapy_mac: str, interface_map: dict):
    """
    Map a Scapy MAC to an ipconfig adapter.

    Wi-Fi and Microsoft Wi-Fi Direct (Local Area Connection* N) often share a
    radio MAC. Prefer the row with a real LAN IPv4 so leftover hotspot NICs
    do not steal Wi‑Fi's address — and so a GUID-only Npcap binding still
    gets 192.168.x.x instead of staying at 0.0.0.0.
    """
    want = good_mac(scapy_mac)
    if not want or want == GLOBAL_MAC:
        return None, None
    hits = []
    for friendly, info in (interface_map or {}).items():
        mac = good_mac((info or {}).get('mac'))
        if mac and mac != GLOBAL_MAC and mac == want:
            hits.append((friendly, info))
    if not hits:
        return None, None
    if len(hits) == 1:
        return hits[0]

    ranked = []
    for friendly, info in hits:
        ip = str((info or {}).get('ip') or '').strip()
        score = 0
        if _ip_ok_for_bind(ip):
            score += 20
        if not _iface_name_looks_softap(friendly):
            score += 15
        if not _is_bad_iface_display_name(friendly):
            score += 5
        ranked.append((score, friendly, info))
    ranked.sort(key=lambda row: -row[0])
    if ranked[0][0] <= 0:
        return None, None
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None, None
    return ranked[0][1], ranked[0][2]


def _better_iface_for_same_ip(prev, face):
    """When two Npcap bindings share an IPv4, keep the physical NIC over SoftAP."""
    if prev is None:
        return face
    prev_soft = _iface_looks_softap(prev)
    face_soft = _iface_looks_softap(face)
    if prev_soft and not face_soft:
        return face
    if face_soft and not prev_soft:
        return prev
    if mac_address_is_usable(getattr(face, 'mac', None)) and not mac_address_is_usable(
        getattr(prev, 'mac', None)
    ):
        return face
    return prev


def ifaces_for_settings_combo(ifaces):
    """Adapters shown in Settings: hide leftover hotspot NICs unless Clumsy is on."""
    rows = list(ifaces or [])
    if not rows:
        return []
    if _softap_bind_allowed():
        return rows
    preferred = [iface for iface in rows if not _iface_looks_softap(iface)]
    return preferred or rows


def settings_iface_picker_hint(ifaces) -> str:
    """Short Settings caption for the adapter list."""
    rows = list(ifaces or [])
    leftover_only = bool(rows) and all(_iface_looks_softap(i) for i in rows) and (
        not _softap_bind_allowed()
    )
    if leftover_only:
        return (
            'Only a leftover Mobile Hotspot adapter is listed. '
            'Reinstall Npcap with Wi‑Fi support, then restart ZubCut.'
        )
    return (
        'This PC’s Wi‑Fi or Ethernet. '
        'Leftover Mobile Hotspot adapters stay hidden unless Clumsy Mode is on.'
    )


def format_iface_settings_label(iface: NetFace) -> str:
    """
    One-line label for the Settings network combo (shown to user).
    Settings JSON still stores iface.name (internal key for get_iface_by_name).
    """
    name = (iface.name or '').strip()
    ip = getattr(iface, 'ip', None) or ''
    try:
        lip = _iface_live_ipv4(iface)
        if lip:
            ip = lip
    except Exception:
        pass
    if ip in ('0.0.0.0', '127.0.0.1'):
        ip = ''
    mac = getattr(iface, 'mac', None) or ''
    if mac and mac == GLOBAL_MAC:
        mac = ''
    bits = []
    if name and not _is_bad_iface_display_name(name):
        bits.append(name)
    elif name:
        bits.append(name)
    if ip:
        bits.append(ip)
    elif _iface_looks_softap(iface):
        bits.append('hotspot leftover')
    if mac and len(bits) < 2:
        bits.append(mac)
    if not bits:
        g = str(getattr(iface, 'guid', '') or '')
        tail = g.split('NPF_')[-1].strip('{}') if g else ''
        bits.append(tail[:24] + ('…' if len(tail) > 24 else '') if tail else 'Adapter')
    return ' · '.join(bits)


def terminal(command, shell=True, decode=True):
    """
    Terminal commands via Subprocess (cross-platform).

    On Windows with shell=True, runs through ``%SystemRoot%\\System32\\cmd.exe /d /c``
    instead of ``subprocess``'s default shell (``%COMSPEC%``). Some PCs set COMSPEC
    to PowerShell, which would spawn ``powershell.exe`` for every ``arp``/``ping``/``ipconfig``.
    Uses ``STARTUPINFO`` + ``SW_HIDE`` so no console window flashes on each call.
    """
    try:
        kwargs = {'stderr': STDOUT}
        if sys.platform.startswith('win') and shell:
            win_hide = _windows_subprocess_no_window_kwargs()
            cmd_exe = os.path.join(
                os.environ.get('SystemRoot', r'C:\Windows'),
                'System32',
                'cmd.exe',
            )
            if isinstance(command, str) and os.path.isfile(cmd_exe):
                argv = [cmd_exe, '/d', '/c', command]
                cmd = check_output(argv, shell=False, stderr=STDOUT, **win_hide)
            else:
                cmd = check_output(command, shell=True, stderr=STDOUT, **win_hide)
        else:
            cmd = check_output(command, shell=shell, stderr=STDOUT)
        return cmd.decode('utf-8', errors='replace') if decode else None
    except CalledProcessError as e:
        # Return error output if available for debugging
        if hasattr(e, 'output') and e.output:
            try:
                return e.output.decode('utf-8', errors='replace') if decode else None
            except:
                pass
        return None
    except UnicodeDecodeError:
        try:
            return cmd.decode('utf-8', errors='replace') if decode else None
        except:
            return str(cmd) if decode else None
    except Exception:
        return None

def threaded(fn):
    """
    Thread wrapper function (decorator)
    """
    from tools.crash_feedback import safe_daemon_target

    def run(*k, **kw):
        t = Thread(target=safe_daemon_target(fn, *k, **kw), daemon=True)
        t.start()
        return t
    return run

def get_vendor(mac):
    """
    Get vendor from manuf wireshark mac database
    """
    return p.get_manuf(mac) or 'None'

def good_mac(mac):
    """
    Convert dash separated MAC to colon separated
    """
    return mac.upper().replace('-', ':')

def get_my_ip(iface_name, *, allow_default_route_fallback: bool = True):
    """
    Get interface IP address (cross-platform)
    iface_name must be the Scapy/pcap name (e.g., \\Device\\NPF_{GUID} on Windows, en0 on macOS)

    When *allow_default_route_fallback* is False, do not return another NIC's
    default-route source IP. Callers that mean "is this adapter live?" must pass
    False — otherwise a disconnected hotspot NIC inherits the Wi‑Fi address.
    """
    try:
        conf.route.resync()
    except Exception:
        pass

    invalid_ips = ('0.0.0.0', '127.0.0.1', None)
    iface_name = iface_name or str(conf.iface)
    candidates: list[str] = []

    # Preferred: walk the scapy route table for the specific interface
    try:
        for entry in conf.route.routes:
            if len(entry) >= 5:
                dst, mask, gw, iface, src_ip = entry[:5]
                if iface == iface_name and src_ip not in invalid_ips:
                    candidates.append(str(src_ip))
    except Exception:
        pass

    for src_ip in candidates:
        if _ipv4_usable_for_lan(src_ip):
            return src_ip
    for src_ip in candidates:
        if _ipv4_valid(src_ip) and src_ip not in invalid_ips:
            return src_ip

    # Fallback: use the default route (first non-loopback source IP)
    if allow_default_route_fallback:
        try:
            route_result = conf.route.route("0.0.0.0")
            if len(route_result) >= 2 and route_result[1] not in invalid_ips:
                src_ip = str(route_result[1])
                if _ipv4_usable_for_lan(src_ip):
                    return src_ip
                if _ipv4_valid(src_ip):
                    return src_ip
        except Exception:
            pass

    # Last resort
    return '127.0.0.1'

def get_gateway_ip(iface_name):
    """
    Get default gateway IP (cross-platform)
    iface_name must be the Scapy/pcap name (e.g., \\Device\\NPF_{GUID} on Windows, en0 on macOS)
    """
    try:
        conf.route.resync()
    except Exception:
        pass

    invalid_gws = ('0.0.0.0', None)
    iface_name = iface_name or str(conf.iface)
    chosen_gw = None
    src_hint = ''

    try:
        src_hint = str(get_my_ip(iface_name, allow_default_route_fallback=False) or '').strip()
        if src_hint in ('127.0.0.1', '0.0.0.0'):
            src_hint = ''
    except Exception:
        src_hint = ''

    try:
        for entry in conf.route.routes:
            if len(entry) >= 5:
                dst, mask, gw, iface, src_ip = entry[:5]
                if gw in invalid_gws:
                    continue
                matched = (not iface_name) or _iface_token_matches(iface, iface_name)
                if not matched and src_hint and str(src_ip) == src_hint:
                    matched = True
                if not matched:
                    continue
                # Default route (dst == 0 and mask == 0) is ideal
                if dst == 0 and mask == 0:
                    return gw
                if not chosen_gw:
                    chosen_gw = gw
    except Exception:
        pass

    # Fallback: use the gateway from the default route (no iface filter)
    if not chosen_gw:
        try:
            result = conf.route.route("0.0.0.0")
            if len(result) >= 3 and result[2] and result[2] not in invalid_gws:
                chosen_gw = result[2]
        except Exception:
            pass

    if (not chosen_gw or chosen_gw in invalid_gws) and sys.platform.startswith('win'):
        os_gw = windows_default_gateway_ip(iface_hint=str(iface_name or ''), src_ip=src_hint)
        if os_gw:
            return os_gw

    return chosen_gw or '0.0.0.0'

def get_gateway_mac(iface_ip, router_ip, *, allow_scapy_probe: bool = True):
    """Resolve gateway MAC. Scapy getmacbyip can block ~4s — skip on GUI paint paths."""
    if sys.platform.startswith('win'):
        # Windows: try ARP table lookup
        if iface_ip and iface_ip != '127.0.0.1':
            response = terminal(f'arp -a {router_ip} -N {iface_ip}')
        else:
            response = terminal(f'arp -a {router_ip}')
        
        if response:
            # Parse Windows ARP output: "  IP_ADDRESS      MAC_ADDRESS      TYPE"
            from tools.win_locale import arp_line_is_interface_header

            for line in response.split('\n'):
                line = line.strip()
                if not line or arp_line_is_interface_header(line):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] == router_ip:
                    mac_candidate = parts[1].replace('-', ':')
                    mac = good_mac(mac_candidate)
                    if mac and mac != GLOBAL_MAC:
                        return mac
    else:
        # macOS/Linux: query ARP table
        response = terminal(f'arp -n {router_ip}')
        if response:
            parts = response.split()
            for token in parts:
                if ':' in token and len(token) >= 17:
                    return good_mac(token)
    if not allow_scapy_probe:
        return GLOBAL_MAC
    # Fallback: actively resolve via scapy (can stall the GUI ~4s when ARP is cold).
    try:
        from scapy.all import getmacbyip
        mac = getmacbyip(router_ip)
        if mac:
            return good_mac(mac)
    except Exception:
        pass
    return GLOBAL_MAC


def _lan_neighbor_mac_via_arp_probe(
    ip: str,
    iface_guid: str | None = None,
    *,
    iface=None,
) -> str:
    """Layer-2 ARP who-has when ICMP is silent (PS5 often blocks ping but answers ARP)."""
    ip = str(ip or '').strip()
    if not ip or not _ipv4_valid(ip):
        return ''
    tokens: list[str] = []
    try:
        tokens = npcap_iface_tokens(iface, iface_guid)
    except Exception:
        tokens = []
    if not tokens and iface_guid:
        tokens = [str(iface_guid)]
    if not tokens:
        tokens = ['']
    try:
        from scapy.all import arping

        for token in tokens:
            # 1s is enough for LAN who-has; 2s+retry made cold Kill feel stuck.
            kwargs: dict = {'timeout': 1, 'verbose': 0, 'retry': 1}
            if token:
                kwargs['iface'] = token
            ans = arping(f'{ip}/32', **kwargs)
            rows = ans[0] if ans else []
            for _sent, rcv in rows:
                mac = good_mac(str(getattr(rcv, 'src', '') or ''))
                if mac_address_is_usable(mac):
                    return mac
    except Exception:
        pass
    return ''


def lookup_mac_from_arp_table(ip: str, iface_ip: str | None = None) -> str:
    """
    Read the Windows/macOS ARP cache for ``ip`` without Scapy (fast, no 4s timeout).

    PS5/Wi‑Fi clients are often missing from the cache until something pings them;
    ZubCut's scan MAC can go stale while the UI still shows KILL:ON in ~20ms.
    """
    ip = str(ip or '').strip()
    if not ip or not _ipv4_valid(ip):
        return GLOBAL_MAC
    if sys.platform.startswith('win'):
        if iface_ip and iface_ip not in ('127.0.0.1', '0.0.0.0'):
            response = terminal(f'arp -a {ip} -N {iface_ip}')
        else:
            response = terminal(f'arp -a {ip}')
        if response:
            from tools.win_locale import arp_line_is_interface_header

            for line in response.split('\n'):
                line = line.strip()
                if not line or arp_line_is_interface_header(line):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] == ip:
                    mac = good_mac(parts[1].replace('-', ':'))
                    if mac and mac != GLOBAL_MAC:
                        return mac
    else:
        response = terminal(f'arp -n {ip}')
        if response:
            for token in response.split():
                if ':' in token and len(token) >= 17:
                    mac = good_mac(token)
                    if mac and mac != GLOBAL_MAC:
                        return mac
    return GLOBAL_MAC


def ipv4_ping_reachable(ip: str, *, timeout_ms: int = 500, attempts: int = 1) -> bool:
    """True when an ICMP echo to ``ip`` gets a reply (ignores stale ARP ghosts)."""
    ip = str(ip or '').strip()
    if not ip or not _ipv4_valid(ip):
        return False
    tries = max(1, int(attempts))
    for n in range(tries):
        try:
            if sys.platform.startswith('win'):
                out = run_command(
                    ['ping', '-n', '1', '-w', str(max(100, int(timeout_ms))), ip],
                    shell=False,
                    timeout=max(2, int(timeout_ms / 1000) + 1),
                )
                # run_command returns CompletedProcess — must read stdout (not repr).
                # Prefer returncode: localized ping text varies (DE/FR/ES) but rc==0
                # with TTL= is stable across Windows language packs.
                text = str(getattr(out, 'stdout', None) or out or '').lower()
                rc = getattr(out, 'returncode', None)
                if rc == 0 and 'ttl=' in text:
                    return True
                if (
                    rc is None
                    and 'ttl=' in text
                    and 'unreachable' not in text
                    and 'timed out' not in text
                    and 'zeitüberschreitung' not in text
                    and 'délai' not in text
                ):
                    return True
            else:
                out = run_command(
                    ['ping', '-c', '1', '-W', str(max(1, int(timeout_ms / 1000))), ip],
                    shell=False,
                    timeout=max(2, int(timeout_ms / 1000) + 1),
                )
                text = str(getattr(out, 'stdout', None) or out or '').lower()
                if 'ttl=' in text or 'time=' in text:
                    return True
        except Exception:
            pass
        if n + 1 < tries:
            time.sleep(0.12)
    return False


def victim_endpoint_live_for_mitm(
    ip: str,
    expected_mac: str,
    iface_ip: str | None = None,
    *,
    ping_attempts: int = 3,
    arp_probe_iface: str | None = None,
    recent_arp_mac: str | None = None,
) -> tuple[bool, str]:
    """
    PS5 Ethernet vs Wi‑Fi rows use different MACs — do not MITM a ghost favorite IP.
    Pings up to ``ping_attempts`` times; if ICMP is silent but ARP still maps this IP
    to ``expected_mac`` (and the MAC has not moved to another IP), treat as live.

    ``recent_arp_mac`` is a MAC just learned via Scapy who-has in the caller (OS ARP
    cache may still be empty). Treated like a fresh probe without a second arping.
    """
    ip = str(ip or '').strip()
    expected_mac = good_mac(str(expected_mac or '').strip())
    if not ip or not _ipv4_valid(ip):
        return False, 'invalid victim IP'

    live_ip = ''
    if expected_mac:
        try:
            live_ip = str(lookup_ip_from_arp_table(expected_mac, iface_ip) or '').strip()
        except Exception:
            live_ip = ''
    if live_ip and live_ip != ip:
        return (
            False,
            f'{ip} is offline — this device is now at {live_ip}. Rescan and use that row.',
        )

    # Fast path: ARP already maps this IP to the selected MAC — skip ICMP waits
    # (3×500–600 ms) so cold Kill after a scan still arms instantly.
    arp_mac_now = lookup_mac_from_arp_table(ip, iface_ip)
    if (
        expected_mac
        and mac_address_is_usable(arp_mac_now)
        and good_mac(arp_mac_now) == expected_mac
    ):
        return True, ''

    hint_mac = good_mac(str(recent_arp_mac or '').strip())
    if (
        expected_mac
        and mac_address_is_usable(hint_mac)
        and hint_mac == expected_mac
        and not mac_address_is_usable(arp_mac_now)
    ):
        # Caller already resolved L2; accept before paying ICMP (PS5 often blocks ping).
        return True, ''

    ping_tries = max(1, int(ping_attempts))
    ping_wait = 500 if ping_tries <= 1 else 600
    if not ipv4_ping_reachable(ip, attempts=ping_tries, timeout_ms=ping_wait):
        arp_mac = arp_mac_now or lookup_mac_from_arp_table(ip, iface_ip)
        from_probe = False
        if not mac_address_is_usable(arp_mac) and mac_address_is_usable(hint_mac):
            arp_mac = hint_mac
            from_probe = True
        elif not mac_address_is_usable(arp_mac) and arp_probe_iface:
            probed = _lan_neighbor_mac_via_arp_probe(ip, arp_probe_iface)
            if mac_address_is_usable(probed):
                arp_mac = probed
                from_probe = True
        if mac_address_is_usable(arp_mac):
            if live_ip and live_ip != ip:
                return (
                    False,
                    f'{ip} is offline — this device is now at {live_ip}. Rescan and use that row.',
                )
            if from_probe or not expected_mac or arp_mac == expected_mac:
                return True, ''
        if live_ip and live_ip != ip:
            return (
                False,
                f'{ip} is offline — this device is now at {live_ip}. Rescan and use that row.',
            )
        return (
            False,
            f'{ip} did not answer ping — wake the PS5 (not Rest Mode), run Arp Scan, '
            f'and select the PlayStation row for that IP. '
            f'Guest Wi‑Fi / AP isolation also blocks LAN Kill (ZC-ISOLATION).',
        )
    arp_mac = lookup_mac_from_arp_table(ip, iface_ip)
    if mac_address_is_usable(arp_mac) and expected_mac and arp_mac != expected_mac:
        live_ip = str(lookup_ip_from_arp_table(expected_mac, iface_ip) or '').strip()
        hint = f' It may be at {live_ip} now.' if live_ip and live_ip != ip else ''
        return (
            False,
            f'{ip} belongs to another device (ARP MAC mismatch).{hint} Rescan and pick the live PS5 row.',
        )
    return True, ''


def _arp_refresh_device_record(device: dict, iface_ip: str | None = None) -> None:
    """Update device['mac'] from forward ARP for device['ip'] (ping once if needed)."""
    if not isinstance(device, dict):
        return
    ip = str(device.get('ip') or '').strip()
    if not ip:
        return
    expected = good_mac(str(device.get('mac') or ''))
    mac = lookup_mac_from_arp_table(ip, iface_ip)
    if not mac_address_is_usable(mac) and sys.platform.startswith('win'):
        try:
            run_command(
                ['ping', '-n', '1', '-w', '400', ip],
                shell=False,
                timeout=2,
            )
        except Exception:
            pass
        mac = lookup_mac_from_arp_table(ip, iface_ip)
    if mac_address_is_usable(mac):
        got = good_mac(mac)
        # During MITM the OS ARP cache can briefly map an IP to the wrong MAC.
        # Never replace the row the user picked with another device's MAC.
        if expected and got != expected:
            return
        device['mac'] = got


def _resolve_allowed_macs(device: dict) -> set[str]:
    """MACs we may MITM when resolving Wi‑Fi ↔ Ethernet for the same console."""
    macs: set[str] = set()
    orig = good_mac(str(device.get('mac') or ''))
    if orig:
        macs.add(orig)
    nick = str(device.get('name') or '').strip()
    if nick and nick != '-':
        try:
            from networking.nicknames import get_nicknames_dict, parse_nickname_profile_key

            for key, nm in get_nicknames_dict().items():
                if str(nm or '').strip() != nick:
                    continue
                prof_mac, _pfx = parse_nickname_profile_key(str(key))
                if prof_mac:
                    macs.add(prof_mac)
        except Exception:
            pass
    return macs


def _resolve_mac_allowed(device: dict, allowed: set[str]) -> bool:
    mac = good_mac(str(device.get('mac') or ''))
    return bool(mac and mac in allowed)


def _device_row_is_playstation(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    dtype = str(row.get('type') or '')
    vendor = str(row.get('vendor') or '').lower()
    return (
        'PlayStation' in dtype
        or 'sony interactive' in vendor
        or 'sony computer entertainment' in vendor
    )


def resolve_live_lan_victim(
    device: dict,
    devices: list[dict] | None = None,
    iface_ip: str | None = None,
    *,
    ping_attempts: int = 1,
) -> tuple[dict, str]:
    """
    When PS5 moves Wi‑Fi ↔ Ethernet it gets a new IP and MAC. The saved table row may
    be stale; find a live endpoint (same nickname, reverse ARP, or refreshed forward ARP).
    Returns (device, user_hint). hint is empty when the input row was already live.
    """
    if not isinstance(device, dict):
        return device, ''
    iface_ip = str(iface_ip or '').strip()
    dev = dict(device)
    rows = [d for d in (devices or []) if isinstance(d, dict) and not d.get('admin')]
    allowed_macs = _resolve_allowed_macs(dev)

    def _live_ok(row: dict) -> bool:
        _arp_refresh_device_record(row, iface_ip)
        ok, _ = victim_endpoint_live_for_mitm(
            row.get('ip'),
            row.get('mac'),
            iface_ip or None,
            ping_attempts=max(1, int(ping_attempts)),
        )
        return ok

    _arp_refresh_device_record(dev, iface_ip)
    if _live_ok(dev):
        return dev, ''

    mac = good_mac(str(dev.get('mac') or ''))
    moved_ip = str(lookup_ip_from_arp_table(mac, iface_ip) or '').strip()
    if moved_ip and _ipv4_valid(moved_ip) and moved_ip != str(dev.get('ip') or '').strip():
        dev['ip'] = moved_ip
        _arp_refresh_device_record(dev, iface_ip)
        if _live_ok(dev):
            return dev, f'PS5 is at {moved_ip} now (Ethernet/Wi‑Fi change).'

    nick = str(dev.get('name') or '').strip()
    if nick and nick != '-':
        for row in rows:
            if str(row.get('name') or '').strip() != nick:
                continue
            cand = dict(row)
            if not _resolve_mac_allowed(cand, allowed_macs):
                # Same nickname on two PlayStation rows = Wi‑Fi ↔ Ethernet handoff.
                if not (
                    _device_row_is_playstation(dev)
                    and _device_row_is_playstation(cand)
                ):
                    continue
            if _live_ok(cand):
                lip = str(cand.get('ip') or '')
                return cand, f'Using live {nick} at {lip} (rescan row was stale).'

        try:
            from networking.nicknames import (
                get_nickname_last_ip_map,
                get_nicknames_dict,
                parse_nickname_profile_key,
                resolve_favorite_ip,
            )

            last_map = get_nickname_last_ip_map()
            seen_macs: set[str] = set()
            for key, nm in get_nicknames_dict().items():
                if str(nm or '').strip() != nick:
                    continue
                prof_mac, _pfx = parse_nickname_profile_key(str(key))
                if not prof_mac or prof_mac in seen_macs:
                    continue
                if prof_mac not in allowed_macs:
                    continue
                seen_macs.add(prof_mac)
                fav_ip = resolve_favorite_ip(prof_mac, str(key), last_map, iface_ip)
                if not fav_ip or not _ipv4_valid(fav_ip):
                    continue
                cand = {'ip': fav_ip, 'mac': prof_mac, 'name': nick}
                for row in rows:
                    if good_mac(str(row.get('mac') or '')) == prof_mac:
                        cand.update(row)
                        cand['name'] = nick
                        break
                if _live_ok(cand):
                    return (
                        cand,
                        f'Using live {nick} at {fav_ip} (PS5 Ethernet/Wi‑Fi profile).',
                    )
        except Exception:
            pass

    _ok, reason = victim_endpoint_live_for_mitm(
        dev.get('ip'),
        dev.get('mac'),
        iface_ip or None,
        ping_attempts=max(1, int(ping_attempts)),
    )
    return dev, reason or 'Rescan and select the PS5 row matching its current connection.'


def lookup_ip_from_arp_table(mac: str, iface_ip: str | None = None) -> str:
    """Reverse ARP lookup: IPv4 currently associated with ``mac`` in the OS cache."""
    mac = good_mac(mac)
    if not mac or mac in (GLOBAL_MAC, '00:00:00:00:00:00'):
        return ''
    if sys.platform.startswith('win'):
        if iface_ip and iface_ip not in ('127.0.0.1', '0.0.0.0'):
            response = terminal(f'arp -a -N {iface_ip}')
        else:
            response = terminal('arp -a')
        if response:
            from tools.win_locale import arp_line_is_interface_header, fold_latin

            for line in response.split('\n'):
                line = line.strip()
                low = fold_latin(line)
                if (
                    not line
                    or arp_line_is_interface_header(line)
                    or 'internet address' in low
                    or 'adresse internet' in low
                    or 'direccion de internet' in low
                    or 'internetadresse' in low
                ):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    ip_candidate = parts[0]
                    mac_candidate = good_mac(parts[1].replace('-', ':'))
                    if mac_candidate == mac and _ipv4_valid(ip_candidate):
                        return ip_candidate
    else:
        response = terminal('arp -a') or terminal('arp -n') or ''
        if response:
            for line in response.split('\n'):
                parts = line.split()
                if len(parts) >= 2:
                    ip_candidate = parts[0]
                    mac_candidate = good_mac(parts[1])
                    if mac_candidate == mac and _ipv4_valid(ip_candidate):
                        return ip_candidate
    return ''


def mac_address_is_usable(mac: str) -> bool:
    m = good_mac(str(mac or '').strip())
    return bool(m and m not in (GLOBAL_MAC, '00:00:00:00:00:00'))


def ipv4_is_device_list_noise(ip: str) -> bool:
    """True for unspecified, loopback, multicast, or broadcast IPv4 scan hits."""
    s = str(ip or '').strip()
    if not _ipv4_valid(s):
        return True
    if s in ('0.0.0.0', '255.255.255.255', '127.0.0.1'):
        return True
    try:
        first = int(s.split('.', 1)[0])
    except (TypeError, ValueError):
        return True
    return first == 0 or first == 127 or first >= 224


def mac_is_device_list_noise(mac: str) -> bool:
    """True for empty, broadcast, or multicast (I/G bit) hardware addresses."""
    m = good_mac(str(mac or '').strip())
    if not mac_address_is_usable(m):
        return True
    try:
        first = int(m.split(':', 1)[0], 16)
    except (TypeError, ValueError, IndexError):
        return True
    return bool(first & 0x01)


def goto(url):
    """
    Open url in default browser (cross-platform)
    """
    try:
        webbrowser.open(url)
    except Exception:
        pass

def check_connection(func):
    """
    Connection checker decorator
    """
    def wrapper(*args, **kargs):
        if is_connected():
            # args[0] == "self" in ZubCutApp class
            return func(args[0])
    return wrapper

_IFACES_CACHE: list | None = None
_IFACES_CACHE_AT: float = 0.0
_IFACES_CACHE_TTL_S = 45.0
_WIN_ADAPTER_NAMES: dict[str, str] | None = None


def _guid_lookup_key(guid: str) -> str:
    g = str(guid or '').strip().upper()
    if not g:
        return ''
    if not g.startswith('{'):
        g = '{' + g + '}'
    return g


def _windows_adapter_friendly_by_guid() -> dict[str, str]:
    """One-shot GUID → 'Wi-Fi' / 'Ethernet' map (cached; Realtek USB Wi‑Fi breaks ipconfig labels)."""
    global _WIN_ADAPTER_NAMES
    if _WIN_ADAPTER_NAMES is not None:
        return _WIN_ADAPTER_NAMES
    out: dict[str, str] = {}
    if sys.platform.startswith('win'):
        try:
            r = run_command(
                [
                    'powershell',
                    '-NoProfile',
                    '-WindowStyle',
                    'Hidden',
                    '-Command',
                    "Get-NetAdapter | ForEach-Object { $_.InterfaceGuid.ToString().ToUpper() + '|' + $_.Name }",
                ],
                shell=False,
                timeout=8,
            )
            if r.returncode == 0 and r.stdout:
                for line in str(r.stdout).splitlines():
                    line = line.strip()
                    if '|' not in line:
                        continue
                    gid, fname = line.split('|', 1)
                    gid = _guid_lookup_key(gid.strip())
                    fname = fname.strip()
                    if gid and fname:
                        out[gid] = fname
        except Exception:
            pass
    _WIN_ADAPTER_NAMES = out
    return out


def invalidate_ifaces_cache(*, full: bool = False) -> None:
    """Drop cached adapter list. ``full=True`` also refreshes Windows friendly names (PowerShell)."""
    global _IFACES_CACHE, _IFACES_CACHE_AT, _WIN_ADAPTER_NAMES
    _IFACES_CACHE = None
    _IFACES_CACHE_AT = 0.0
    if full:
        _WIN_ADAPTER_NAMES = None


def get_ifaces_cached(*, max_age_s: float | None = None):
    """Return interface list; reuse recent scan to avoid blocking Settings open."""
    import time

    global _IFACES_CACHE, _IFACES_CACHE_AT
    ttl = float(_IFACES_CACHE_TTL_S if max_age_s is None else max_age_s)
    now = time.monotonic()
    if _IFACES_CACHE is not None and (now - _IFACES_CACHE_AT) < ttl:
        return list(_IFACES_CACHE)
    ifaces = get_ifaces()
    # Do not cache an empty scan (Npcap may not be ready on first Settings open).
    if ifaces:
        _IFACES_CACHE = list(ifaces)
        _IFACES_CACHE_AT = now
    return list(ifaces)


def get_ifaces():
    """
    Get current working interfaces (cross-platform)
    """
    conf.route.resync()
    if sys.platform.startswith('win'):
        # Windows: Scapy returns GUIDs like \\Device\\NPF_{GUID}
        # We need to map these to friendly names and get IPs
        
        # Step 1: Get interface info from ipconfig to map friendly names to IPs
        ipconfig_output = terminal('ipconfig /all')
        interface_map = {}  # friendly_name -> {ip, mac, guid}
        current_adapter = None
        
        if ipconfig_output:
            for line in ipconfig_output.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Adapter section headers (EN/DE/ES/FR/IT) — not English-only "adapter".
                if _ipconfig_line_is_adapter_header(line):
                    current_adapter = _ipconfig_adapter_name_from_header(line)
                    if current_adapter:
                        interface_map[current_adapter] = {
                            'ip': '0.0.0.0',
                            'mac': GLOBAL_MAC,
                            'guid': None,
                        }
                elif current_adapter:
                    # Only the adapter's own IPv4 — skip gateway/DHCP/DNS/mask lines
                    if not _ipconfig_line_is_host_ipv4(line):
                        mac_match = re.search(r'([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})', line)
                        if mac_match:
                            interface_map[current_adapter]['mac'] = good_mac(mac_match.group(1))
                        continue
                    ip_match = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', line)
                    if ip_match:
                        ip = ip_match.group(1)
                        try:
                            nums = ip.split('.')
                            if all(0 <= int(n) <= 255 for n in nums) and ip != '0.0.0.0':
                                interface_map[current_adapter]['ip'] = _prefer_ipv4(
                                    interface_map[current_adapter]['ip'], ip
                                )
                        except ValueError:
                            pass
                    mac_match = re.search(r'([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})', line)
                    if mac_match:
                        interface_map[current_adapter]['mac'] = good_mac(mac_match.group(1))
        
        # Step 2: Get GUID mapping from netsh (may be localized - best effort)
        netsh_output = terminal('netsh interface show interface')
        guid_to_friendly = {}  # guid -> friendly_name
        guid_names = _windows_adapter_friendly_by_guid()
        if netsh_output:
            for line in netsh_output.split('\n'):
                line = line.strip()
                if not line or '---' in line:
                    continue
                # Try to extract GUID in braces if present
                if '{' in line and '}' in line:
                    guid_start = line.find('{')
                    guid_end = line.find('}', guid_start)
                    if guid_start >= 0 and guid_end > guid_start:
                        guid = line[guid_start+1:guid_end]
                        friendly = line[:guid_start].strip()
                        # Keep the full adapter name. Last-token truncation turned
                        # "Local Area Connection* 10" into Settings label "10".
                        guid_to_friendly[guid] = friendly
        
        # Step 3: Get Scapy interfaces and match with our map
        from scapy.all import get_if_hwaddr
        scapy_ifaces = get_if_list()
        # Driver Easy / Npcap reinstall often leaves several ghost NPF_{GUID} bindings
        # on the same IPv4; keep the one with a real MAC (others are FF:FF:FF:FF:FF:FF).
        best_by_ip: dict[str, NetFace] = {}

        for scapy_name in scapy_ifaces:
            if 'Loopback' in scapy_name:
                continue
            # Extract GUID from Scapy name: \\Device\\NPF_{GUID}
            guid = None
            if 'NPF_' in scapy_name:
                # Extract GUID: \\Device\\NPF_{20AB37B7-7002-4A4E-9F8C-3B6C95FC709D}
                guid_part = scapy_name.split('NPF_')[-1]
                # Remove braces - GUID is between { and }
                if '{' in guid_part:
                    guid_start = guid_part.find('{')
                    guid_end = guid_part.find('}', guid_start)
                    if guid_end > guid_start:
                        guid = guid_part[guid_start+1:guid_end]
                    else:
                        # Fallback: just strip braces
                        guid = guid_part.strip('{}').split('}')[0].split('\\')[0]
                else:
                    guid = guid_part.strip('{}').split('}')[0].split('\\')[0]
            
            # Try to find matching friendly name
            friendly_name = None
            if guid and guid in guid_to_friendly:
                friendly_name = guid_to_friendly[guid]
            else:
                # Try to match by checking if GUID appears in interface_map keys
                for key in interface_map.keys():
                    if guid and guid.lower() in key.lower():
                        friendly_name = key
                        break

            # PowerShell GUID map is the source of truth (cached). Truncated netsh
            # labels like "10" must not beat "Local Area Connection* 10" / "Wi-Fi".
            ps_name = guid_names.get(_guid_lookup_key(guid)) if guid else None
            if ps_name and not _is_bad_iface_display_name(ps_name):
                friendly_name = ps_name
            else:
                friendly_name = _prefer_windows_friendly_iface_name(friendly_name) or None

            # Get IP and MAC
            ip = '0.0.0.0'
            mac = GLOBAL_MAC
            found_ip = False
            
            if friendly_name and friendly_name in interface_map:
                ip = interface_map[friendly_name]['ip']
                mac = interface_map[friendly_name]['mac']
                if ip != '0.0.0.0' and ip != '127.0.0.1':
                    found_ip = True
            
            # Try to get MAC from scapy (always try this)
            try:
                scapy_mac = get_if_hwaddr(scapy_name)
                if scapy_mac and scapy_mac != '00:00:00:00:00:00':
                    mac = scapy_mac
            except Exception:
                scapy_mac = None

            # Unique-MAC ipconfig match only. Wi-Fi Direct leftovers share the radio MAC;
            # a first-hit match steals Wi-Fi's IPv4 and hides the real NIC in Settings.
            if not friendly_name and scapy_mac:
                friendly, info = _mac_match_ipconfig_adapter(scapy_mac, interface_map)
                if friendly and info:
                    friendly_name = friendly
                    if info.get('ip') not in ('0.0.0.0', '127.0.0.1', None, ''):
                        ip = info['ip']
                        found_ip = True
            
            # Own routes only — never conf.route.route("0.0.0.0") which lets a
            # ghost NPF inherit Wi‑Fi's address while the adapter still has no IPv4.
            if not found_ip:
                try:
                    for route in conf.route.routes:
                        # Route format: (dst, mask, gw, iface, ip)
                        if len(route) >= 5 and _iface_token_matches(route[3], scapy_name):
                            route_ip = route[4]
                            if route_ip and route_ip not in ('0.0.0.0', '127.0.0.1'):
                                ip = _prefer_ipv4(ip, route_ip)
                                found_ip = True
                                break
                except Exception:
                    pass
            
            # Skip only loopback interfaces, but include interfaces even if IP is 0.0.0.0
            # (they might be valid interfaces that just don't have an IP assigned)
            if ip == '127.0.0.1':
                continue
            
            # Final fallback: this adapter's own IPv4 only (never inherit Wi‑Fi via default route).
            if not found_ip or ip == '0.0.0.0':
                try:
                    potential_ip = get_my_ip(scapy_name, allow_default_route_fallback=False)
                    if potential_ip and potential_ip != '0.0.0.0' and potential_ip != '127.0.0.1':
                        ip = _prefer_ipv4(ip, potential_ip)
                        found_ip = True
                except Exception:
                    pass
            
            # Use friendly name if available, otherwise use Scapy name (cleaned up)
            if friendly_name and not _is_bad_iface_display_name(friendly_name):
                display_name = friendly_name
            elif guid and _guid_lookup_key(guid) in guid_names:
                display_name = guid_names[_guid_lookup_key(guid)]
            else:
                # Clean up Scapy name for display
                display_name = scapy_name.replace('\\Device\\NPF_', '').strip('{}')
                # If still looks like a GUID, use a simpler name
                if '{' in display_name or len(display_name) > 50:
                    display_name = f"Interface-{scapy_ifaces.index(scapy_name)+1}"
            
            # Always yield the interface, even if IP is 0.0.0.0 (might be valid but unconfigured)
            # Only skip if it's explicitly loopback
            # KEY FIX: guid must be the Scapy/pcap name, not just the Windows GUID
            iface = {
                'name': display_name,        # nice human name (or cleaned up)
                'guid': scapy_name,         # scapy / pcap name (\\Device\\NPF_{...})
                'mac': mac,
                'ips': [ip],
                'win_guid': guid,            # optional: keep Windows GUID if needed
            }
            face = NetFace(iface)
            refresh_netface_live_ip(face)
            lip = str(face.ip or ip or '').strip()
            if lip in ('127.0.0.1', '0.0.0.0'):
                if mac_address_is_usable(mac) and not (
                    _iface_looks_softap(face) and not _softap_bind_allowed()
                ):
                    yield face
                continue
            # Skip ghost Npcap bindings (00:00… / FF:FF…) that share a live LAN IP with a real NIC.
            if not mac_address_is_usable(mac):
                continue
            # Disconnected adapters (Bluetooth, unplugged Ethernet) often show APIPA only —
            # do not treat them as the active LAN NIC (breaks Lag/Kill MITM on Wi‑Fi).
            if not _ipv4_usable_for_lan(lip):
                continue
            best_by_ip[lip] = _better_iface_for_same_ip(best_by_ip.get(lip), face)
        for face in best_by_ip.values():
            yield face
    else:
        # macOS/Linux: Build iface dicts similar to Windows structure
        # name, guid=name, mac via scapy, ips via route table
        
        # Build a map of iface -> src_ip from route table
        iface_ips = {}
        try:
            for entry in conf.route.routes:
                if len(entry) >= 5:
                    dst, mask, gw, iface, src_ip = entry[:5]
                    if src_ip and src_ip not in ('0.0.0.0', '127.0.0.1'):
                        if iface not in iface_ips:
                            iface_ips[iface] = src_ip
        except Exception:
            pass
        
        for name in get_if_list():
            ip = iface_ips.get(name, '0.0.0.0')
            try:
                from scapy.all import get_if_hwaddr
                mac = get_if_hwaddr(name)
            except Exception:
                mac = GLOBAL_MAC
            iface = {'name': name, 'guid': name, 'mac': mac, 'ips': [ip]}
            yield NetFace(iface)

def get_default_iface():
    """
    Get default pcap interface (cross-platform)
    """
    try:
        best = pick_best_live_iface()
        if best is not None and best.name != 'NULL' and _iface_live_ipv4(best):
            refresh_netface_live_ip(best)
            return best
    except Exception:
        pass
    ifaces_list = list(get_ifaces())
    if not ifaces_list:
        return NetFace(DUMMY_IFACE)

    # Try to match with scapy's default interface
    for iface in ifaces_list:
        if iface.guid in str(conf.iface) or iface.name in str(conf.iface):
            refresh_netface_live_ip(iface)
            if _iface_live_ipv4(iface):
                return iface

    # Fallback: first connected LAN interface (not APIPA)
    for iface in ifaces_list:
        refresh_netface_live_ip(iface)
        if _iface_live_ipv4(iface):
            return iface

    # Last resort: return first interface
    return ifaces_list[0] if ifaces_list else NetFace(DUMMY_IFACE)

_IPV4_DOTTED_QUAD = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')


def _ipv4_valid(ip: str) -> bool:
    if not ip or not _IPV4_DOTTED_QUAD.match(ip):
        return False
    try:
        return all(0 <= int(p) <= 255 for p in ip.split('.'))
    except ValueError:
        return False


def _ipv4_usable_for_lan(ip: str) -> bool:
    """Routable LAN IPv4 — excludes loopback, unset, and APIPA (169.254.x.x)."""
    if not _ipv4_valid(ip):
        return False
    if ip in ('0.0.0.0', '127.0.0.1'):
        return False
    return not ip.startswith('169.254.')


def _prefer_ipv4(current: str, new: str) -> str:
    """Keep DHCP/home LAN over APIPA; never replace a good host IP with another."""
    cur = str(current or '').strip()
    nxt = str(new or '').strip()
    cur_ok = _ipv4_usable_for_lan(cur)
    nxt_ok = _ipv4_usable_for_lan(nxt)
    if cur_ok and nxt_ok:
        return cur
    if nxt_ok:
        return nxt
    if cur_ok:
        return cur
    return nxt or cur


def _ipconfig_line_is_adapter_header(line: str) -> bool:
    """True for adapter section titles (EN/DE/FR/ES)."""
    from tools.win_locale import ipconfig_line_is_adapter_header

    return ipconfig_line_is_adapter_header(line)


def _ipconfig_adapter_name_from_header(line: str) -> str:
    """Friendly adapter name from a localized ipconfig section header."""
    from tools.win_locale import ipconfig_adapter_name_from_header

    return ipconfig_adapter_name_from_header(line)


def _ipconfig_line_is_host_ipv4(line: str) -> bool:
    """True only for adapter IPv4 assignment lines — not gateway/DNS/mask."""
    from tools.win_locale import ipconfig_line_is_host_ipv4

    return ipconfig_line_is_host_ipv4(line)


def _ipconfig_line_is_gateway(line: str) -> bool:
    """True for Default Gateway lines (EN/DE/FR/ES/IT)."""
    from tools.win_locale import ipconfig_line_is_gateway

    return ipconfig_line_is_gateway(line)


def _gateways_from_ipconfig_text(text: str) -> list:
    """Return ``(adapter, host_ipv4, gateway_ipv4)`` rows from ``ipconfig`` text."""
    rows = []
    adapter = ''
    host_ip = ''
    for raw in (text or '').split('\n'):
        line = (raw or '').strip()
        if not line:
            continue
        if _ipconfig_line_is_adapter_header(line):
            adapter = _ipconfig_adapter_name_from_header(line) or ''
            host_ip = ''
            continue
        if not adapter:
            continue
        ip_m = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', line)
        if not ip_m:
            continue
        ip = ip_m.group(1)
        if not _ipv4_valid(ip):
            continue
        if _ipconfig_line_is_host_ipv4(line):
            host_ip = ip
        elif _ipconfig_line_is_gateway(line) and ip not in ('0.0.0.0', '127.0.0.1'):
            rows.append((adapter, host_ip, ip))
    return rows


def _pick_windows_gateway(rows, iface_hint: str = '', src_ip: str = '') -> str:
    usable = []
    for adapter, host, gw in rows:
        if not _ipv4_valid(gw) or gw in ('0.0.0.0', '127.0.0.1'):
            continue
        if _is_softap_ipv4(gw) and not _softap_bind_allowed():
            continue
        usable.append((adapter, host, gw))
    if not usable:
        return ''
    hint = str(iface_hint or '').strip()
    hint_guid = _extract_adapter_guid(hint)
    src = str(src_ip or '').strip()
    for adapter, host, gw in usable:
        if hint and adapter == hint:
            return gw
        if hint_guid and _extract_adapter_guid(adapter) == hint_guid:
            return gw
    if src and _ipv4_valid(src):
        for adapter, host, gw in usable:
            if host == src:
                return gw
            if ipv4_same_link(src, gw) or (host and ipv4_same_link(src, host)):
                return gw
    return usable[0][2]


def windows_default_gateway_ip(*, iface_hint: str = '', src_ip: str = '') -> str:
    """OS default gateway when Scapy's route table misses this Npcap iface."""
    if not sys.platform.startswith('win'):
        return ''
    try:
        text = terminal('ipconfig') or ''
    except Exception:
        return ''
    return _pick_windows_gateway(
        _gateways_from_ipconfig_text(text),
        iface_hint,
        src_ip,
    )


def _mask_prefix_len(mask_value) -> int:
    """Convert route-table mask (int or dotted string) to prefix length."""
    try:
        if isinstance(mask_value, str):
            return ipaddress.IPv4Network(f"0.0.0.0/{mask_value}", strict=False).prefixlen
        mv = int(mask_value)
        return bin(mv & 0xFFFFFFFF).count("1")
    except Exception:
        return 0


def ipv4_same_link(ip_a: str, ip_b: str, *, prefix_len: int = 24) -> bool:
    """True when both IPv4s share ``prefix_len`` (default /24). Never raises."""
    try:
        from tools.diag_privacy import same_ipv4_subnet

        hit = same_ipv4_subnet(ip_a, ip_b, prefix_len=prefix_len)
        return bool(hit)
    except Exception:
        pass
    try:
        a = [int(x) for x in str(ip_a or '').split('.')]
        b = [int(x) for x in str(ip_b or '').split('.')]
        if len(a) != 4 or len(b) != 4:
            return False
        plen = max(0, min(32, int(prefix_len)))
        if plen == 24:
            return a[:3] == b[:3]
        mask = (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF if plen else 0
        ai = (a[0] << 24) | (a[1] << 16) | (a[2] << 8) | a[3]
        bi = (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]
        return (ai & mask) == (bi & mask)
    except Exception:
        return False


def iface_ipv4_prefix_len(iface, default: int = 24) -> int:
    """
    Best-effort IPv4 prefix length for ``iface`` from the Scapy route table.

    Falls back to ``default`` (/24) when unknown — preserves historical scan behavior.
    """
    try:
        lip = _iface_live_ipv4(iface) or str(getattr(iface, 'ip', None) or '').strip()
        if not lip or not _ipv4_valid(lip):
            return int(default)
        addr = ipaddress.IPv4Address(lip)
        guid = str(getattr(iface, 'guid', None) or '').strip()
        name = str(getattr(iface, 'name', None) or '').strip()
        best = -1
        for entry in getattr(conf.route, 'routes', []) or []:
            if len(entry) < 4:
                continue
            net = _network_for_route(entry)
            if not net or addr not in net:
                continue
            token = str(entry[3] or '')
            if guid and token not in (guid, name):
                # Still accept when the on-link network contains our address.
                if int(net.prefixlen) < 8:
                    continue
            plen = int(net.prefixlen)
            # Ignore absurdly broad prefixes (/8–/15) — they mis-match dual-NIC PCs.
            if 16 <= plen <= 30 and plen > best:
                best = plen
        if best >= 16:
            return best
    except Exception:
        pass
    return int(default)


def _network_for_route(route_entry):
    """
    Build IPv4Network from a scapy route entry when possible.
    Route rows are usually: (dst, mask, gw, iface, src_ip, ...).
    """
    try:
        if len(route_entry) < 2:
            return None
        dst, mask = route_entry[:2]
        prefix = _mask_prefix_len(mask)
        if prefix < 0 or prefix > 32:
            return None
        dst_i = int(dst) & 0xFFFFFFFF
        return ipaddress.IPv4Network((dst_i, prefix), strict=False)
    except Exception:
        return None


def refresh_netface_live_ip(iface: NetFace) -> None:
    """Refresh NetFace.ip from the OS (Settings/scan objects go stale after NIC changes)."""
    lip = _iface_live_ipv4(iface)
    if lip:
        iface.ip = lip
        return
    cur = str(getattr(iface, 'ip', None) or '').strip()
    if _is_softap_ipv4(cur) and not _softap_bind_allowed():
        iface.ip = '0.0.0.0'


def npcap_iface_tokens(iface, primary: str | None = None) -> list[str]:
    """Ordered Npcap/Scapy bind tokens to try (GUID first, then friendly name)."""
    out: list[str] = []
    for raw in (
        primary,
        getattr(iface, 'guid', None) if iface is not None else None,
        getattr(iface, 'name', None) if iface is not None else None,
    ):
        s = str(raw or '').strip()
        if s and s != 'NULL' and s not in out:
            out.append(s)
    return out


def scapy_iface_token_ok(token) -> bool:
    """False for empty / dummy ``NULL`` tokens that make Scapy raise ValueError."""
    t = str(token or '').strip()
    return bool(t) and t.upper() != 'NULL'


def bind_scapy_conf_iface(token) -> bool:
    """Set ``conf.iface`` when *token* is a real Npcap name. Never raises."""
    if not scapy_iface_token_ok(token):
        return False
    try:
        conf.iface = token
        return True
    except Exception:
        return False


def resolve_iface_my_ip(iface) -> str:
    """Best IPv4 for scanner Me/router topology — DHCP LAN over APIPA."""
    refresh_netface_live_ip(iface)
    guid = str(getattr(iface, 'guid', None) or '').strip()
    try:
        ip = str(get_my_ip(guid, allow_default_route_fallback=False) if guid else '') or ''
    except TypeError:
        ip = str(get_my_ip(guid) if guid else '') or ''
    cached = str(getattr(iface, 'ip', None) or '').strip()
    if _ip_ok_for_bind(ip):
        return ip
    if _ip_ok_for_bind(cached):
        return cached
    return ''


def _pick_first_live_iface(ifaces):
    for iface in ifaces:
        refresh_netface_live_ip(iface)
        if _iface_live_ipv4(iface):
            return iface
    return None


def _iface_live_ipv4(iface) -> str:
    """Current IPv4 on this Npcap iface (not the stale NetFace.ip cache)."""
    if iface is not None and _iface_looks_softap(iface) and not _softap_bind_allowed():
        return ''
    guid = str(getattr(iface, 'guid', None) or '').strip()
    ip = ''
    if guid:
        try:
            ip = str(get_my_ip(guid, allow_default_route_fallback=False) or '').strip()
        except TypeError:
            try:
                ip = str(get_my_ip(guid) or '').strip()
            except Exception:
                ip = ''
        except Exception:
            ip = ''
    if ip in ('0.0.0.0',):
        return ''
    if _ip_ok_for_bind(ip):
        return ip
    cached = str(getattr(iface, 'ip', None) or '').strip()
    if ip in ('127.0.0.1', '') and _ip_ok_for_bind(cached):
        return cached
    return ''


def _iface_for_route_tokens(route_tokens, ifaces):
    if not route_tokens:
        return None
    for token in route_tokens:
        ts = str(token)
        for iface in ifaces:
            if iface.guid == ts or ts == iface.guid:
                return iface
    for token in route_tokens:
        ts = str(token)
        if 'NPF_' in ts or ts.startswith('\\Device'):
            for iface in ifaces:
                if iface.guid == ts:
                    return iface
    return None


_ARP_IFACE_HEADER_RE = re.compile(
    # English "Interface:", DE "Schnittstelle:", ES "Interfaz:", FR often still
    # "Interface:" — match any header then IPv4 --- 0xIFINDEX.
    r'(?:interface|schnittstelle|interfaz)\s*:\s*'
    r'(\d{1,3}(?:\.\d{1,3}){3})\s*---\s*0x',
    re.IGNORECASE,
)


def _parse_windows_arp_by_interface() -> dict[str, set[str]]:
    """Map local interface IPv4 -> remote IPs listed under that ARP section."""
    if not sys.platform.startswith('win'):
        return {}
    text = terminal('arp -a') or ''
    result: dict[str, set[str]] = {}
    current_iface_ip = ''
    for raw in text.split('\n'):
        line = raw.strip()
        if not line:
            continue
        m = _ARP_IFACE_HEADER_RE.search(line)
        if m:
            current_iface_ip = m.group(1)
            result.setdefault(current_iface_ip, set())
            continue
        if not current_iface_ip:
            continue
        parts = line.split()
        if len(parts) >= 2 and _ipv4_valid(parts[0]):
            result.setdefault(current_iface_ip, set()).add(parts[0])
    return result


def _iface_for_victim_arp(victim_ip: str, ifaces) -> 'NetFace | None':
    """Pick the NIC whose OS ARP cache already lists this victim (Wi‑Fi vs Ethernet)."""
    victim_ip = str(victim_ip or '').strip()
    if not victim_ip or not ifaces:
        return None
    by_iface = _parse_windows_arp_by_interface()
    if not by_iface:
        return None
    for iface in ifaces:
        lip = _iface_live_ipv4(iface) or str(getattr(iface, 'ip', None) or '').strip()
        if lip and victim_ip in by_iface.get(lip, set()):
            return iface
    return None


def get_iface_for_victim_ip(victim_ip: str, fallback=None):
    """
    Pick the local NetFace Scapy would use to reach victim_ip (same subnet / route table).

    Use this when Settings points at one NIC (e.g. Ethernet) but the selected device is on
    another (e.g. mobile hotspot / ICS) so ARP + pf rules target the correct adapter.
    """
    if not _ipv4_valid(victim_ip) or victim_ip in ('0.0.0.0', '127.0.0.1'):
        return fallback if fallback is not None else get_default_iface()
    # Cached iface list keeps Kill ON snappy when a Wi-Fi/BT combo dongle inflates
    # ipconfig output (1–3 s parse). The cache is invalidated by Settings/Clumsy flows.
    try:
        ifaces = list(get_ifaces_cached())
    except Exception:
        ifaces = list(get_ifaces())
    if not ifaces:
        return fallback if fallback is not None else get_default_iface()

    # ARP cache first: when PC has Ethernet + Wi‑Fi on the same /24, the route
    # table often picks Ethernet while the victim (PS5 on Wi‑Fi) is only reachable
    # via the Wi‑Fi ARP segment — poisoning on the wrong NIC does nothing.
    arp_hit = _iface_for_victim_arp(victim_ip, ifaces)
    if arp_hit is not None:
        return arp_hit
    if fallback is not None:
        live_fb = _iface_live_ipv4(fallback)
        if live_fb and victim_ip in _parse_windows_arp_by_interface().get(live_fb, set()):
            return fallback

    def _route_iface(*, resync: bool = False):
        if resync:
            try:
                conf.route.resync()
            except Exception:
                pass
        try:
            rt = conf.route.route(victim_ip)
        except Exception:
            return None
        return _iface_for_route_tokens(rt, ifaces)

    # Route table first — authoritative when the PC hops Ethernet ↔ Wi‑Fi on the same /24.
    # The old /24 fast-accept on fallback.NetFace.ip kept using unplugged Ethernet after
    # switching to Wi‑Fi (stale 192.168.1.x on the cached object), so Lag/Kill sent no traffic.
    hit = _route_iface(resync=False)
    if hit is not None:
        # Same /24: prefer Settings/fallback only when the victim is on that NIC's ARP
        # segment. Blindly preferring fallback broke Kill on dual-homed PCs (Ethernet +
        # Wi‑Fi on 192.168.1.x) when the PS5 was only reachable via Wi‑Fi.
        try:
            if fallback is not None:
                live_fb = _iface_live_ipv4(fallback)
                plen = iface_ipv4_prefix_len(fallback, default=24)
                if (
                    live_fb
                    and ipv4_same_link(live_fb, victim_ip, prefix_len=plen)
                    and str(hit.guid) != str(fallback.guid)
                ):
                    by_iface = _parse_windows_arp_by_interface()
                    if live_fb and victim_ip in by_iface.get(live_fb, set()):
                        return fallback
        except Exception:
            pass
        return hit
    hit = _route_iface(resync=True)
    if hit is not None:
        return hit

    # Fast accept only when fallback still has a live address on the victim's link.
    try:
        if fallback is not None:
            live_ip = _iface_live_ipv4(fallback)
            if live_ip:
                plen = iface_ipv4_prefix_len(fallback, default=24)
                if ipv4_same_link(live_ip, victim_ip, prefix_len=plen):
                    return fallback
    except Exception:
        pass

    # Fallback #1: longest-prefix match from full route table.
    try:
        victim_addr = ipaddress.IPv4Address(victim_ip)
    except Exception:
        return fallback if fallback is not None else get_default_iface()
    best_route = None
    best_prefix = -1
    try:
        for entry in getattr(conf.route, 'routes', []):
            if len(entry) < 4:
                continue
            net = _network_for_route(entry)
            if not net or victim_addr not in net:
                continue
            prefix = int(net.prefixlen)
            if prefix <= best_prefix:
                continue
            iface_token = str(entry[3])
            for iface in ifaces:
                if iface.guid == iface_token:
                    best_route = iface
                    best_prefix = prefix
                    break
        if best_route is not None:
            return best_route
    except Exception:
        pass

    # Fallback #2: same on-link subnet as a live interface (hotspot / odd routes).
    # Prefer the interface's real prefix; keep /24 as the unknown-mask default.
    for iface in ifaces:
        ip = _iface_live_ipv4(iface)
        if not ip or ip in ('0.0.0.0', '127.0.0.1'):
            continue
        plen = iface_ipv4_prefix_len(iface, default=24)
        if ipv4_same_link(ip, victim_ip, prefix_len=plen):
            return iface

    if fallback is not None and _iface_live_ipv4(fallback):
        return fallback
    return ifaces[0] if ifaces else get_default_iface()


def pick_best_live_iface():
    """Return the best connected LAN adapter for Settings (live IP, usable MAC, not APIPA)."""
    ifaces = list(get_ifaces_cached())
    if not ifaces:
        ifaces = list(get_ifaces())
    best = None
    best_score = -1
    for iface in ifaces:
        if _iface_looks_softap(iface) and not _softap_bind_allowed():
            continue
        lip = _iface_live_ipv4(iface)
        if not lip or lip.startswith('169.254.') or not mac_address_is_usable(iface.mac):
            continue
        score = 0
        if not _is_bad_iface_display_name(iface.name):
            score += 10
        # Soft deprioritize VPN/TAP/Hyper-V so full-tunnel default routes do not
        # steal auto-pick from the physical LAN NIC (ARP MITM needs L2).
        if _iface_looks_vpn_or_virtual(iface):
            score -= 80
        try:
            rt = conf.route.route('0.0.0.0')
            for token in rt or ():
                if str(token) == str(iface.guid):
                    score += 100
                    break
        except Exception:
            pass
        if score > best_score:
            best_score = score
            best = iface
    if best is not None:
        return best
    for iface in ifaces:
        if _iface_live_ipv4(iface) and mac_address_is_usable(iface.mac):
            return iface
    return ifaces[0] if ifaces else NetFace(DUMMY_IFACE)


def repair_saved_iface_name(saved: str) -> str:
    """Map broken Settings labels / ghost bindings to the live default-route NIC."""
    name = str(saved or '').strip()
    if (
        not name
        or name == 'NULL'
        or _is_bad_iface_display_name(name)
        or (_iface_name_looks_softap(name) and not _softap_bind_allowed())
    ):
        invalidate_ifaces_cache(full=True)
        best = pick_best_live_iface()
        if best is not None and best.name != 'NULL' and _iface_live_ipv4(best):
            return best.name
        for iface in get_ifaces():
            lip = _iface_live_ipv4(iface)
            if lip and mac_address_is_usable(iface.mac):
                return iface.name
        return name

    invalidate_ifaces_cache(full=True)
    ifaces = list(get_ifaces())
    for iface in ifaces:
        if iface.name != name:
            continue
        if mac_address_is_usable(iface.mac) and _iface_live_ipv4(iface):
            return name

    # Saved adapter disconnected or ghost — remap by last known IP, else default route.
    want_ip = ''
    for iface in ifaces:
        if iface.name == name:
            want_ip = str(getattr(iface, 'ip', None) or '').strip()
            break
    if want_ip and _ip_ok_for_bind(want_ip):
        for iface in ifaces:
            lip = _iface_live_ipv4(iface) or str(getattr(iface, 'ip', None) or '').strip()
            if lip == want_ip and _ip_ok_for_bind(lip) and mac_address_is_usable(iface.mac):
                return iface.name
    best = pick_best_live_iface()
    if best is not None and best.name != 'NULL' and _iface_live_ipv4(best):
        return best.name
    for iface in ifaces:
        lip = _iface_live_ipv4(iface)
        if lip and mac_address_is_usable(iface.mac):
            return iface.name
    return name


def repair_nickname_last_ips_from_arp(nickname_last_ip: dict, nicknames: dict) -> dict:
    """Refresh saved last-IP map from the OS ARP table (PS5 moved .165 → .248)."""
    try:
        from networking.nicknames import nickname_profile_key, parse_nickname_profile_key
    except Exception:
        return dict(nickname_last_ip or {})
    last = dict(nickname_last_ip or {})
    iface = pick_best_live_iface()
    iface_ip = _iface_live_ipv4(iface) or str(getattr(iface, 'ip', None) or '')
    keys = set(last.keys()) | {str(k) for k in (nicknames or {})}
    for key in list(keys):
        mac, _pfx = parse_nickname_profile_key(str(key))
        if not mac:
            continue
        try:
            arp_ip = lookup_ip_from_arp_table(mac, iface_ip)
        except Exception:
            arp_ip = ''
        if arp_ip and _ipv4_valid(arp_ip):
            pk = nickname_profile_key(mac, arp_ip)
            if pk:
                last[pk] = arp_ip
            if str(key) in last and str(key) != pk:
                del last[str(key)]
            continue
        stored = str(last.get(str(key)) or '').strip()
        if not stored:
            continue
        try:
            owner = lookup_mac_from_arp_table(stored, iface_ip)
        except Exception:
            owner = ''
        # Only drop when forward ARP proves another device owns this IP. An empty
        # cache at cold start is not evidence — wiping here hid nicknamed rows until scan.
        if mac_address_is_usable(owner) and owner != mac:
            del last[str(key)]
    return last


def reconcile_scanner_with_settings_iface(scanner, killer=None) -> str:
    """
    Align scanner Me/Router with the adapter saved in Settings.

    When only one Npcap binding exists, pin settings to it (stale ghost NPF names
    make Settings label IP disagree with the Me row). Returns a short user hint
    when something was corrected (empty if unchanged).
    """
    try:
        from tools.utils_gui import get_settings, set_settings
    except Exception:
        return ''

    ifaces = list(get_ifaces_cached())
    if not ifaces:
        ifaces = list(get_ifaces())

    saved = str(get_settings('iface') or '').strip()
    try:
        repaired = repair_saved_iface_name(saved)
        if repaired and repaired != saved:
            set_settings('iface', repaired)
            saved = repaired
    except Exception:
        pass
    if len(ifaces) == 1:
        only = ifaces[0]
        # Do not pin Settings to a leftover hotspot NIC when Clumsy is off —
        # that is the "Network Interface stuck on 10" bug.
        if not (_iface_looks_softap(only) and not _softap_bind_allowed()):
            refresh_netface_live_ip(only)
            if only.name and only.name != 'NULL' and saved != only.name:
                set_settings('iface', only.name)
                saved = only.name

    picked = get_iface_by_name(saved) if saved else None
    if picked is None or picked.name == 'NULL':
        picked = pick_best_live_iface()
    if picked is None or picked.name == 'NULL':
        return ''

    me_before = str(getattr(scanner, 'my_ip', None) or '').strip()
    old_name = str(getattr(getattr(scanner, 'iface', None), 'name', None) or '').strip()

    scanner.iface = picked
    refresh_netface_live_ip(picked)
    if killer is not None:
        killer.iface = picked
        try:
            killer.router = getattr(scanner, 'router', None) or killer.router
        except Exception:
            pass

    try:
        # Called from startup/settings paths — avoid getmacbyip (~4s) stalls.
        scanner.refresh_local_topology(allow_scapy_probe=False)
        scanner.add_me()
        scanner.add_router()
    except Exception:
        pass

    me_after = str(getattr(scanner, 'my_ip', None) or '').strip()
    label_ip = _iface_live_ipv4(picked) or str(getattr(picked, 'ip', None) or '').strip()
    hints: list[str] = []
    if saved and picked.name and saved != picked.name:
        set_settings('iface', picked.name)
        hints.append('saved network adapter name was updated')
    if old_name and old_name != picked.name:
        hints.append(f'using adapter for Me row ({me_after or label_ip or picked.name})')
    elif me_before and me_after and me_before != me_after:
        hints.append(f'Me row updated to {me_after}')
    if me_after and label_ip and me_after != label_ip:
        hints.append(
            f'Me is {me_after} but adapter shows {label_ip} — reconnect Wi‑Fi and Arp Scan'
        )
    return '; '.join(hints)


def resolve_settings_iface_name(saved: str) -> str:
    """
    Map stored Settings iface name to a live adapter.

    After Driver Easy / Npcap reinstall, settings may still reference a ghost
    NPF binding (FF:FF:FF:FF:FF:FF MAC) that no longer captures traffic.
    """
    name = str(saved or '').strip()
    if not name or name == 'NULL':
        return name
    if _is_bad_iface_display_name(name) or (
        _iface_name_looks_softap(name) and not _softap_bind_allowed()
    ):
        name = ''
    ifaces = list(get_ifaces_cached())
    want_ip = ''
    for iface in ifaces:
        if iface.name != name:
            continue
        if mac_address_is_usable(iface.mac) and _iface_live_ipv4(iface):
            return name
        want_ip = str(getattr(iface, 'ip', None) or '').strip()
        break
    if want_ip and _ip_ok_for_bind(want_ip):
        for iface in ifaces:
            lip = _iface_live_ipv4(iface) or str(getattr(iface, 'ip', None) or '').strip()
            if lip == want_ip and _ip_ok_for_bind(lip) and mac_address_is_usable(iface.mac):
                return iface.name
    best = pick_best_live_iface()
    if best is not None and best.name != 'NULL' and _iface_live_ipv4(best):
        return best.name
    return name


def get_iface_by_name(name):
    """
    Return interface given its name
    """
    if not name or str(name).strip() == '' or name == 'NULL':
        return get_default_iface()
    name = resolve_settings_iface_name(str(name).strip())
    ifaces = list(get_ifaces())
    chosen = None
    for iface in ifaces:
        if iface.name == name:
            chosen = iface
            break
    if chosen is None:
        want_guid = _extract_adapter_guid(name)
        if want_guid:
            for iface in ifaces:
                got = _extract_adapter_guid(
                    str(getattr(iface, 'guid', '') or '') or iface.name
                )
                if got == want_guid:
                    chosen = iface
                    break
    if chosen is None:
        for sep in ('\u2014', '\u2013'):
            if sep in name:
                stem = name.split(sep, 1)[0].strip()
                if stem and stem != name:
                    for iface in ifaces:
                        if iface.name == stem:
                            chosen = iface
                            break
            if chosen is not None:
                break
    if chosen is None:
        chosen = get_default_iface()
    refresh_netface_live_ip(chosen)
    if not _iface_live_ipv4(chosen) or (
        _iface_looks_softap(chosen) and not _softap_bind_allowed()
    ):
        live = pick_best_live_iface()
        if live is not None and live.name != 'NULL' and _iface_live_ipv4(live):
            return live
        live = _pick_first_live_iface(ifaces)
        if live is not None:
            return live
    return chosen

def is_connected(current_iface=None):
    """
    Checks if there are any IPs in Default Gateway sections
    """
    if current_iface is None:
        current_iface = get_default_iface()
    
    if current_iface.name == 'NULL':
        # Try to get a valid interface
        current_iface = get_default_iface()
        if current_iface.name == 'NULL':
            # Last resort: check if we have any network connectivity
            try:
                socket().connect(('8.8.8.8', 53))
                return True
            except Exception:
                return False

    if sys.platform.startswith('win'):
        from tools.win_locale import ipconfig_gateway_findstr_command

        ipconfig_output = terminal(ipconfig_gateway_findstr_command())
        if ipconfig_output and ipconfig_output.strip():
            if re.search(r'\d{1,3}(?:\.\d{1,3}){3}', ipconfig_output):
                return True
        # Fallback: check if interface has a valid IP
        if current_iface.ip and current_iface.ip != '0.0.0.0' and current_iface.ip != '127.0.0.1':
            return True

    # Fallback: try socket connection test
    try:
        s = socket()
        s.settimeout(1)
        s.connect(('8.8.8.8', 53))
        s.close()
        return True
    except Exception:
        pass
    
    return False
