"""WinDivert session lock. Stdlib + WinDivert only — not part of ZubCut.

Same capture path as the lock that already worked: python.exe daemon,
host filter, Recv then Send, FORWARD then NETWORK, AWS HTTPS drop list.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

from zublock_rules import RANGES_PATH, parse_drop_keys, should_drop

ROOT = Path(__file__).resolve().parent
INVALID_HANDLE = ctypes.c_void_p(-1).value
HOTSPOT_PREFIX = '192.168.137.'
DEFAULT_CONSOLE = '192.168.137.64'
WINDIVERT_PRIORITY = 0
ADDR_LEN = 80
WINDIVERT_SHUTDOWN_BOTH = 3
DROP_PATH = ROOT / 'drop_keys.txt'
STATUS_PATH = ROOT / 'zublock_status.json'
PID_PATH = ROOT / 'worker.pid'
WORKER_LOG = ROOT / 'worker.log'
OFF_TEXT = '# Empty = forward everything.\n'
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
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


def is_hotspot_console_ip(ip: str) -> bool:
    """True for a client on this PC's Mobile Hotspot LAN (not the gateway, not house Wi-Fi)."""
    raw = (ip or '').strip()
    if not raw.startswith(HOTSPOT_PREFIX):
        return False
    last = raw.rsplit('.', 1)[-1]
    return last not in ('0', '1', '255')


def capture_filters(console_ip: str = '') -> list[str]:
    """Exact filter from the lock that already worked."""
    ip = (console_ip or '').strip() or DEFAULT_CONSOLE
    return [f'ip and (ip.SrcAddr == {ip} or ip.DstAddr == {ip})']


def python_exe() -> str:
    exe = sys.executable or ''
    if exe.lower().endswith('pythonw.exe'):
        cand = exe[:-11] + 'python.exe'
        if Path(cand).is_file():
            return cand
    return exe


def ranges_text(path: Path = RANGES_PATH) -> str:
    text = path.read_text(encoding='utf-8')
    if not parse_drop_keys(text):
        raise RuntimeError(f'no lock rules in {path}')
    return text if text.endswith('\n') else text + '\n'


def lock_is_on(drop_path: Path = DROP_PATH) -> bool:
    try:
        text = drop_path.read_text(encoding='utf-8')
    except OSError:
        return False
    return bool(parse_drop_keys(text))


def set_lock(on: bool, drop_path: Path = DROP_PATH, ranges_path: Path = RANGES_PATH) -> None:
    drop_path.parent.mkdir(parents=True, exist_ok=True)
    if on:
        drop_path.write_text(ranges_text(ranges_path), encoding='utf-8')
    else:
        drop_path.write_text(OFF_TEXT, encoding='utf-8')


def _hidden_kwargs() -> dict:
    if os.name != 'nt':
        return {}
    return {'creationflags': CREATE_NO_WINDOW}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
    )
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def write_worker_pid(pid: int) -> None:
    try:
        PID_PATH.write_text(str(int(pid)), encoding='utf-8')
    except Exception:
        pass


def clear_worker_pid() -> None:
    try:
        PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def worker_pids() -> list[int]:
    try:
        pid = int(PID_PATH.read_text(encoding='utf-8').strip())
    except Exception:
        return []
    if _pid_alive(pid):
        return [pid]
    clear_worker_pid()
    return []


def worker_running() -> bool:
    return bool(worker_pids())


def start_worker(console_ip: str) -> str:
    if worker_running():
        return ''
    ip = (console_ip or '').strip() or DEFAULT_CONSOLE
    WORKER_LOG.parent.mkdir(parents=True, exist_ok=True)
    handle = open(WORKER_LOG, 'a', encoding='utf-8', errors='replace')
    try:
        handle.write(f'\nstart {time.strftime("%H:%M:%S")} ps4={ip} py={python_exe()}\n')
        handle.flush()
    except Exception:
        pass
    proc = subprocess.Popen(
        [
            python_exe(),
            '-u',
            str(ROOT / 'zublock_engine.py'),
            '--ps4',
            ip,
            '--daemon',
        ],
        cwd=str(ROOT),
        stdout=handle,
        stderr=handle,
        **_hidden_kwargs(),
    )
    write_worker_pid(proc.pid)
    return ''


def stop_workers() -> None:
    for pid in worker_pids():
        try:
            subprocess.run(
                ['taskkill', '/PID', str(pid), '/T', '/F'],
                capture_output=True,
                timeout=8,
                **_hidden_kwargs(),
            )
        except Exception:
            pass
    clear_worker_pid()


def read_status() -> dict:
    try:
        return json.loads(STATUS_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def write_status(payload: dict) -> None:
    tmp = STATUS_PATH.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(payload), encoding='utf-8')
        tmp.replace(STATUS_PATH)
    except Exception:
        pass


