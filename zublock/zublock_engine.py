"""WinDivert session lock. Stdlib + WinDivert only — not part of ZubCut."""
from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import threading
from pathlib import Path

from zublock_rules import should_drop

ROOT = Path(__file__).resolve().parent
INVALID_HANDLE = ctypes.c_void_p(-1).value
HOTSPOT_PREFIX = '192.168.137.'
HOTSPOT_NET = '192.168.137.0/24'
DEFAULT_CONSOLE = '192.168.137.64'
# Above ZubCut/Clumzy (priority 0) so this lock actually sees hotspot packets.
WINDIVERT_PRIORITY = 800
ADDR_LEN = 256
SONY_MAC_PREFIXES = (
    'f8-da-0c',
    '00-d9-d1',
    '00-04-1f',
    '00-13-15',
    '00-19-c5',
    '00-1d-0d',
    '00-1f-a7',
    '00-24-8d',
    '00-24-be',
    '00-e4-21',
    '28-0d-fc',
    '70-9e-29',
    '78-c8-81',
    'a8-e3-ee',
    'bc-60-a7',
    'c8-63-f1',
    'f8-46-1c',
)


def parse_ipv4(raw: bytes) -> tuple[str, str, str, int, int, str] | None:
    """Return (src, dst, proto, sport, dport, tcp_flags) from a raw IPv4 packet."""
    if len(raw) < 20:
        return None
    if (raw[0] >> 4) != 4:
        return None
    ihl = (raw[0] & 0x0F) * 4
    if ihl < 20 or len(raw) < ihl:
        return None
    proto_n = raw[9]
    src = '.'.join(str(b) for b in raw[12:16])
    dst = '.'.join(str(b) for b in raw[16:20])
    if proto_n == 6:
        if len(raw) < ihl + 20:
            return src, dst, 'TCP', 0, 0, ''
        sport, dport = struct.unpack('!HH', raw[ihl : ihl + 4])
        fl = raw[ihl + 13]
        flags = ''
        if fl & 0x02:
            flags += 'S'
        if fl & 0x10:
            flags += 'A'
        return src, dst, 'TCP', int(sport), int(dport), flags
    if proto_n == 17:
        if len(raw) < ihl + 8:
            return src, dst, 'UDP', 0, 0, ''
        sport, dport = struct.unpack('!HH', raw[ihl : ihl + 4])
        return src, dst, 'UDP', int(sport), int(dport), ''
    return src, dst, 'IP', 0, 0, ''


def _handle_ok(handle) -> bool:
    if handle is None:
        return False
    try:
        value = int(handle)
    except (TypeError, ValueError):
        return False
    return value not in (0, -1, INVALID_HANDLE)


def capture_filters(console_ip: str = '') -> list[str]:
    """Whole hotspot LAN, not one ARP row (.64 vs .248 on the same console)."""
    inner = f'ip.SrcAddr == {HOTSPOT_NET} or ip.DstAddr == {HOTSPOT_NET}'
    ip = (console_ip or '').strip()
    if ip and not ip.startswith(HOTSPOT_PREFIX):
        inner = f'({inner}) or ip.SrcAddr == {ip} or ip.DstAddr == {ip}'
    base = f'ip and ({inner})'
    return [f'({base}) and !impostor', base]


def _ping_alive(ip: str) -> bool:
    try:
        proc = subprocess.run(
            ['ping', '-n', '1', '-w', '400', ip],
            capture_output=True,
            timeout=2,
        )
        return proc.returncode == 0
    except Exception:
        return False


def discover_hotspot_clients(arp_text: str = '') -> list[str]:
    """Live hotspot clients only. One IP per MAC so a stale extra ARP row is ignored."""
    text = arp_text
    live_check = not bool(arp_text)
    if not text:
        try:
            proc = subprocess.run(
                ['arp', '-a'],
                capture_output=True,
                text=True,
                timeout=6,
                errors='replace',
            )
            text = proc.stdout or ''
        except Exception:
            return []
    in_hotspot = False
    found: list[tuple[str, str]] = []
    seen_ip: set[str] = set()
    seen_mac: set[str] = set()
    for line in text.splitlines():
        low = line.lower()
        if 'interface:' in low and HOTSPOT_PREFIX in low:
            in_hotspot = True
            continue
        if low.startswith('interface:'):
            in_hotspot = False
            continue
        if not in_hotspot:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ip, mac = parts[0], parts[1].lower().replace(':', '-')
        if not ip.startswith(HOTSPOT_PREFIX):
            continue
        if ip.endswith('.1') or ip.endswith('.255'):
            continue
        if ip in seen_ip or mac in seen_mac:
            continue
        seen_ip.add(ip)
        seen_mac.add(mac)
        found.append((ip, mac))
    sony = [
        ip
        for ip, mac in found
        if any(mac.startswith(p) for p in SONY_MAC_PREFIXES)
    ]
    ips = sony if sony else [ip for ip, _mac in found]
    if live_check:
        live = [ip for ip in ips if _ping_alive(ip)]
        if live:
            return live
    return ips


def discover_hotspot_console(arp_text: str = '') -> str:
    """First PlayStation (or any host) on the Windows hotspot LAN."""
    clients = discover_hotspot_clients(arp_text)
    return clients[0] if clients else DEFAULT_CONSOLE


