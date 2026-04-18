from concurrent.futures.thread import ThreadPoolExecutor
from scapy.all import Ether, arping, conf, get_if_addr
from time import sleep
import re
import sys
from typing import Optional

from networking.nicknames import Nicknames
from tools.device_display import infer_network_device_type
from tools.utils import *
from constants import *

class Scanner():
    def __init__(self):
        self.iface = get_default_iface()
        self.device_count = 25
        self.max_threads = 8
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
        self.ips = [f'{self.perfix}.{i}' for i in range(1, self.device_count)]

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
            self.devices.append(
                {
                    'ip':     ip,
                    'mac':    mac,
                    'vendor': vend,
                    'type':   dev_type,
                    'name':   nicknames.get_name(mac),
                    'admin':  False
                }
            )
        
        # Remove device with old ip
        for device in self.devices[:]:
            mac, ip = device['mac'], device['ip']
            if self.old_ips.get(mac, ip) != ip:
                self.devices.remove(device)
        
        # Re-create devices old ips dict
        self.old_ips = {d['mac']: d['ip'] for d in self.devices}

        self.add_me()
        self.add_router()

        # Clear arp cache to avoid duplicates next time
        if unique:
            self.flush_arp()

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
        self.ping_thread_pool()
        
        while self.__ping_done < self.device_count - 1:
            # Add a sleep to overcome High CPU usage
            sleep(.01)
            self.qt_progress_signal(self.__ping_done)
        
        return True
    
    @threaded
    def ping_thread_pool(self):
        """
        Control maximum threads running at once
        """
        with ThreadPoolExecutor(self.max_threads) as executor:
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
                hits = [(r[1].psrc, r[1].src) for r in ans[0]]
                if hits:
                    self.devices_appender(hits)
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
        sleep(0.3)
        
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

    def probe_ip_arp_cache_only(self, ip: str) -> Optional[tuple]:
        if sys.platform.startswith('win'):
            # Windows ARP format: "  IP_ADDRESS      MAC_ADDRESS      TYPE"
            # Try with interface IP first
            if self.my_ip and self.my_ip != '127.0.0.1':
                cache = terminal(f'arp -a {ip} -N {self.my_ip}') or ''
            else:
                # Fallback: query all ARP entries
                cache = terminal(f'arp -a {ip}') or ''
            
            if cache:
                # Windows ARP output format:
                # " 192.168.1.1          00-11-22-33-44-55     dynamic"
                # or "Interface: 192.168.1.100 --- 0x3\n  192.168.1.1          00-11-22-33-44-55     dynamic"
                for line in cache.split('\n'):
                    line = line.strip()
                    if not line or 'Interface:' in line:
                        continue
                    # Look for IP and MAC in the line
                    parts = line.split()
                    if len(parts) >= 2:
                        # Check if first part is the IP we're looking for
                        if parts[0] == ip:
                            # Second part should be MAC (might be in format 00-11-22 or 00:11:22)
                            mac_candidate = parts[1].replace('-', ':')
                            mac = good_mac(mac_candidate)
                            if mac and mac != GLOBAL_MAC:
                                self.devices_appender([(ip, mac)])
                                return (ip, mac)
                        # Also check if IP appears anywhere in the line
                        elif ip in line:
                            # Extract MAC using regex
                            macs = re.findall(r'([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})', line)
                            if macs:
                                mac = good_mac(macs[0])
                                if mac and mac != GLOBAL_MAC:
                                    self.devices_appender([(ip, mac)])
                                    return (ip, mac)
        else:
            cache = terminal('arp -an') or ''
            for line in cache.split('\n'):
                if ip in line:
                    macs = re.findall(r'([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})', line)
                    if macs:
                        mac = good_mac(macs[0])
                        self.devices_appender([(ip, mac)])
                        return (ip, mac)
        return None