def _ping_alive(ip: str) -> bool:
    try:
        proc = subprocess.run(
            ['ping', '-n', '1', '-w', '400', ip],
            capture_output=True,
            timeout=2,
            **_hidden_kwargs(),
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
                **_hidden_kwargs(),
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
        self.console_ip = console_ip or DEFAULT_CONSOLE
        self._dll = None
        self._handle = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._rules: set[tuple[str, str, int]] = set()
        self._lock = threading.Lock()
        self._filt = b''
        self.dropped = 0
        self.forwarded = 0
        self.send_fail = 0
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
        if hasattr(self._dll, 'WinDivertShutdown'):
            self._dll.WinDivertShutdown.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self._dll.WinDivertShutdown.restype = ctypes.c_bool
        return ''

    def set_rules(self, rules: set[tuple[str, str, int]]) -> None:
        with self._lock:
            self._rules = set(rules)

    def start(self) -> str:
        err = self.load()
        if err:
            self.error = err
            return err
        if _handle_ok(self._handle):
            return ''
        self._filt = capture_filters(self.console_ip)[0].encode('ascii')
        last_gle = 0
        for layer, name in (
            (self.LAYER_FORWARD, 'FORWARD'),
            (self.LAYER_NETWORK, 'NETWORK'),
        ):
            try:
                ctypes.windll.kernel32.SetLastError(0)
            except Exception:
                pass
            handle = self._dll.WinDivertOpen(
                self._filt, layer, WINDIVERT_PRIORITY, 0
            )
            if _handle_ok(handle):
                self._handle = handle
                self.layers = name
                break
            last_gle = ctypes.GetLastError()
        if not _handle_ok(self._handle):
            self.error = f'WinDivertOpen failed (GLE {last_gle})'
            return self.error
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='zublock-divert', daemon=True)
        self._thread.start()
        self.error = ''
        return ''

    def stop(self) -> None:
        self._stop.set()
        handle = self._handle
        self._handle = None
        if _handle_ok(handle) and self._dll:
            try:
                if hasattr(self._dll, 'WinDivertShutdown'):
                    self._dll.WinDivertShutdown(handle, WINDIVERT_SHUTDOWN_BOTH)
            except Exception:
                pass
            try:
                self._dll.WinDivertClose(handle)
            except Exception:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)
        self.layers = ''

    @property
    def running(self) -> bool:
        return _handle_ok(self._handle)

    def _match(self, src: str, dst: str, proto: str, sport: int, dport: int, flags: str) -> bool:
        with self._lock:
            rules = set(self._rules)
        return should_drop(src, dst, proto, sport, dport, rules, flags=flags)

    def _loop(self) -> None:
        assert self._dll is not None
        buf = ctypes.create_string_buffer(0xFFFF)
        addr = ctypes.create_string_buffer(ADDR_LEN)
        nread = ctypes.c_uint(0)
        while not self._stop.is_set() and _handle_ok(self._handle):
            ok = self._dll.WinDivertRecv(
                self._handle, buf, len(buf), ctypes.byref(nread), addr
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
            sent_ok = self._dll.WinDivertSend(
                self._handle, buf, int(nread.value), ctypes.byref(sent), addr
            )
            if sent_ok:
                self.forwarded += 1
            else:
                self.send_fail += 1


def _run_daemon(console_ip: str) -> int:
    """Same control loop as session_lock.py --daemon: watch drop_keys, start/stop DivertDrop."""
    write_worker_pid(os.getpid())
    divert = DivertDrop(console_ip)
    last_mtime = None
    print(f'daemon ps4={console_ip} drop={DROP_PATH}', flush=True)
    try:
        while True:
            try:
                mtime = DROP_PATH.stat().st_mtime
                text = DROP_PATH.read_text(encoding='utf-8')
            except OSError:
                mtime = -1
                text = ''
            if mtime != last_mtime:
                last_mtime = mtime
                rules = parse_drop_keys(text)
                divert.set_rules(rules)
                if rules:
                    err = divert.start()
                    if err:
                        print(f'DROP start failed: {err}', flush=True)
                    else:
                        keys = ', '.join(
                            sorted(f'{p}/{h}:{port}' for p, h, port in rules)
                        )
                        print(f'DROP on {keys} layer={divert.layers}', flush=True)
                else:
                    divert.stop()
                    print('DROP off', flush=True)
            write_status(
                {
                    'running': divert.running,
                    'locked': bool(parse_drop_keys(text)) if text else False,
                    'dropped': divert.dropped,
                    'forwarded': divert.forwarded,
                    'send_fail': divert.send_fail,
                    'layers': divert.layers,
                    'error': divert.error,
                    'ps4': divert.console_ip,
                }
            )
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        divert.stop()
        set_lock(False)
        write_status({'running': False, 'locked': False, 'dropped': 0, 'forwarded': 0})
        clear_worker_pid()
        print('stopped', flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='ZubLock WinDivert worker')
    ap.add_argument('--ps4', default=DEFAULT_CONSOLE)
    ap.add_argument('--daemon', action='store_true')
    args = ap.parse_args(argv)
    if args.daemon:
        return _run_daemon(str(args.ps4).strip() or DEFAULT_CONSOLE)
    ap.print_help()
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
