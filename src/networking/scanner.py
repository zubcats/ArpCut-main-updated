from concurrent.futures.thread import ThreadPoolExecutor
import os
import threading
from scapy.all import Ether, arping, conf, get_if_addr
from time import sleep
import re
import sys
from typing import Optional

from networking.nicknames import (
    Nicknames,
    get_nicknames_dict,
    get_nickname_last_ip_map,
    ipv4_subnet_prefix,
    nickname_profile_key,
    parse_nickname_profile_key,
    record_nickname_last_ip,
    resolve_favorite_ip,
    stale_nickname_favorite_should_skip,
)
from tools.device_display import infer_network_device_type
from networking.device_table import (
    build_client_rows_from_scan,
    extra_scan_hits_from_ics_arp,
    phantom_favorite_should_skip,
    sync_device_table,
)
from tools.clumsy_inline import clumsy_mode_enabled
from tools.utils import *
from tools.utils import _iface_live_ipv4  # star-import skips private names; sync_iface needs this
from constants import *

class Scanner():
    def __init__(self):
        self.iface = get_default_iface()
        self.device_count = 25
        self.max_threads = 12
        self.__ping_done = 0
        self.__ping_done_lock = threading.Lock()
        self.devices = []
        self.old_ips = {}
        self.router = {}
        self.ips = []
        self.me = {}
        self.perfix = None
        self.qt_progress_signal = int
        self.qt_log_signal = print
    
    def generate_ips(self):
        try:
            n = int(self.device_count)
        except (TypeError, ValueError):
            n = 25
        n = max(1, min(255, n))
        self.ips = [f'{self.perfix}.{i}' for i in range(1, n)]

    def init(self):
        """
        Intializing Scanner
        """
        try:
            from tools.utils_gui import get_settings

            saved = str(get_settings('iface') or '').strip()
            if saved and saved != 'NULL':
                self.iface = get_iface_by_name(saved)
            else:
                self.iface = get_iface_by_name(self.iface.name)
        except Exception:
            self.iface = get_iface_by_name(self.iface.name)
        self.devices = []

        # Use iface.guid (Scapy/pcap name) for network operations, not iface.name
        self.router_ip = get_gateway_ip(self.iface.guid)
        # Startup init — skip getmacbyip; warm/Kill paths refresh router MAC from ARP.
        self.router_mac = get_gateway_mac(
            self.iface.ip, self.router_ip, allow_scapy_probe=False
        )

        self.my_ip = resolve_iface_my_ip(self.iface)
        self.my_mac = good_mac(self.iface.mac)
        
        self.perfix = self.my_ip.rsplit(".", 1)[0]
        self.generate_ips()

    def sync_iface_for_victim_ip(self, victim_ip: str) -> bool:
        """
        If victim_ip is on a different local interface than self.iface, rebind scanner
        topology (gateway, me, router dict) so Killer/ARP/firewall use the right NIC.
        """
        target = get_iface_for_victim_ip(victim_ip, fallback=self.iface)
        refresh_netface_live_ip(target)
        live_here = _iface_live_ipv4(self.iface)
        live_target = _iface_live_ipv4(target)
        if str(target.guid) == str(self.iface.guid) and live_here:
            refresh_netface_live_ip(self.iface)
            return False
        if str(target.guid) == str(self.iface.guid) and not live_target:
            return False
        self.iface = target
        refresh_netface_live_ip(self.iface)
        self.router_ip = get_gateway_ip(self.iface.guid)
        # GUI/Kill paths call this — never fall through to getmacbyip (~4s).
        self.router_mac = get_gateway_mac(
            self.iface.ip, self.router_ip, allow_scapy_probe=False
        )
        self.my_ip = resolve_iface_my_ip(self.iface)
        self.my_mac = good_mac(self.iface.mac)
        if self.my_ip:
            self.iface.ip = self.my_ip
        try:
            self.perfix = self.my_ip.rsplit(".", 1)[0]
        except Exception:
            pass
        self.generate_ips()
        self.router = {
            'ip': self.router_ip,
            'mac': self.router_mac,
            'vendor': get_vendor(self.router_mac),
            'type': 'Router',
            'name': '',
            'admin': True,
        }
        self.me = {
            'ip': self.my_ip,
            'mac': self.my_mac,
            'vendor': get_vendor(self.my_mac),
            'type': 'Me',
            'name': '',
            'admin': True,
        }
        for row in self.devices:
            t = row.get('type')
            if t == 'Router':
                row['ip'] = self.router_ip
                row['mac'] = self.router_mac
                row['vendor'] = get_vendor(self.router_mac)
            elif t == 'Me':
                row['ip'] = self.my_ip
                row['mac'] = self.my_mac
                row['vendor'] = get_vendor(self.my_mac)
        return True

    def refresh_local_topology(self, *, allow_scapy_probe: bool = True) -> None:
        """
        Re-read gateway and local addresses on the current iface without changing NIC.
        Clumsy enable/repair + restart do this implicitly; Kill/Lag need it on every arm.

        ``allow_scapy_probe=False`` skips getmacbyip (~4s) — use on GUI paint paths.
        """
        guid = getattr(self.iface, 'guid', None) or getattr(self.iface, 'name', None)
        if not guid or guid == 'NULL':
            return
        refresh_netface_live_ip(self.iface)
        self.my_ip = resolve_iface_my_ip(self.iface)
        self.my_mac = good_mac(self.iface.mac)
        if self.my_ip:
            self.iface.ip = self.my_ip
        self.router_ip = get_gateway_ip(guid)
        self.router_mac = get_gateway_mac(
            self.my_ip or self.iface.ip,
            self.router_ip,
            allow_scapy_probe=allow_scapy_probe,
        )
        try:
            self.perfix = self.my_ip.rsplit('.', 1)[0]
        except Exception:
            pass
        self.router = {
            'ip': self.router_ip,
            'mac': self.router_mac,
            'vendor': get_vendor(self.router_mac),
            'type': 'Router',
            'name': '',
            'admin': True,
        }
        self.me = {
            'ip': self.my_ip,
            'mac': self.my_mac,
            'vendor': get_vendor(self.my_mac),
            'type': 'Me',
            'name': '',
            'admin': True,
        }
        for row in self.devices:
            t = row.get('type')
            if t == 'Router':
                row['ip'] = self.router_ip
                row['mac'] = self.router_mac
                row['vendor'] = get_vendor(self.router_mac)
            elif t == 'Me':
                row['ip'] = self.my_ip
                row['mac'] = self.my_mac
                row['vendor'] = get_vendor(self.my_mac)

    def flush_arp(self):
        """
        Flush ARP cache
        """
        try:
            from tools.clumsy_inline import hotspot_arp_cache_sensitive

            if hotspot_arp_cache_sensitive(self):
                return
        except Exception:
            pass
        if sys.platform.startswith('win'):
            arp_cmd = terminal('arp -d *')
            if arp_cmd and 'The parameter is incorrect' in arp_cmd:
                terminal('netsh interface ip delete arpcache')
        else:
            # macOS/Linux: flush ARP cache may require sudo; best-effort noop
            terminal('arp -a > /dev/null | cat')

    def add_me(self):
        """
        Get My info and append to self.devices
        """
        self.me = {
            'ip':       self.my_ip,
            'mac':      self.my_mac,
            'vendor':   get_vendor(self.my_mac),
            'type':     'Me',
            'name':     '',
            'admin':    True
        }
        for i, row in enumerate(self.devices):
            if isinstance(row, dict) and row.get('type') == 'Me':
                self.devices[i] = dict(self.me)
                return
        self.devices.insert(0, self.me)

    def add_router(self):
        """
        Get Gateway info and append to self.devices
        """
        self.router = {
            'ip':       self.router_ip,
            'mac':      self.router_mac,
            'vendor':   get_vendor(self.router_mac),
            'type':     'Router',
            'name':     '',
            'admin':    True
        }
        for i, row in enumerate(self.devices):
            if isinstance(row, dict) and row.get('type') == 'Router':
                self.devices[i] = dict(self.router)
                return
        self.devices.insert(0, self.router)

    def inject_nicknamed_favorites(self):
        """
        Insert nicknamed devices that were not in the latest scan, using the last known IPv4
        from settings so they still appear after restart (until a scan finds them again).
        """
        nick_db = get_nicknames_dict()
        if not nick_db:
            return
        last_map = get_nickname_last_ip_map()
        iface_ip = str(getattr(getattr(self, 'iface', None), 'ip', None) or '').strip()
        present_profiles = set()
        for d in self.devices:
            if not isinstance(d, dict) or d.get('admin'):
                continue
            mac = good_mac(d.get('mac'))
            ip = str(d.get('ip') or '').strip()
            if mac and ip:
                present_profiles.add(nickname_profile_key(mac, ip))
        to_add = []
        for key_raw, name in sorted(nick_db.items()):
            if not name or name == '-':
                continue
            mac, prefix = parse_nickname_profile_key(key_raw)
            if not mac:
                continue
            ip = resolve_favorite_ip(mac, key_raw, last_map, iface_ip)
            if not ip:
                continue
            if stale_nickname_favorite_should_skip(mac, ip, iface_ip):
                continue
            if not clumsy_mode_enabled():
                try:
                    from tools.clumsy_inline import clumsy_ics_downstream_prefix

                    if str(ip).startswith(clumsy_ics_downstream_prefix()):
                        continue
                except Exception:
                    pass
            pk = nickname_profile_key(mac, ip)
            if not pk or pk in present_profiles:
                continue
            if phantom_favorite_should_skip(self, mac, ip, present_profiles):
                continue
            if prefix and ipv4_subnet_prefix(ip) != prefix:
                continue
            parts = str(ip).split('.')
            if len(parts) != 4:
                continue
            try:
                if not all(0 <= int(x) <= 255 for x in parts):
                    continue
            except (TypeError, ValueError):
                continue
            present_profiles.add(pk)
            vend = get_vendor(mac)
            try:
                dev_type = infer_network_device_type(mac, vend, '')
            except Exception:
                dev_type = 'User'
            to_add.append(
                {
                    'ip': ip,
                    'mac': mac,
                    'vendor': vend,
                    'type': dev_type,
                    'name': name,
                    'admin': False,
                }
            )
        insert_at = 2 if len(self.devices) >= 2 else len(self.devices)
        for d in to_add:
            self.devices.insert(insert_at, d)
            insert_at += 1

    def devices_appender(self, scan_result):
        """
        Append scan results to self.devices (MAC-centric table in Clumsy hotspot mode).
        """
        hits: list = list(scan_result or [])
        try:
            for pair in extra_scan_hits_from_ics_arp(self):
                if pair not in hits:
                    hits.append(pair)
        except Exception:
            pass
        self.devices = build_client_rows_from_scan(self, hits)

        self.old_ips = {
            nickname_profile_key(d['mac'], d['ip']): d['ip']
            for d in self.devices
            if not d.get('admin')
        }

        self.add_me()
        self.add_router()
        self.inject_nicknamed_favorites()
        self.old_ips = {
            nickname_profile_key(d['mac'], d['ip']): d['ip']
            for d in self.devices
            if not d.get('admin')
        }
        sync_device_table(self, allow_subnet_ping=True)

        # Clear arp cache to avoid duplicates next time
        if unique:
            self.flush_arp()

    def merge_client_hits(self, hits):
        """
        Add or update non-admin rows from probe result without discarding existing clients.
        Keeps Me/Router rows coherent via add_me/add_router.
        """
        if not hits:
            return
        admins = [d for d in self.devices if d.get('admin')]
        existing = [d for d in self.devices if not d.get('admin')]
        merged_hits = []
        seen = set()
        try:
            from networking.device_table import _home_lan_ip_for_row, _ics_prefix, _is_ics_ip

            ics_prefix = _ics_prefix()
        except Exception:
            # Prefer live SoftAP when device_table import fails mid-scan.
            try:
                from tools.clumsy_inline import clumsy_ics_downstream_prefix

                ics_prefix = clumsy_ics_downstream_prefix()
            except Exception:
                ics_prefix = '192.168.137.'
            _home_lan_ip_for_row = None
            _is_ics_ip = None
        for d in existing:
            mac = good_mac(d.get('mac'))
            if not mac:
                continue
            if clumsy_mode_enabled():
                ip = str(d.get('ip') or '').strip()
                if ip:
                    pair = (ip, mac)
                    if pair not in seen:
                        merged_hits.append(pair)
                        seen.add(pair)
            lan = str(d.get('lan_ip') or '').strip()
            if _home_lan_ip_for_row is not None:
                home = _home_lan_ip_for_row(d, ics_prefix)
                if home:
                    lan = home
            elif lan and _is_ics_ip and _is_ics_ip(lan, ics_prefix):
                lan = ''
            if not lan:
                ip = str(d.get('ip') or '').strip()
                if _is_ics_ip and _is_ics_ip(ip, ics_prefix):
                    ip = ''
                lan = ip
            if lan and (lan, mac) not in seen:
                merged_hits.append((lan, mac))
                seen.add((lan, mac))
        for ip, mac in hits:
            mac = good_mac(mac)
            if not mac:
                continue
            pair = (str(ip).strip(), mac)
            if pair not in seen:
                merged_hits.append(pair)
                seen.add(pair)
        self.devices = build_client_rows_from_scan(self, merged_hits)
        self.old_ips = {
            nickname_profile_key(d['mac'], d['ip']): d['ip']
            for d in self.devices
            if not d.get('admin')
        }
        self.add_me()
        self.add_router()
        self.inject_nicknamed_favorites()
        self.old_ips = {
            nickname_profile_key(d['mac'], d['ip']): d['ip']
            for d in self.devices
            if not d.get('admin')
        }
        sync_device_table(self, allow_subnet_ping=True)

    def _windows_arp_raw_text(self):
        """Merge interface-scoped and full ARP output (``-N`` often returns nothing on some builds)."""
        chunks = []
        my = (getattr(self, 'my_ip', None) or '').strip()
        if my and my not in ('127.0.0.1', '0.0.0.0'):
            scoped = terminal(f'arp -a -N {my}')
            if scoped and scoped.strip():
                chunks.append(scoped)
        full = terminal('arp -a')
        if full and full.strip():
            chunks.append(full)
        return '\n'.join(chunks)

    def _windows_parse_arp_table(self, text):
        """
        Parse ``arp -a`` output on any locale. Uses regex (not column order) and skips
        interface header lines (``Interface:`` / ``Schnittstelle:`` / ``--- 0x..`` rows).
        """
        if not text or not text.strip():
            return []
        pat_ip = re.compile(r'\b((?:\d{1,3}\.){3}\d{1,3})\b')
        pat_mac = re.compile(r'(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b', re.I)
        # "Interface: 192.168.1.10 --- 0x3" style (EN + many locales use same layout)
        hdr = re.compile(
            r'^.+\s*:\s*\d{1,3}(?:\.\d{1,3}){3}\s+---\s+0x[0-9a-f]+\s*$',
            re.I,
        )
        clean = []
        seen = set()
        pf = (getattr(self, 'perfix', None) or '').strip()
        my = (getattr(self, 'my_ip', None) or '').strip()
        restrict_subnet = (
            bool(pf)
            and not pf.startswith('127.')
            and my
            and my not in ('127.0.0.1', '0.0.0.0')
        )
        # ICS / Clumsy: my_ip is often 192.168.137.x so perfix becomes 192.168.137 — restricting
        # ARP rows to that prefix would hide every device on the main LAN (192.168.1.x, etc.).
        if restrict_subnet:
            try:
                if clumsy_mode_enabled():
                    restrict_subnet = False
                else:
                    # SoftAP up (137.x / 173.x) even when Clumsy mode is off — do not
                    # hide home-LAN ARP rows just because my_ip is the hotspot GW.
                    from tools.clumsy_inline import victim_on_clumsy_ics_subnet

                    if victim_on_clumsy_ics_subnet(my):
                        restrict_subnet = False
            except Exception:
                pass
        # Prefer live prefix length over hard /24 (perfix) so /23–/22 LANs
        # still surface devices when Scapy arping falls back to the OS ARP table.
        prefix_len = 24
        if restrict_subnet:
            try:
                from tools.utils import iface_ipv4_prefix_len, ipv4_same_link

                prefix_len = int(iface_ipv4_prefix_len(getattr(self, 'iface', None), default=24))
                prefix_len = max(16, min(30, prefix_len))
            except Exception:
                prefix_len = 24
        for raw in text.split('\n'):
            line = (raw or '').strip()
            if not line:
                continue
            low = line.lower()
            if 'interface:' in low:
                continue
            if hdr.match(line):
                continue
            # Header row with IP + --- 0x but no hardware MAC on the line
            if '---' in line and '0x' in low and pat_ip.search(line) and not pat_mac.search(line):
                continue
            m_ip = pat_ip.search(line)
            m_mac = pat_mac.search(line)
            if not m_ip or not m_mac:
                continue
            ip = m_ip.group(1)
            try:
                nums = ip.split('.')
                if len(nums) != 4 or not all(0 <= int(x) <= 255 for x in nums):
                    continue
            except (ValueError, TypeError):
                continue
            mac = good_mac(m_mac.group(0))
            if not mac or mac == GLOBAL_MAC:
                continue
            if restrict_subnet:
                try:
                    from tools.utils import ipv4_same_link

                    if not ipv4_same_link(my, ip, prefix_len=prefix_len):
                        continue
                except Exception:
                    if not ip.startswith(pf + '.'):
                        continue
            key = (ip, mac)
            if key in seen:
                continue
            seen.add(key)
            clean.append((ip, mac))
        return clean

    def arping_cache(self):
        """
        Showing system arp cache after pinging
        """
        # Correct scan result when working with specific interface
        if sys.platform.startswith('win'):
            scan_result = self._windows_arp_raw_text()
            if scan_result:
                # Locale type labels: EN dynamic/static, DE dynamisch, FR dynamique/statique,
                # ES dinámico/estático — prefer IP+MAC rows over English-only filters.
                row_re = re.compile(
                    r'\b(?:\d{1,3}\.){3}\d{1,3}\b.+(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}',
                    re.I,
                )
                lines_keep = [
                    l for l in scan_result.split('\n') if row_re.search(l or '')
                ]
                if lines_keep:
                    scan_result = '\n'.join(lines_keep)
        else:
            scan_result = terminal('arp -an')
        
        if not scan_result:
            print('ARP error has been caught!')
            self.devices_appender([])
            return

        if sys.platform.startswith('win'):
            clean_result = self._windows_parse_arp_table(scan_result)
        else:
            # macOS/Linux: parse lines like "? (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0 ..."
            lines = [l for l in scan_result.split('\n') if l.strip()]
            clean_result = []
            for line in lines:
                try:
                    ip = re.findall(r'\(([^)]+)\)', line)[0]
                    macs = re.findall(r'([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})', line)
                    if macs:
                        clean_result.append((ip, macs[0]))
                except Exception:
                    continue
        self.devices_appender(clean_result)
    
    def arp_scan(self):
        """
        Scan using Scapy arping method 
        """
        self.init()

        self.generate_ips()
        # Prefer the live interface prefix (not hard-coded /24) so /23+/22 LANs
        # still discover hosts. Cap arping breadth at /22 to avoid huge sweeps.
        try:
            from tools.utils import iface_ipv4_prefix_len

            plen = int(iface_ipv4_prefix_len(self.iface, default=24))
        except Exception:
            plen = 24
        plen = max(8, min(30, plen))
        # Cap breadth: prefixlen < 22 means a *wider* net (/16 etc.) — clamp to /22.
        # Ordinary /24 keeps plen=24 (not widened).
        if plen < 22:
            plen = 22
        # "0.0.0.0/xx" breaks discovery; fall back to the host subnet from our own IP.
        if self.router_ip and self.router_ip not in ('0.0.0.0', '127.0.0.1'):
            target = f"{self.router_ip}/{plen}"
        else:
            base = f"{self.perfix}.0" if self.perfix else (self.my_ip or '0.0.0.0')
            target = f"{base}/{plen}"
        try:
            scan_result = arping(
                target,
                iface=self.iface.guid,  # Use guid (Scapy/pcap name), not name
                verbose=0,
                timeout=2,
            )
            clean_result = [(i[1].psrc, i[1].src) for i in scan_result[0]]
        except Exception as e:
            print('arp_scan: arping failed:', e)
            clean_result = []

        # Always merge Windows ARP cache — sleepy PS5/consoles often miss a single
        # arping burst but already appear in `arp -a`. Previously we only fell back
        # when Scapy returned *zero* hits (router alone answers → fallback never ran).
        if sys.platform.startswith('win'):
            try:
                arp_text = self._windows_arp_raw_text() or ''
                arp_hits = self._windows_parse_arp_table(arp_text) if arp_text else []
                if arp_hits:
                    seen = set(clean_result)
                    for hit in arp_hits:
                        if hit not in seen:
                            clean_result.append(hit)
                            seen.add(hit)
            except Exception as e:
                print('arp_scan: ARP table merge failed:', e)

        if not clean_result and sys.platform.startswith('win'):
            try:
                self.arping_cache()
            except Exception as e:
                print('arp_scan: ARP table fallback failed:', e)
                self.devices_appender([])
            return

        self.devices_appender(clean_result)

    def ping_scan(self):
        """
        Ping all devices at once [CPU Killing function]
           (All Threads will run at the same tine)
        """
        self.init()
        with self.__ping_done_lock:
            self.__ping_done = 0
        
        self.generate_ips()
        total_ips = len(self.ips)
        self.ping_thread_pool()
        
        while True:
            with self.__ping_done_lock:
                done = self.__ping_done
            # Add a sleep to overcome High CPU usage
            sleep(.01)
            self.qt_progress_signal(done)
            if done >= total_ips:
                break
        
        return True
    
    @threaded
    def ping_thread_pool(self):
        """
        Control maximum threads running at once
        """
        n = len(self.ips)
        # Cap workers: hundreds of concurrent subprocess pings exhausts threads/handles on Windows.
        cap = min(self.max_threads, n, int(os.environ.get('ZUBCUT_PING_POOL_CAP', '96')))
        workers = max(1, cap)
        with ThreadPoolExecutor(workers) as executor:
            for ip in self.ips:
                executor.submit(self.ping, ip)

    def ping(self, ip):
        """
        Ping a specific ip with native command "ping -n"
        """
        if sys.platform.startswith('win'):
            terminal(f'ping -n 1 {ip}', decode=False)
        else:
            # macOS: -W is millis for some ping variants; use higher timeout via -t if available
            terminal(f'ping -c 1 {ip}', decode=False)
        with self.__ping_done_lock:
            self.__ping_done += 1

    def probe_ip(self, ip: str) -> Optional[tuple]:
        """
        Probe a specific IP using multiple methods; return (ip, mac) if discovered.
        Adds to ARP cache when possible. Best-effort cross-platform.
        """
        ip = (ip or '').strip()
        if not ip:
            return None
        # Ensure scanner is initialized
        if not hasattr(self, 'my_ip') or not self.my_ip or self.my_ip == '127.0.0.1':
            try:
                self.init()
            except Exception as e:
                print(f'Warning: Scanner init failed in probe_ip: {e}')
        
        # Validate interface
        if self.iface.name == 'NULL':
            print(f'Warning: Invalid interface for probe_ip({ip})')
            # Try to reinitialize interface
            try:
                from tools.utils import get_default_iface
                self.iface = get_default_iface()
                self.init()
            except Exception:
                pass
        
        try:
            # 1) Try scapy arping to /32 (requires admin on Windows)
            if self.iface.name != 'NULL':
                ans = arping(f"{ip}/32", iface=self.iface.guid, timeout=1, verbose=0)  # Use guid (Scapy/pcap name)
                rows = ans[0] if ans else []
                hits = [(r[1].psrc, r[1].src) for r in rows]
                if hits:
                    self.merge_client_hits(hits)
                    return hits[0]
        except Exception as e:
            # Scapy arping might fail on Windows without admin or Npcap
            pass

        # 2) ICMP ping fallback to populate ARP
        try:
            self.ping(ip)
        except Exception as e:
            print(f'Warning: Ping failed for {ip}: {e}')
        
        # Small delay to let ARP cache update (longer for Windows)
        from time import sleep
        sleep(0.55 if sys.platform.startswith('win') else 0.3)
        
        # 3) Parse ARP cache
        result = self.probe_ip_arp_cache_only(ip)
        if result:
            return result

        # 4) TCP SYN to common ports to stimulate ARP (gaming/HTTP/HTTPS/DNS)
        try:
            from scapy.all import IP, TCP, sr1
            for port in [53, 80, 443, 3074, 500, 88, 123]:
                sr1(IP(dst=ip)/TCP(dport=port, flags='S'), timeout=0.5, verbose=0, iface=self.iface.guid)  # Use guid (Scapy/pcap name)
        except Exception:
            pass

        # Re-check ARP cache
        return self.probe_ip_arp_cache_only(ip)

    @staticmethod
    def _windows_parse_arp_probe_hit(cache: str, want_ip: str) -> Optional[tuple]:
        """Parse Windows ``arp -a`` output for a single IPv4; return (ip, mac) or None."""
        if not cache or not want_ip:
            return None
        for raw in cache.split('\n'):
            line = (raw or '').strip()
            if not line:
                continue
            low = line.lower()
            if 'interface:' in low or 'schnittstelle:' in low:
                continue
            parts = line.split()
            if len(parts) >= 2:
                if parts[0] == want_ip:
                    mac_candidate = parts[1].replace('-', ':')
                    mac = good_mac(mac_candidate)
                    if mac and mac != GLOBAL_MAC:
                        return (want_ip, mac)
                elif want_ip in line:
                    macs = re.findall(
                        r'([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})',
                        line,
                    )
                    if macs:
                        mac = good_mac(macs[0])
                        if mac and mac != GLOBAL_MAC:
                            return (want_ip, mac)
        return None

    def lookup_ip_in_arp_cache(self, ip: str) -> Optional[tuple]:
        """Read-only ARP table lookup — never merges devices or touches selection."""
        ip = (ip or '').strip()
        if not ip:
            return None
        if sys.platform.startswith('win'):
            # ``arp -a ip -N my_ip`` only sees that adapter's table. With ICS, my_ip is often
            # 192.168.137.x while the target is on 192.168.1.x — the entry lives on Wi‑Fi/LAN.
            # Try scoped query, then address-only, then full table.
            sources = []
            my = (getattr(self, 'my_ip', None) or '').strip()
            if my and my not in ('127.0.0.1', '0.0.0.0'):
                sources.append(terminal(f'arp -a {ip} -N {my}') or '')
            sources.append(terminal(f'arp -a {ip}') or '')
            sources.append(terminal('arp -a') or '')
            seen_txt = set()
            for cache in sources:
                if not cache or cache in seen_txt:
                    continue
                seen_txt.add(cache)
                hit = self._windows_parse_arp_probe_hit(cache, ip)
                if hit:
                    return hit
            return None
        cache = terminal('arp -an') or ''
        for line in cache.split('\n'):
            if ip in line:
                macs = re.findall(r'([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})', line)
                if macs:
                    mac = good_mac(macs[0])
                    if mac and mac != GLOBAL_MAC:
                        return (ip, mac)
        return None

    def probe_ip_arp_cache_only(self, ip: str) -> Optional[tuple]:
        """ARP-cache probe that merges a hit into the device table (Manual IP Search)."""
        hit = self.lookup_ip_in_arp_cache(ip)
        if hit:
            self.merge_client_hits([hit])
        return hit