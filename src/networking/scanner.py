from concurrent.futures.thread import ThreadPoolExecutor
import os
from scapy.all import Ether, arping, conf, get_if_addr
from time import sleep
import re
import sys
from typing import Optional

from networking.nicknames import (
    Nicknames,
    get_nicknames_dict,
    get_nickname_last_ip_map,
    record_nickname_last_ip,
)
from tools.device_display import infer_network_device_type
from tools.clumsy_inline import sync_clumsy_row, clumsy_mode_enabled
from tools.utils import *
from constants import *

class Scanner():
    def __init__(self):
        self.iface = get_default_iface()
        self.device_count = 25
        self.max_threads = 12
        self.__ping_done = 0
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
        self.iface = get_iface_by_name(self.iface.name)
        self.devices = []

        # Use iface.guid (Scapy/pcap name) for network operations, not iface.name
        self.router_ip = get_gateway_ip(self.iface.guid)
        self.router_mac = get_gateway_mac(self.iface.ip, self.router_ip)

        self.my_ip = get_my_ip(self.iface.guid)
        self.my_mac = good_mac(self.iface.mac)
        
        self.perfix = self.my_ip.rsplit(".", 1)[0]
        self.generate_ips()

    def sync_iface_for_victim_ip(self, victim_ip: str) -> bool:
        """
        If victim_ip is on a different local interface than self.iface, rebind scanner
        topology (gateway, me, router dict) so Killer/ARP/firewall use the right NIC.
        """
        target = get_iface_for_victim_ip(victim_ip, fallback=self.iface)
        if target.guid == self.iface.guid:
            return False
        self.iface = target
        self.router_ip = get_gateway_ip(self.iface.guid)
        self.router_mac = get_gateway_mac(self.iface.ip, self.router_ip)
        self.my_ip = get_my_ip(self.iface.guid)
        self.my_mac = good_mac(self.iface.mac)
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

    def refresh_local_topology(self) -> None:
        """
        Re-read gateway and local addresses on the current iface without changing NIC.
        Clumsy enable/repair + restart do this implicitly; Kill/Lag need it on every arm.
        """
        guid = getattr(self.iface, 'guid', None) or getattr(self.iface, 'name', None)
        if not guid or guid == 'NULL':
            return
        self.router_ip = get_gateway_ip(guid)
        self.router_mac = get_gateway_mac(self.iface.ip, self.router_ip)
        self.my_ip = get_my_ip(guid)
        self.my_mac = good_mac(self.iface.mac)
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
        present = {d.get('mac') for d in self.devices if isinstance(d, dict)}
        to_add = []
        for mac_raw, name in sorted(nick_db.items()):
            if not name or name == '-':
                continue
            mac = good_mac(mac_raw)
            if not mac or mac in present:
                continue
            ip = last_map.get(mac)
            if not ip:
                continue
            parts = str(ip).split('.')
            if len(parts) != 4:
                continue
            try:
                if not all(0 <= int(x) <= 255 for x in parts):
                    continue
            except (TypeError, ValueError):
                continue
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
        Append scan results to self.devices
        """
        nicknames = Nicknames()

        self.devices = []
        unique = []

        # Sort by last IPv4 octet (tolerant of odd rows so we never abort the scan thread).
        def _ip_sort_key(item):
            try:
                return int(str(item[0]).rsplit('.', 1)[-1])
            except (ValueError, IndexError, TypeError, AttributeError):
                return 0

        scan_result = sorted(scan_result, key=_ip_sort_key)

        for ip, mac in scan_result:
            mac = good_mac(mac)

            # Skip me or router and duplicated devices
            if ip in [self.router_ip, self.my_ip] or mac in unique:
                continue
            
            # update same device with new ip
            if self.old_ips.get(mac, ip) != ip:
                self.old_ips[mac] = ip
                unique.append(mac)

            vend = get_vendor(mac)
            try:
                dev_type = infer_network_device_type(mac, vend, '')
            except Exception:
                dev_type = 'User'
            nm = nicknames.get_name(mac)
            self.devices.append(
                {
                    'ip':     ip,
                    'mac':    mac,
                    'vendor': vend,
                    'type':   dev_type,
                    'name':   nm,
                    'admin':  False
                }
            )
            if nm and nm != '-':
                record_nickname_last_ip(mac, ip)
        
        # Remove device with old ip
        for device in self.devices[:]:
            mac, ip = device['mac'], device['ip']
            if self.old_ips.get(mac, ip) != ip:
                self.devices.remove(device)
        
        # Re-create devices old ips dict
        self.old_ips = {d['mac']: d['ip'] for d in self.devices}

        self.add_me()
        self.add_router()
        self.inject_nicknamed_favorites()
        self.old_ips = {d['mac']: d['ip'] for d in self.devices if not d.get('admin')}
        sync_clumsy_row(self)

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
        nicknames = Nicknames()
        by_mac = {d['mac']: d for d in self.devices if not d.get('admin')}
        for ip, mac in hits:
            mac = good_mac(mac)
            if ip in [self.router_ip, self.my_ip] or not mac:
                continue
            vend = get_vendor(mac)
            try:
                dev_type = infer_network_device_type(mac, vend, '')
            except Exception:
                dev_type = 'User'
            nm = nicknames.get_name(mac)
            by_mac[mac] = {
                'ip': ip,
                'mac': mac,
                'vendor': vend,
                'type': dev_type,
                'name': nm,
                'admin': False,
            }
            if nm and nm != '-':
                record_nickname_last_ip(mac, ip)

        def _sort_dev(d):
            try:
                return int(str(d['ip']).rsplit('.', 1)[-1])
            except (ValueError, IndexError, TypeError, AttributeError):
                return 0

        self.devices = sorted(by_mac.values(), key=_sort_dev)
        self.old_ips = {d['mac']: d['ip'] for d in self.devices}
        self.add_me()
        self.add_router()
        self.inject_nicknamed_favorites()
        self.old_ips = {d['mac']: d['ip'] for d in self.devices if not d.get('admin')}
        # Ping sweep can take seconds; this runs on the scan QThread, not the GUI thread.
        sync_clumsy_row(self, allow_subnet_ping=True)

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
            except Exception:
                pass
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
            if restrict_subnet and not ip.startswith(pf + '.'):
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
                lines_en = [
                    l for l in scan_result.split('\n')
                    if 'dynamic' in l.lower() or 'static' in l.lower()
                ]
                if lines_en:
                    scan_result = '\n'.join(lines_en)
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
        # "0.0.0.0/24" breaks discovery; fall back to the host subnet from our own IP.
        target = f"{self.router_ip}/24"
        if not self.router_ip or self.router_ip in ('0.0.0.0', '127.0.0.1'):
            target = f"{self.perfix}.0/24"
        try:
            scan_result = arping(
                target,
                iface=self.iface.guid,  # Use guid (Scapy/pcap name), not name
                verbose=0,
                timeout=1
            )
            clean_result = [(i[1].psrc, i[1].src) for i in scan_result[0]]
        except Exception as e:
            print('arp_scan: arping failed:', e)
            clean_result = []

        # If Scapy found nothing (Npcap permissions, wrong iface, etc.), fall back to OS ARP table.
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
        self.__ping_done = 0
        
        self.generate_ips()
        total_ips = len(self.ips)
        self.ping_thread_pool()
        
        while self.__ping_done < total_ips:
            # Add a sleep to overcome High CPU usage
            sleep(.01)
            self.qt_progress_signal(self.__ping_done)
        
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

    def probe_ip_arp_cache_only(self, ip: str) -> Optional[tuple]:
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
                    self.merge_client_hits([hit])
                    return hit
            return None
        cache = terminal('arp -an') or ''
        for line in cache.split('\n'):
            if ip in line:
                macs = re.findall(r'([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})', line)
                if macs:
                    mac = good_mac(macs[0])
                    self.merge_client_hits([(ip, mac)])
                    return (ip, mac)
        return None