class DivertDrop:
    LAYER_NETWORK = 0
    LAYER_FORWARD = 1

    def __init__(self, console_ip: str = '') -> None:
        self.console_ip = console_ip
        self._dll = None
        self._handles: list = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._rules: set[tuple[str, str, int]] = set()
        self._lock = threading.Lock()
        self._filt_bytes: list[bytes] = []
        self.dropped = 0
        self.forwarded = 0
        self.error = ''
        self.layers = ''

    def _find_dll(self) -> Path | None:
        local = os.environ.get('LOCALAPPDATA') or ''
        cands = [
            ROOT / 'windivert' / 'WinDivert.dll',
            ROOT / 'WinDivert.dll',
        ]
        if local:
            cands.append(Path(local) / 'ZubLock' / 'windivert' / 'WinDivert.dll')
            cands.append(Path(local) / 'ZubCut' / 'windivert' / 'WinDivert.dll')
        for path in cands:
            if path.is_file():
                return path
        return None

    def load(self) -> str:
        dll_path = self._find_dll()
        if dll_path is None:
            return (
                'WinDivert.dll not found. Run ZubLock-Setup so it can download WinDivert.'
            )
        os.add_dll_directory(str(dll_path.parent))
        self._dll = ctypes.WinDLL(str(dll_path))
        self._dll.WinDivertOpen.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int16,
            ctypes.c_uint64,
        ]
        self._dll.WinDivertOpen.restype = ctypes.c_void_p
        self._dll.WinDivertRecv.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_void_p,
        ]
        self._dll.WinDivertRecv.restype = ctypes.c_bool
        self._dll.WinDivertSend.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_void_p,
        ]
        self._dll.WinDivertSend.restype = ctypes.c_bool
        self._dll.WinDivertClose.argtypes = [ctypes.c_void_p]
        self._dll.WinDivertClose.restype = ctypes.c_bool
        return ''

    def set_rules(self, rules: set[tuple[str, str, int]]) -> None:
        with self._lock:
            self._rules = set(rules)

    def _open(self, filt: bytes, layer: int):
        assert self._dll is not None
        try:
            ctypes.windll.kernel32.SetLastError(0)
        except Exception:
            pass
        handle = self._dll.WinDivertOpen(
            filt,
            layer,
            WINDIVERT_PRIORITY,
            0,
        )
        if _handle_ok(handle):
            return handle, 0
        return None, ctypes.GetLastError()

    def start(self) -> str:
        err = self.load()
        if err:
            self.error = err
            return err
        if self.running:
            return ''
        last_gle = 0
        names: list[str] = []
        for filt in capture_filters(self.console_ip):
            raw = filt.encode('ascii')
            self._filt_bytes.append(raw)
            got: list = []
            labels: list[str] = []
            for layer, name in (
                (self.LAYER_FORWARD, 'FORWARD'),
                (self.LAYER_NETWORK, 'NETWORK'),
            ):
                handle, gle = self._open(raw, layer)
                if handle is not None:
                    got.append(handle)
                    labels.append(name)
                else:
                    last_gle = gle
            if got:
                self._handles = got
                names = labels
                break
        if not self._handles:
            self.error = f'WinDivertOpen failed (GLE {last_gle})'
            return self.error
        self.layers = '+'.join(names)
        self._stop.clear()
        for i, handle in enumerate(self._handles):
            thread = threading.Thread(
                target=self._loop,
                args=(handle,),
                name=f'zublock-divert-{i}',
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        self.error = ''
        return ''

    def stop(self) -> None:
        self._stop.set()
        handles = list(self._handles)
        self._handles = []
        if self._dll:
            for handle in handles:
                if _handle_ok(handle):
                    try:
                        self._dll.WinDivertClose(handle)
                    except Exception:
                        pass
        threads = list(self._threads)
        self._threads = []
        for thread in threads:
            thread.join(timeout=1.0)

    @property
    def running(self) -> bool:
        return any(_handle_ok(h) for h in self._handles)

    def _match(self, src: str, dst: str, proto: str, sport: int, dport: int, flags: str) -> bool:
        with self._lock:
            rules = set(self._rules)
        return should_drop(src, dst, proto, sport, dport, rules, flags=flags)

    def _loop(self, handle) -> None:
        assert self._dll is not None
        buf = ctypes.create_string_buffer(0xFFFF)
        addr = ctypes.create_string_buffer(ADDR_LEN)
        nread = ctypes.c_uint(0)
        while not self._stop.is_set() and _handle_ok(handle):
            ok = self._dll.WinDivertRecv(
                handle, buf, len(buf), ctypes.byref(nread), addr
            )
            if not ok:
                if self._stop.is_set():
                    return
                continue
            raw = bytes(buf.raw[: int(nread.value)])
            drop = False
            parsed = parse_ipv4(raw)
            if parsed is not None:
                src, dst, proto, sport, dport, flags = parsed
                drop = self._match(src, dst, proto, sport, dport, flags)
            if drop:
                self.dropped += 1
                continue
            sent = ctypes.c_uint(0)
            self._dll.WinDivertSend(
                handle, buf, int(nread.value), ctypes.byref(sent), addr
            )
            self.forwarded += 1
