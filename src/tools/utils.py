import os
import subprocess
from scapy.all import conf, get_if_list
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


def run_command(command, *, shell=True, timeout=None, check=False):
    """
    Run a subprocess without flashing cmd.exe / PowerShell on Windows.

    String commands with shell=True use ``cmd.exe /d /c`` (not COMSPEC) so PCs
    with COMSPEC pointing at PowerShell do not spawn a visible console per call.
    """
    kwargs = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        'text': True,
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
    t = (s or '').strip().lower()
    if not t:
        return True
    if t == 'description' or t.startswith('description'):
        return True
    if t in ('connected', 'disconnected', 'enabled', 'disabled', 'dedicated'):
        return True
    if re.match(r'^interface-\d+$', t):
        return True
    return False


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

def get_my_ip(iface_name):
    """
    Get interface IP address (cross-platform)
    iface_name must be the Scapy/pcap name (e.g., \\Device\\NPF_{GUID} on Windows, en0 on macOS)
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

    try:
        for entry in conf.route.routes:
            if len(entry) >= 5:
                dst, mask, gw, iface, src_ip = entry[:5]
                # Prefer matches for our interface
                if iface_name and iface != iface_name:
                    continue
                if gw in invalid_gws:
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

    return chosen_gw or '0.0.0.0'

def get_gateway_mac(iface_ip, router_ip):
    if sys.platform.startswith('win'):
        # Windows: try ARP table lookup
        if iface_ip and iface_ip != '127.0.0.1':
            response = terminal(f'arp -a {router_ip} -N {iface_ip}')
        else:
            response = terminal(f'arp -a {router_ip}')
        
        if response:
            # Parse Windows ARP output: "  IP_ADDRESS      MAC_ADDRESS      TYPE"
            for line in response.split('\n'):
                line = line.strip()
                if not line or 'Interface:' in line:
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
    # Fallback: actively resolve via scapy
    try:
        from scapy.all import getmacbyip
        mac = getmacbyip(router_ip)
        if mac:
            return good_mac(mac)
    except Exception:
        pass
    return GLOBAL_MAC


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
            for line in response.split('\n'):
                line = line.strip()
                if not line or 'Interface:' in line:
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
                text = str(out or '').lower()
                if 'ttl=' in text and 'unreachable' not in text and 'timed out' not in text:
                    return True
            else:
                out = run_command(
                    ['ping', '-c', '1', '-W', str(max(1, int(timeout_ms / 1000))), ip],
                    shell=False,
                    timeout=max(2, int(timeout_ms / 1000) + 1),
                )
                text = str(out or '').lower()
                if 'ttl=' in text or 'time=' in text:
                    return True
        except Exception:
            pass
        if n + 1 < tries:
            time.sleep(0.12)
    return False


def victim_endpoint_live_for_mitm(
    ip: str, expected_mac: str, iface_ip: str | None = None, *, ping_attempts: int = 3
) -> tuple[bool, str]:
    """
    PS5 Ethernet vs Wi‑Fi rows use different MACs — do not MITM a ghost favorite IP.
    Pings up to ``ping_attempts`` times; if ICMP is silent but ARP still maps this IP
    to ``expected_mac`` (and the MAC has not moved to another IP), treat as live.
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

    ping_tries = max(1, int(ping_attempts))
    ping_wait = 300 if ping_tries <= 1 else 500
    if not ipv4_ping_reachable(ip, attempts=ping_tries, timeout_ms=ping_wait):
        arp_mac = lookup_mac_from_arp_table(ip, iface_ip)
        if (
            expected_mac
            and mac_address_is_usable(arp_mac)
            and arp_mac == expected_mac
            and (not live_ip or live_ip == ip)
        ):
            return True, ''
        if live_ip and live_ip != ip:
            return (
                False,
                f'{ip} is offline — this device is now at {live_ip}. Rescan and use that row.',
            )
        return (
            False,
            f'{ip} did not answer ping — wake the PS5, rescan, and pick the live row '
            f'(Settings Wi‑Fi is OK if ipconfig matches Me).',
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
        dev.get('ip'), dev.get('mac'), iface_ip or None, ping_attempts=3
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
            for line in response.split('\n'):
                line = line.strip()
                if not line or 'Interface:' in line or 'Internet Address' in line:
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
                # Look for adapter name: "Ethernet adapter Ethernet:" (works for localized outputs too)
                if 'adapter' in line.lower() and ':' in line:
                    # Extract adapter name (text before the colon)
                    adapter_name = line.split(':', 1)[0].split()[-1]
                    if adapter_name:
                        current_adapter = line.split(':', 1)[0].split('adapter')[-1].strip(' :')
                        if not current_adapter:
                            current_adapter = adapter_name
                        interface_map[current_adapter] = {'ip': '0.0.0.0', 'mac': GLOBAL_MAC, 'guid': None}
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
                        # Take the last token as interface name (works for many locales)
                        friendly_parts = friendly.split()
                        if friendly_parts:
                            friendly = friendly_parts[-1]
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

            # Drop useless netsh/ipconfig labels (no PowerShell Get-NetAdapter: avoids spawning
            # powershell.exe on every refresh; ipconfig + MAC match remains the source of truth).
            if friendly_name and _is_bad_iface_display_name(friendly_name):
                friendly_name = None
            if not friendly_name and guid:
                friendly_name = guid_names.get(_guid_lookup_key(guid))

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

            # If we have a MAC, attempt to match friendly names from ipconfig
            if not friendly_name and scapy_mac:
                for friendly, info in interface_map.items():
                    if info['mac'] != GLOBAL_MAC and good_mac(info['mac']) == good_mac(scapy_mac):
                        friendly_name = friendly
                        if info['ip'] not in ('0.0.0.0', '127.0.0.1'):
                            ip = info['ip']
                            found_ip = True
                        break
            
            # Fallback: try to get IP from scapy route table (always try this as fallback)
            if not found_ip:
                # Method 1: Try default route for this iface (ignore TypeError on newer scapy)
                try:
                    route_result = conf.route.route("0.0.0.0", iface=scapy_name)
                    if route_result and len(route_result) > 1:
                        potential_ip = route_result[1]
                        if potential_ip and potential_ip not in ('0.0.0.0', '127.0.0.1'):
                            ip = _prefer_ipv4(ip, potential_ip)
                            found_ip = True
                except TypeError:
                    # Newer scapy versions do not accept iface kwarg
                    pass
                except Exception:
                    pass

                # Method 2: Check all routes for this interface
                if not found_ip:
                    try:
                        for route in conf.route.routes:
                            # Route format: (dst, mask, gw, iface, ip)
                            if len(route) >= 5 and route[3] == scapy_name:
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
            
            # Final fallback: use get_my_ip with the Scapy name directly
            if not found_ip or ip == '0.0.0.0':
                try:
                    potential_ip = get_my_ip(scapy_name)
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
                if mac_address_is_usable(mac):
                    yield face
                continue
            # Skip ghost Npcap bindings (00:00… / FF:FF…) that share a live LAN IP with a real NIC.
            if not mac_address_is_usable(mac):
                continue
            # Disconnected adapters (Bluetooth, unplugged Ethernet) often show APIPA only —
            # do not treat them as the active LAN NIC (breaks Lag/Kill MITM on Wi‑Fi).
            if not _ipv4_usable_for_lan(lip):
                continue
            prev = best_by_ip.get(lip)
            if prev is None:
                best_by_ip[lip] = face
            elif mac_address_is_usable(mac) and not mac_address_is_usable(prev.mac):
                best_by_ip[lip] = face
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


def _ipconfig_line_is_host_ipv4(line: str) -> bool:
    """True only for adapter IPv4 assignment lines — not gateway/DNS/mask."""
    low = (line or '').lower()
    if any(
        token in low
        for token in (
            'gateway',
            'dhcp server',
            'dns',
            'wins',
            'mask',
            'subnet',
            'route',
        )
    ):
        return False
    return any(
        token in low
        for token in (
            'ipv4 address',
            'ip address',
            'ip-adresse',
            'adresse ipv4',
            'indirizzo ipv4',
        )
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


def resolve_iface_my_ip(iface) -> str:
    """Best IPv4 for scanner Me/router topology — DHCP LAN over APIPA."""
    refresh_netface_live_ip(iface)
    guid = str(getattr(iface, 'guid', None) or '').strip()
    ip = str(get_my_ip(guid) if guid else '') or ''
    cached = str(getattr(iface, 'ip', None) or '').strip()
    if _ipv4_usable_for_lan(ip):
        return ip
    if _ipv4_usable_for_lan(cached):
        return cached
    return ip if _ipv4_valid(ip) else cached


def _pick_first_live_iface(ifaces):
    for iface in ifaces:
        refresh_netface_live_ip(iface)
        if _iface_live_ipv4(iface):
            return iface
    return None


def _iface_live_ipv4(iface) -> str:
    """Current IPv4 on this Npcap iface (not the stale NetFace.ip cache)."""
    guid = str(getattr(iface, 'guid', None) or '').strip()
    if not guid:
        return ''
    try:
        ip = str(get_my_ip(guid) or '').strip()
    except Exception:
        return ''
    if ip in ('0.0.0.0', '127.0.0.1') or not _ipv4_usable_for_lan(ip):
        return ''
    return ip


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
        low = line.lower()
        if low.startswith('interface:'):
            parts = line.split()
            current_iface_ip = parts[1] if len(parts) >= 2 else ''
            if current_iface_ip:
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
        # Same /24: prefer Settings/fallback when route picked a different NIC.
        try:
            if fallback is not None:
                live_fb = _iface_live_ipv4(fallback)
                v_oct = [int(x) for x in victim_ip.split('.')]
                f_oct = [int(x) for x in live_fb.split('.')] if live_fb else []
                if (
                    len(v_oct) == 4
                    and len(f_oct) == 4
                    and v_oct[:3] == f_oct[:3]
                    and str(hit.guid) != str(fallback.guid)
                ):
                    return fallback
        except Exception:
            pass
        return hit
    hit = _route_iface(resync=True)
    if hit is not None:
        return hit

    # Fast accept only when fallback still has a live address on the victim's /24.
    try:
        if fallback is not None:
            live_ip = _iface_live_ipv4(fallback)
            if live_ip:
                f_oct = [int(x) for x in live_ip.split('.')]
                v_oct = [int(x) for x in victim_ip.split('.')]
                if len(f_oct) == 4 and len(v_oct) == 4 and f_oct[:3] == v_oct[:3]:
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

    # Fallback #2: same /24 as a live interface (hotspot clients, odd route tables).
    try:
        v_oct = [int(x) for x in victim_ip.split('.')]
    except ValueError:
        return fallback if fallback is not None else get_default_iface()
    for iface in ifaces:
        ip = _iface_live_ipv4(iface)
        if not ip or ip in ('0.0.0.0', '127.0.0.1'):
            continue
        try:
            a = [int(x) for x in ip.split('.')]
        except ValueError:
            continue
        if len(a) == 4 and len(v_oct) == 4 and a[:3] == v_oct[:3]:
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
        lip = _iface_live_ipv4(iface)
        if not lip or lip.startswith('169.254.') or not mac_address_is_usable(iface.mac):
            continue
        score = 0
        if not _is_bad_iface_display_name(iface.name):
            score += 10
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
    if not name or name == 'NULL' or _is_bad_iface_display_name(name):
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
    if want_ip and _ipv4_usable_for_lan(want_ip):
        for iface in ifaces:
            lip = _iface_live_ipv4(iface) or str(getattr(iface, 'ip', None) or '').strip()
            if lip == want_ip and mac_address_is_usable(iface.mac):
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


def resolve_settings_iface_name(saved: str) -> str:
    """
    Map stored Settings iface name to a live adapter.

    After Driver Easy / Npcap reinstall, settings may still reference a ghost
    NPF binding (FF:FF:FF:FF:FF:FF MAC) that no longer captures traffic.
    """
    name = str(saved or '').strip()
    if not name or name == 'NULL':
        return name
    if _is_bad_iface_display_name(name):
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
    if want_ip and _ipv4_usable_for_lan(want_ip):
        for iface in ifaces:
            lip = _iface_live_ipv4(iface) or str(getattr(iface, 'ip', None) or '').strip()
            if lip == want_ip and mac_address_is_usable(iface.mac):
                return iface.name
    if not name:
        best = pick_best_live_iface()
        return best.name if best and best.name != 'NULL' else ''
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
    if not _iface_live_ipv4(chosen):
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
        # Windows: check for default gateway via ipconfig
        ipconfig_output = terminal('ipconfig | findstr /i gateway')
        if ipconfig_output and ipconfig_output.strip():
            # Check if output contains IP addresses (digits with dots)
            if any(c.isdigit() for c in ipconfig_output):
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
