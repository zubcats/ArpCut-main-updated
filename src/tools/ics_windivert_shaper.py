"""
ICS / Clumsy-mode advanced shaping via WinDivert (driver path).

Used only when Clumsy mode is on, WinDivert is available, and the selected device
matches the detected ICS client IP. Falls back to MITM forwarder otherwise.

Requires Administrator and WinDivert.dll next to the executable (or in ./windivert/).
"""

from __future__ import annotations

import ctypes
import heapq
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from typing import Optional, Tuple

try:
    import winreg
except ImportError:
    winreg = None

WINDIVERT_LAYER_NETWORK = 0
WINDIVERT_LAYER_NETWORK_FORWARD = 1
WINDIVERT_SHUTDOWN_BOTH = 2
WINDIVERT_RECV_FLAG_NOBLOCK = 0x0001
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
ERROR_NO_DATA = 232
ERROR_INSUFFICIENT_BUFFER = 122

ADDR_BUF = 256
MAX_PACKET = 0xFFFF


def _windivert_search_bases() -> list[str]:
    """Directories to look for bundled WinDivert.dll / WinDivert64.sys."""
    bases: list[str] = []
    if getattr(sys, 'frozen', False):
        bases.append(os.path.dirname(sys.executable))
    else:
        bases.append(os.getcwd())
        try:
            repo = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            bases.append(repo)
        except Exception:
            pass
    out: list[str] = []
    seen: set[str] = set()
    for b in bases:
        if not b:
            continue
        norm = os.path.normcase(os.path.abspath(b))
        if norm in seen:
            continue
        seen.add(norm)
        out.append(b)
    return out


def _windivert_dll_path() -> Optional[str]:
    dll, _sys = _windivert_bundle_paths()
    return dll


def _windivert_local_cache_dir() -> str:
    """No spaces — avoids WinDivertOpen PATH_NOT_FOUND (code 3) from Program Files paths."""
    base = os.environ.get('LOCALAPPDATA', '').strip()
    if not base:
        base = os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
    path = os.path.join(base, 'ZubCut', 'windivert')
    os.makedirs(path, exist_ok=True)
    return path


def _windivert_install_paths() -> tuple[Optional[str], Optional[str]]:
    """WinDivert.dll + WinDivert64.sys under the ZubCut install directory."""
    if not sys.platform.startswith('win'):
        return None, None
    rel_dirs = (os.path.join('windivert'),)
    names = ('WinDivert.dll', 'WinDivert64.sys')
    for base in _windivert_search_bases():
        for rel_dir in rel_dirs:
            dll = os.path.join(base, rel_dir, names[0])
            sys_p = os.path.join(base, rel_dir, names[1])
            if os.path.isfile(dll) and os.path.isfile(sys_p):
                return os.path.abspath(dll), os.path.abspath(sys_p)
    return None, None


def _windivert_materialize_paths() -> tuple[Optional[str], Optional[str]]:
    """
    Load WinDivert from %LOCALAPPDATA%\\ZubCut\\windivert (Clumsy-style colocated dll+sys).

    Copy from {app}\\windivert so the driver path is short and has no spaces.
    """
    src_dll, src_sys = _windivert_install_paths()
    if not src_dll or not src_sys:
        return None, None
    cache = _windivert_local_cache_dir()
    dst_dll = os.path.join(cache, 'WinDivert.dll')
    dst_sys = os.path.join(cache, 'WinDivert64.sys')
    try:
        for src, dst in ((src_dll, dst_dll), (src_sys, dst_sys)):
            if not os.path.isfile(dst):
                shutil.copy2(src, dst)
                continue
            try:
                if os.path.getsize(dst) != os.path.getsize(src):
                    shutil.copy2(src, dst)
                elif os.path.getmtime(dst) < os.path.getmtime(src):
                    shutil.copy2(src, dst)
            except OSError:
                shutil.copy2(src, dst)
    except OSError:
        return None, None
    if not (os.path.isfile(dst_dll) and os.path.isfile(dst_sys)):
        return None, None
    return os.path.abspath(dst_dll), os.path.abspath(dst_sys)


def _windivert_bundle_paths() -> tuple[Optional[str], Optional[str]]:
    """Runtime paths used for WinDivertOpen (materialized local cache)."""
    return _windivert_materialize_paths()


def _windivert_last_error_message() -> str:
    kernel32 = ctypes.windll.kernel32
    err = int(kernel32.GetLastError())
    if err == 0:
        return 'unknown error'
    buf = ctypes.create_unicode_buffer(512)
    kernel32.FormatMessageW(
        0x00001000,
        None,
        err,
        0,
        buf,
        len(buf),
        None,
    )
    msg = (buf.value or '').strip() or f'Win32 error {err}'
    return f'{msg} (code {err})'


def _windivert_prepare_dll_dir(dll_path: str) -> None:
    """WinDivert64.sys loads from the same directory as WinDivert.dll (do not SetDllDirectory)."""
    dll_dir = os.path.dirname(os.path.abspath(dll_path))
    if not dll_dir:
        return
    if hasattr(os, 'add_dll_directory'):
        try:
            os.add_dll_directory(dll_dir)
        except OSError:
            pass


def _windivert_normalized_path(path: str) -> str:
    p = (path or '').strip()
    low = p.lower()
    if low.startswith('\\??\\'):
        p = p[4:]
    elif low.startswith('\\\\?\\'):
        p = p[4:]
    if not p:
        return ''
    return os.path.normcase(os.path.abspath(p))


def _windivert_service_image_path() -> str:
    if not sys.platform.startswith('win') or winreg is None:
        return ''
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SYSTEM\CurrentControlSet\Services\WinDivert',
        ) as key:
            image, _ = winreg.QueryValueEx(key, 'ImagePath')
            return _windivert_normalized_path(str(image))
    except OSError:
        return ''


def _windivert_sc_stop_and_delete() -> None:
    for args in (['sc.exe', 'stop', 'WinDivert'], ['sc.exe', 'delete', 'WinDivert']):
        try:
            subprocess.run(
                args,
                capture_output=True,
                timeout=15,
                check=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except Exception:
            pass


def _windivert_repair_stale_service(sys_path: str) -> tuple[bool, str]:
    """
    WinDivertOpen error 3 often means the WinDivert kernel service still points at a
    deleted .sys path (e.g. an old WinRAR temp folder). Remove the stale service so
    the next WinDivertOpen registers WinDivert64.sys next to our DLL.
    """
    want = _windivert_normalized_path(sys_path)
    if not want or not os.path.isfile(want):
        return False, 'WinDivert64.sys missing'
    current = _windivert_service_image_path()
    if not current:
        return True, 'no service (will install on open)'
    if current == want:
        return True, 'service path ok'
    if os.path.isfile(current):
        return True, 'service uses another valid driver path'
    _windivert_sc_stop_and_delete()
    return True, f'removed stale WinDivert service (was {current})'


def _windivert_load_dll(dll_path: str, sys_path: Optional[str] = None) -> ctypes.WinDLL:
    sys_p = sys_path or os.path.join(os.path.dirname(os.path.abspath(dll_path)), 'WinDivert64.sys')
    _windivert_repair_stale_service(sys_p)
    _windivert_prepare_dll_dir(dll_path)
    old_cwd = os.getcwd()
    dll_dir = os.path.dirname(os.path.abspath(dll_path))
    try:
        if dll_dir:
            os.chdir(dll_dir)
    except OSError:
        dll_dir = ''
    try:
        return ctypes.WinDLL(dll_path)
    finally:
        if dll_dir:
            try:
                os.chdir(old_cwd)
            except OSError:
                pass


def _ics_clumsy_victim_filter(victim_ip: str) -> str:
    """Clumsy-style per-host filter (simple quad match, no subnet ranges)."""
    vip = _ipv4_quad(victim_ip)
    return f'ip and (ip.SrcAddr == {vip} or ip.DstAddr == {vip})'


def _ipv4_quad(ip: str) -> str:
    return (ip or '').strip()


def _ics_subnet_quad_prefix(prefix: str) -> str:
    p = (prefix or '').strip().rstrip('.')
    if not p:
        return ''
    parts = p.split('.')
    if len(parts) != 3:
        return ''
    return p


def _ics_windivert_filter(victim_ip: str, downstream_prefix: str = '') -> str:
    """
    WinDivert filter for ICS client traffic.

    On Mobile Hotspot, FORWARD-layer packets can show post-NAT addresses; a subnet-wide
    filter on the downstream prefix plus victim matching in the recv loop catches more paths.
    """
    vip = _ipv4_quad(victim_ip)
    quad = _ics_subnet_quad_prefix(downstream_prefix)
    if quad and vip.startswith(quad + '.'):
        return (
            f'ip and ('
            f'(ip.SrcAddr >= {quad}.2 and ip.SrcAddr <= {quad}.254) or '
            f'(ip.DstAddr >= {quad}.2 and ip.DstAddr <= {quad}.254)'
            ')'
        )
    return f'ip and (ip.SrcAddr == {vip} or ip.DstAddr == {vip})'


def _packet_involves_victim(src: str, dst: str, victim: str) -> bool:
    return src == victim or dst == victim


def _ics_gateway_ip(downstream_prefix: str) -> str:
    quad = _ics_subnet_quad_prefix(downstream_prefix)
    return f'{quad}.1' if quad else ''


def _is_hotspot_client_ip(ip: str, downstream_prefix: str) -> bool:
    """ICS downstream client (PS5), not the PC gateway (.1)."""
    quad = _ics_subnet_quad_prefix(downstream_prefix)
    if not quad or not ip:
        return False
    return ip.startswith(quad + '.') and ip != _ics_gateway_ip(downstream_prefix)


def _windivert_addr_flag_word(addr_b: bytes) -> int:
    """
    Layer/Event/Sniffed/Outbound/Loopback/Impostor bitfield (UINT64 at offset 8).

    WinDivert 1.x/2.x share this layout; reading offset 16 was wrong and broke
    outbound classification on FORWARD-layer post-NAT packets.
    """
    if len(addr_b) < 16:
        return 0
    return int.from_bytes(addr_b[8:16], 'little')


# WINDIVERT_ADDRESS bitfield (see WinDivert 2.2 docs).
_WD_FLAG_SNIFFED = 1 << 16
_WD_FLAG_OUTBOUND = 1 << 17
_WD_FLAG_LOOPBACK = 1 << 18
_WD_FLAG_IMPOSTOR = 1 << 19


def _windivert_addr_outbound(addr_b: bytes) -> Optional[bool]:
    if len(addr_b) < 16:
        return None
    word = _windivert_addr_flag_word(addr_b)
    return bool(word & _WD_FLAG_OUTBOUND)


def _windivert_addr_impostor(addr_b: bytes) -> bool:
    """True for packets reinjected by WinDivertSend (must not shape twice)."""
    return bool(_windivert_addr_flag_word(addr_b) & _WD_FLAG_IMPOSTOR)


def _victim_packet_roles(
    src: str,
    dst: str,
    victim: str,
    downstream_prefix: str,
    *,
    outbound: Optional[bool] = None,
    subnet_capture: bool = False,
) -> tuple[bool, bool, str]:
    """
    Map a packet to victim outbound/inbound on the hotspot.

    Never treat all non-gateway traffic as victim — that paused the whole PC NAT path
    and looked like full WiFi cut. Use 137.x client IPs or outbound hint only when
    the pinned victim is on the hotspot subnet.
    """
    vip = _ipv4_quad(victim)
    if src == vip:
        return True, dst == vip, vip
    if dst == vip:
        return src == vip, True, vip
    src_is = _is_hotspot_client_ip(src, downstream_prefix)
    dst_is = _is_hotspot_client_ip(dst, downstream_prefix)
    if src_is and not dst_is:
        return True, False, src
    if dst_is and not src_is:
        return False, True, dst
    if src_is and dst_is:
        active = src
        return True, dst == active or dst_is, active
    client = vip if _is_hotspot_client_ip(vip, downstream_prefix) else ''
    if subnet_capture and client and outbound is not None:
        if outbound:
            return True, False, client
        return False, True, client
    return False, False, vip


def _packet_matches_hotspot_client(
    src: str, dst: str, victim: str, downstream_prefix: str
) -> bool:
    if _packet_involves_victim(src, dst, victim):
        return True
    quad = _ics_subnet_quad_prefix(downstream_prefix)
    if not quad:
        return False
    needle = quad + '.'
    return src.startswith(needle) or dst.startswith(needle)


def _ipv4_bytes(b: bytes) -> str:
    return '.'.join(str(x) for x in b)


def _bind_windivert_api(dll: ctypes.WinDLL) -> None:
    dll.WinDivertOpen.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int16,
        ctypes.c_uint64,
    ]
    dll.WinDivertOpen.restype = ctypes.c_void_p

    dll.WinDivertRecvEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.c_void_p,
    ]
    dll.WinDivertRecvEx.restype = wintypes.BOOL

    dll.WinDivertSend.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.c_void_p,
    ]
    dll.WinDivertSend.restype = wintypes.BOOL

    dll.WinDivertShutdown.argtypes = [wintypes.HANDLE, ctypes.c_int]
    dll.WinDivertShutdown.restype = wintypes.BOOL

    dll.WinDivertClose.argtypes = [wintypes.HANDLE]
    dll.WinDivertClose.restype = wintypes.BOOL


def _open_windivert_handle(dll: ctypes.WinDLL, filt: str, layer: int) -> int:
    f = filt.encode('ascii', errors='ignore')
    h = dll.WinDivertOpen(ctypes.c_char_p(f), ctypes.c_int(layer), ctypes.c_int16(0), ctypes.c_uint64(0))
    if not h:
        return -1
    hv = int(h) if not isinstance(h, ctypes.c_void_p) else int(h.value or 0)
    maxptr = (1 << 64) - 1
    if hv == 0 or hv == maxptr:
        return -1
    return hv


def _ics_windivert_open_candidates(
    victim_ip: str, downstream_prefix: str = ''
) -> list[tuple[str, str]]:
    """
    Filter order for hotspot capture.

    Subnet filter first (FORWARD-layer PS5 traffic often never hits a tight
    victim-only filter). Userspace still impairs only the victim IP.
    """
    vip = _ipv4_quad(victim_ip)
    if not vip:
        return []
    quad = _ics_subnet_quad_prefix(downstream_prefix)
    out: list[tuple[str, str]] = []
    if quad:
        anchor = vip if vip.startswith(quad + '.') else f'{quad}.2'
        out.append((_ics_windivert_filter(anchor, downstream_prefix), 'subnet'))
    if vip:
        out.append((_ics_clumsy_victim_filter(vip), 'victim'))
    return out


def _open_best_windivert_handle(
    dll: ctypes.WinDLL, victim_ip: str, downstream_prefix: str = ''
) -> tuple[int, int, str]:
    """
    Open exactly one WinDivert handle (subnet+FORWARD preferred).

    Multiple overlapping handles each process the same packet and would apply
    percent-cut byte budgets / shaping more than once — that looks like full Kill.
    """
    for filt, desc in _ics_windivert_open_candidates(victim_ip, downstream_prefix):
        # FORWARD first — PS5 game traffic is usually visible here on ICS hotspot.
        for layer in (WINDIVERT_LAYER_NETWORK_FORWARD, WINDIVERT_LAYER_NETWORK):
            h = _open_windivert_handle(dll, filt, layer)
            if h >= 0:
                return h, layer, desc
    return -1, 0, ''


def probe_windivert_for_victim(victim_ip: str) -> tuple[bool, str]:
    """
    Try opening WinDivert like Clumsy (dll+sys colocated, admin required).
    Returns (ok, message).
    """
    vip = _ipv4_quad(victim_ip)
    if not vip:
        return False, 'no victim IP'
    dll_path, sys_path = _windivert_materialize_paths()
    if not dll_path or not sys_path:
        inst_dll, inst_sys = _windivert_install_paths()
        if not inst_dll or not inst_sys:
            return (
                False,
                'WinDivert not installed — reinstall ZubCut with "Clumsy mode" checked',
            )
        return False, 'could not copy WinDivert to local cache (check disk permissions)'
    repaired, repair_note = _windivert_repair_stale_service(sys_path)
    if not repaired:
        return False, repair_note
    try:
        dll = _windivert_load_dll(dll_path, sys_path)
        _bind_windivert_api(dll)
    except OSError as exc:
        return False, f'failed to load WinDivert.dll: {exc}'
    try:
        from tools.clumsy_inline import clumsy_ics_downstream_prefix

        prefix = clumsy_ics_downstream_prefix()
    except Exception:
        prefix = '192.168.137.'
    h, layer, desc = _open_best_windivert_handle(dll, vip, prefix)
    if h >= 0:
        try:
            dll.WinDivertClose(h)
        except Exception:
            pass
        return True, f'ok (layer {layer}, {desc})'
    last_err = _windivert_last_error_message()
    hint = ''
    if 'code 3' in (last_err or '').lower() or '(code 3)' in (last_err or ''):
        hint = (
            ' Stale WinDivert driver service may remain — run tools\\Repair-WinDivert-Service.cmd '
            'as Administrator, then try Kill again.'
        )
    return False, (
        f'{last_err or "WinDivertOpen failed"} '
        f'[dll={dll_path} sys={sys_path}]{hint}'
    )


def _parse_ipv4_src_dst(packet: bytes) -> Optional[Tuple[str, str]]:
    if len(packet) < 20:
        return None
    v = packet[0] >> 4
    if v != 4:
        return None
    ihl = (packet[0] & 0x0F) * 4
    if len(packet) < ihl or ihl < 20:
        return None
    src = _ipv4_bytes(packet[12:16])
    dst = _ipv4_bytes(packet[16:20])
    return src, dst


_MAX_LAG_HEAP_PACKETS = 4096
_PAUSE_HOLD_DUE = float('inf')

# Single source of truth — partial modes must never share state with full pause.
IMPAIR_OFF = 0
IMPAIR_PAUSE = 1
IMPAIR_PERCENT = 2
IMPAIR_SHAPE = 3


class IcsWinDivertLagGate:
    """
    Single WinDivert path for all Clumsy / ICS client impairment (Kill, Dupe, Advanced Lag,
    Percent Cut, Lag Switch, etc.): connection pause, percent loss, or shaped delay/jitter/cap.

    Pause holds traffic until unpause/OFF; queued packets are discarded on resume (not replayed)
    so the console is not kicked. Hotspot gateway ARP is untouched.
    """

    def __init__(self, victim_ip: str):
        self._victim = _ipv4_quad(victim_ip)
        self._dll: Optional[ctypes.WinDLL] = None
        self._handles: list[int] = []
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._blocking = False
        self._hold_pause = True
        self._direction = 'both'
        self._delay_ms = 0
        self._loss_pct = 0
        self._discard_heap = False
        self._delay_out_ms = 0
        self._delay_in_ms = 0
        self._jitter_out_ms = 0
        self._jitter_in_ms = 0
        self._loss_out = 0
        self._loss_in = 0
        self._cap_out_bps = 0.0
        self._cap_in_bps = 0.0
        self._bucket_out = 0.0
        self._bucket_in = 0.0
        self._last_bucket = 0.0
        self._pass_cut_active = False
        self._pass_out_pct = 100
        self._pass_in_pct = 100
        self._byte_budget_out = 0.0
        self._byte_budget_in = 0.0
        self._packets_seen = 0
        self._packets_matched = 0
        self._packets_held = 0
        self._open_layers: list[int] = []
        self._downstream_prefix = '192.168.137.'
        self._subnet_capture = False
        self._impair_mode = IMPAIR_OFF

    @property
    def victim_ip(self) -> str:
        return self._victim

    def set_victim_ip(self, victim_ip: str) -> None:
        """Pin/live-update PS5 hotspot IP (ARP can lag behind the device table)."""
        ip = _ipv4_quad(victim_ip)
        if ip:
            with self._lock:
                self._victim = ip

    @property
    def packets_seen(self) -> int:
        return int(self._packets_seen)

    @property
    def packets_matched(self) -> int:
        return int(self._packets_matched)

    @property
    def packets_held(self) -> int:
        return int(self._packets_held)

    @property
    def is_blocking(self) -> bool:
        with self._lock:
            return bool(self._blocking)

    @property
    def active_layers(self) -> tuple[int, ...]:
        return tuple(self._open_layers)

    def is_running(self) -> bool:
        th = self._thread
        return th is not None and th.is_alive() and bool(self._handles)

    def start(self, direction: str = 'both') -> None:
        d = str(direction or 'both').strip().lower()
        if d not in ('both', 'in', 'out'):
            d = 'both'
        if self.is_running():
            with self._lock:
                self._direction = d
            return
        self.stop(join_timeout=0.2)
        self._stop.clear()
        with self._lock:
            self._direction = str(direction or 'both').strip().lower()
            if self._direction not in ('both', 'in', 'out'):
                self._direction = 'both'
            self._blocking = False
            self._discard_heap = False
        dll_path, sys_path = _windivert_materialize_paths()
        if not dll_path or not sys_path:
            inst_dll, inst_sys = _windivert_install_paths()
            if not inst_dll or not inst_sys:
                raise OSError(
                    'WinDivert not installed under ZubCut\\windivert — '
                    'reinstall with Clumsy mode checked.'
                )
            raise OSError('WinDivert could not be copied to %LOCALAPPDATA%\\ZubCut\\windivert')
        repaired, _repair_note = _windivert_repair_stale_service(sys_path)
        if not repaired:
            raise OSError(_repair_note)
        self._dll = _windivert_load_dll(dll_path, sys_path)
        _bind_windivert_api(self._dll)
        vip = self._victim
        try:
            from tools.clumsy_inline import clumsy_ics_downstream_prefix

            prefix = clumsy_ics_downstream_prefix()
        except Exception:
            prefix = '192.168.137.'
        self._downstream_prefix = prefix
        h, layer, desc = _open_best_windivert_handle(self._dll, vip, prefix)
        if h < 0:
            last_err = _windivert_last_error_message()
            hint = 'Run ZubCut as Administrator.'
            if last_err:
                raise OSError(f'WinDivertOpen failed: {last_err} {hint}')
            raise OSError(f'WinDivertOpen failed. {hint}')
        self._handles = [h]
        self._open_layers = [layer]
        self._subnet_capture = desc == 'subnet'
        self._packets_seen = 0
        self._packets_matched = 0
        self._packets_held = 0
        self._thread = threading.Thread(
            target=self._run_loop,
            name='ics_windivert_lag_gate',
            daemon=True,
        )
        self._thread.start()

    def set_blocking(
        self,
        block: bool,
        *,
        mode: str | None = None,
        delay_ms: int | None = None,
        loss_pct: int | None = None,
    ) -> None:
        with self._lock:
            self._blocking = bool(block)
            if mode is not None:
                m = str(mode).strip().lower()
                self._hold_pause = m != 'delay'
            if delay_ms is not None:
                self._delay_ms = max(0, min(2000, int(delay_ms)))
            if loss_pct is not None:
                self._loss_pct = max(0, min(100, int(loss_pct)))
            if block:
                self._impair_mode = IMPAIR_PAUSE
                self._clear_percent_cut_unlocked()
            else:
                self._impair_mode = IMPAIR_OFF
                self._discard_heap = True

    def _clear_percent_cut_unlocked(self) -> None:
        self._pass_cut_active = False
        self._pass_out_pct = 100
        self._pass_in_pct = 100
        self._byte_budget_out = 0.0
        self._byte_budget_in = 0.0

    @staticmethod
    def _passes_byte_ratio(pass_pct: int, budget: float, pkt_size: int) -> Tuple[bool, float]:
        """
        Tokenless byte budget (same model as MITM forwarder ``_passes_ratio``).
        Returns (allowed, updated_budget).
        """
        pct = max(0, min(100, int(pass_pct)))
        if pct <= 0:
            return False, budget
        if pct >= 100:
            return True, budget
        size = max(1, int(pkt_size))
        grant = (size * pct) / 100.0
        budget += grant
        if budget >= size:
            return True, budget - float(size)
        return False, budget

    def clear_blocking_pause(self) -> None:
        """Leave kill/lag/dupe full-pause mode; discard held packets (no replay burst)."""
        with self._lock:
            self._impair_mode = IMPAIR_OFF
            self._blocking = False
            self._hold_pause = False
            self._delay_ms = 0
            self._loss_pct = 0
            self._discard_heap = True

    def apply_percent_cut(self, cut_pct: int) -> None:
        """
        Partial cut on hotspot (WinDivert): ``cut_pct`` = share of traffic to drop;
        ``100 - cut_pct`` is forwarded using a byte budget (not pause/hold).
        """
        cut = max(0, min(100, int(cut_pct)))
        allow = max(0, 100 - cut)
        with self._lock:
            self._impair_mode = IMPAIR_OFF if cut <= 0 else IMPAIR_PERCENT
            self._blocking = False
            self._hold_pause = False
            self._loss_pct = 0
            self._delay_ms = 0
            self._delay_out_ms = 0
            self._delay_in_ms = 0
            self._jitter_out_ms = 0
            self._jitter_in_ms = 0
            self._loss_out = 0
            self._loss_in = 0
            self._cap_out_bps = 0.0
            self._cap_in_bps = 0.0
            if cut <= 0:
                self._clear_percent_cut_unlocked()
            else:
                self._pass_cut_active = True
                self._pass_out_pct = allow
                self._pass_in_pct = allow
                self._byte_budget_out = 0.0
                self._byte_budget_in = 0.0
            self._discard_heap = True

    def apply_shaping_params(
        self,
        delay_out_ms: int,
        delay_in_ms: int,
        jitter_out_ms: int,
        jitter_in_ms: int,
        loss_out: int,
        loss_in: int,
        max_kbps_out: float,
        max_kbps_in: float,
    ) -> None:
        with self._lock:
            self._delay_out_ms = max(0, int(delay_out_ms))
            self._delay_in_ms = max(0, int(delay_in_ms))
            self._jitter_out_ms = max(0, int(jitter_out_ms))
            self._jitter_in_ms = max(0, int(jitter_in_ms))
            self._loss_out = max(0, min(100, int(loss_out)))
            self._loss_in = max(0, min(100, int(loss_in)))
            self._cap_out_bps = max(0.0, float(max_kbps_out)) * 1000.0 / 8.0
            self._cap_in_bps = max(0.0, float(max_kbps_in)) * 1000.0 / 8.0
            shaping_on = self._shaping_active_unlocked()
            self._impair_mode = IMPAIR_SHAPE if shaping_on else IMPAIR_OFF
            self._blocking = False
            self._hold_pause = False
            self._loss_pct = 0
            self._delay_ms = 0
            self._clear_percent_cut_unlocked()
            self._discard_heap = True

    def pause_connection(self) -> None:
        """Hold all shaped victim traffic (lag/kill/dupe block phase)."""
        with self._lock:
            self._clear_percent_cut_unlocked()
            self._delay_out_ms = 0
            self._delay_in_ms = 0
            self._jitter_out_ms = 0
            self._jitter_in_ms = 0
            self._loss_out = 0
            self._loss_in = 0
            self._cap_out_bps = 0.0
            self._cap_in_bps = 0.0
            self._impair_mode = IMPAIR_PAUSE
            self._blocking = True
            self._hold_pause = True
            self._delay_ms = 0
            self._loss_pct = 0
            self._discard_heap = False

    def resume_from_pause(self) -> None:
        """End pause/hold without stopping the gate thread (lag allow phase / unpause)."""
        with self._lock:
            self._impair_mode = IMPAIR_OFF
            self._clear_percent_cut_unlocked()
            self._delay_out_ms = 0
            self._delay_in_ms = 0
            self._jitter_out_ms = 0
            self._jitter_in_ms = 0
            self._loss_out = 0
            self._loss_in = 0
            self._cap_out_bps = 0.0
            self._cap_in_bps = 0.0
            self._blocking = False
            self._hold_pause = False
            self._delay_ms = 0
            self._loss_pct = 0
            self._discard_heap = True

    def clear_shaping(self) -> None:
        with self._lock:
            self._impair_mode = IMPAIR_OFF
            self._clear_percent_cut_unlocked()
            self._delay_out_ms = 0
            self._delay_in_ms = 0
            self._jitter_out_ms = 0
            self._jitter_in_ms = 0
            self._loss_out = 0
            self._loss_in = 0
            self._cap_out_bps = 0.0
            self._cap_in_bps = 0.0
            self._discard_heap = True

    def _percent_cut_active_unlocked(self) -> bool:
        return bool(self._pass_cut_active)

    def _shaping_active_unlocked(self) -> bool:
        return (
            self._delay_out_ms > 0
            or self._delay_in_ms > 0
            or self._jitter_out_ms > 0
            or self._jitter_in_ms > 0
            or self._loss_out > 0
            or self._loss_in > 0
            or self._cap_out_bps > 0
            or self._cap_in_bps > 0
        )

    def _tick_buckets_unlocked(self, dt: float) -> None:
        if self._cap_out_bps > 0:
            self._bucket_out = min(self._cap_out_bps, self._bucket_out + self._cap_out_bps * dt)
        if self._cap_in_bps > 0:
            self._bucket_in = min(self._cap_in_bps, self._bucket_in + self._cap_in_bps * dt)

    def set_direction(self, direction: str) -> None:
        with self._lock:
            d = str(direction or 'both').strip().lower()
            self._direction = d if d in ('both', 'in', 'out') else 'both'

    def prepare_stop(self) -> None:
        with self._lock:
            self._impair_mode = IMPAIR_OFF
            self._blocking = False
            self._discard_heap = True

    def stop(self, join_timeout: float = 0.15) -> None:
        self.prepare_stop()
        self._stop.set()
        handles = list(self._handles)
        if handles and self._dll is not None:
            for h in handles:
                try:
                    self._dll.WinDivertShutdown(h, WINDIVERT_SHUTDOWN_BOTH)
                except Exception:
                    pass
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout=max(0.05, float(join_timeout)))
        self._thread = None
        if handles and self._dll is not None:
            for h in handles:
                try:
                    self._dll.WinDivertClose(h)
                except Exception:
                    pass
        self._handles = []
        self._open_layers = []
        self._dll = None

    def _shapes_packet(
        self, direction: str, *, from_victim: bool, to_victim: bool
    ) -> bool:
        if direction == 'both':
            return from_victim or to_victim
        if direction == 'in':
            return to_victim
        if direction == 'out':
            return from_victim
        return True

    def _send_immediate(self, h, dll, pkt: bytes, addr_b: bytes, send_len_ptr) -> None:
        pkt_buf = (ctypes.c_ubyte * len(pkt)).from_buffer_copy(pkt)
        addr_buf = (ctypes.c_ubyte * len(addr_b)).from_buffer_copy(addr_b)
        send_len_ptr.value = 0
        dll.WinDivertSend(
            h,
            ctypes.cast(pkt_buf, ctypes.c_void_p),
            len(pkt),
            send_len_ptr,
            ctypes.cast(addr_buf, ctypes.c_void_p),
        )

    def _recv_one(self, dll, h, buf, addr, recv_len, addr_len) -> Optional[Tuple[bytes, bytes]]:
        recv_len.value = 0
        addr_len.value = ADDR_BUF
        ok = dll.WinDivertRecvEx(
            h,
            ctypes.cast(buf, ctypes.c_void_p),
            MAX_PACKET,
            ctypes.byref(recv_len),
            ctypes.c_uint64(WINDIVERT_RECV_FLAG_NOBLOCK),
            ctypes.cast(addr, ctypes.c_void_p),
            ctypes.byref(addr_len),
            None,
        )
        if not ok:
            return None
        n = int(recv_len.value)
        if n <= 0:
            return None
        pkt = bytes(ctypes.string_at(ctypes.addressof(buf), n))
        addr_b = bytes(ctypes.string_at(ctypes.addressof(addr), int(addr_len.value)))
        return pkt, addr_b

    def _run_loop(self) -> None:
        assert self._dll is not None
        dll = self._dll
        handles = list(self._handles)
        if not handles:
            return
        buf = (ctypes.c_ubyte * MAX_PACKET)()
        addr = (ctypes.c_ubyte * ADDR_BUF)()
        recv_len = ctypes.c_uint(0)
        addr_len = ctypes.c_uint(ADDR_BUF)
        send_len = ctypes.c_uint(0)
        kernel32 = ctypes.windll.kernel32
        victim = self._victim
        subnet_prefix = getattr(self, '_downstream_prefix', '192.168.137.')
        heap: list[Tuple[float, bytes, bytes, int]] = []
        from tools.mitm_compound_loss import CAP_OVERFLOW_LOSS_PCT, should_drop_compounded

        while not self._stop.is_set():
            now = time.perf_counter()
            impair_mode = IMPAIR_OFF
            with self._lock:
                if self._discard_heap:
                    self._discard_heap = False
                    heap.clear()
                impair_mode = int(self._impair_mode)
                blocking = self._blocking
                hold_pause = self._hold_pause
                direction = self._direction
                delay_ms = self._delay_ms
                loss_pct = self._loss_pct
                shaping = impair_mode == IMPAIR_SHAPE
                d_out = self._delay_out_ms
                d_in = self._delay_in_ms
                j_out = self._jitter_out_ms
                j_in = self._jitter_in_ms
                l_out = self._loss_out
                l_in = self._loss_in
                cap_out = self._cap_out_bps
                cap_in = self._cap_in_bps
                pass_cut = impair_mode == IMPAIR_PERCENT
                pass_out_pct = self._pass_out_pct
                pass_in_pct = self._pass_in_pct
                budget_out = self._byte_budget_out
                budget_in = self._byte_budget_in
                if shaping:
                    if self._last_bucket <= 0:
                        self._last_bucket = now
                    dt = max(0.0, now - self._last_bucket)
                    self._last_bucket = now
                    self._tick_buckets_unlocked(dt)

            while heap and heap[0][0] <= now:
                due = heap[0][0]
                if math.isinf(due) or due >= _PAUSE_HOLD_DUE:
                    heapq.heappop(heap)
                    continue
                if impair_mode == IMPAIR_PAUSE and hold_pause:
                    heapq.heappop(heap)
                    continue
                _, pkt_b, addr_b, h_send = heapq.heappop(heap)
                if self._stop.is_set():
                    break
                self._send_immediate(h_send, dll, pkt_b, addr_b, ctypes.byref(send_len))

            got_pkt = False
            for h in handles:
                got = self._recv_one(dll, h, buf, addr, recv_len, addr_len)
                if got is None:
                    err = kernel32.GetLastError()
                    if err not in (ERROR_NO_DATA, 0, ERROR_INSUFFICIENT_BUFFER):
                        time.sleep(0.001)
                    continue
                got_pkt = True
                pkt, addr_b = got
                self._packets_seen += 1
                # Reinjected packets must pass through without percent/shape re-apply
                # (otherwise byte budgets drain twice and partial cut looks like Kill).
                if _windivert_addr_impostor(addr_b):
                    self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                    continue
                parsed = _parse_ipv4_src_dst(pkt)
                if not parsed:
                    self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                    continue

                src, dst = parsed
                subnet_mode = bool(getattr(self, '_subnet_capture', False))
                if subnet_mode:
                    gw = _ics_gateway_ip(subnet_prefix)
                    if gw and src == gw and dst == gw:
                        self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                        continue
                elif not _packet_matches_hotspot_client(
                    src, dst, victim, subnet_prefix
                ):
                    self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                    continue
                self._packets_matched += 1

                outbound = _windivert_addr_outbound(addr_b)
                from_v, to_v, active_victim = _victim_packet_roles(
                    src,
                    dst,
                    victim,
                    subnet_prefix,
                    outbound=outbound,
                    subnet_capture=subnet_mode,
                )
                if active_victim and active_victim != victim:
                    victim = active_victim
                    with self._lock:
                        self._victim = active_victim
                if not self._shapes_packet(direction, from_victim=from_v, to_victim=to_v):
                    self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                    continue

                is_from_victim = from_v
                is_to_victim = to_v
                n = len(pkt)

                # Subnet filters can see gateway / other clients — only impair PS5 flows.
                if not (from_v or to_v):
                    self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                    continue

                if impair_mode == IMPAIR_OFF:
                    self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                    continue

                if impair_mode == IMPAIR_PERCENT and (is_from_victim or is_to_victim):
                    allow_pkt = True
                    if is_from_victim:
                        allow_pkt, budget_out = self._passes_byte_ratio(
                            pass_out_pct, budget_out, n
                        )
                    elif is_to_victim:
                        allow_pkt, budget_in = self._passes_byte_ratio(
                            pass_in_pct, budget_in, n
                        )
                    with self._lock:
                        self._byte_budget_out = budget_out
                        self._byte_budget_in = budget_in
                    if not allow_pkt:
                        continue
                    self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                    continue

                if impair_mode == IMPAIR_SHAPE and (is_from_victim or is_to_victim):
                    cap_ok = True
                    if cap_out > 0 and is_from_victim:
                        cap_ok = self._bucket_out >= float(n)
                    if cap_ok and cap_in > 0 and is_to_victim:
                        cap_ok = self._bucket_in >= float(n)
                    loss_shape = l_out if is_from_victim else (l_in if is_to_victim else 0)
                    cap_active = (cap_out > 0 and is_from_victim) or (
                        cap_in > 0 and is_to_victim
                    )
                    if should_drop_compounded(
                        loss_shape,
                        cap_active=cap_active,
                        cap_can_forward=cap_ok,
                        overflow_loss_pct=CAP_OVERFLOW_LOSS_PCT,
                    ):
                        continue
                    if cap_active:
                        with self._lock:
                            if cap_out > 0 and is_from_victim:
                                if self._bucket_out < float(n):
                                    continue
                                self._bucket_out -= float(n)
                            if cap_in > 0 and is_to_victim:
                                if self._bucket_in < float(n):
                                    continue
                                self._bucket_in -= float(n)
                    extra_j = 0
                    base_d = 0
                    if is_from_victim:
                        base_d = d_out
                        extra_j = random.randint(0, j_out) if j_out else 0
                    elif is_to_victim:
                        base_d = d_in
                        extra_j = random.randint(0, j_in) if j_in else 0
                    shape_delay = base_d + extra_j
                    if shape_delay > 0:
                        if len(heap) >= _MAX_LAG_HEAP_PACKETS:
                            heapq.heappop(heap)
                        due = time.perf_counter() + shape_delay / 1000.0
                        heapq.heappush(heap, (due, pkt, addr_b, h))
                        continue
                    self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                    continue

                if impair_mode == IMPAIR_PAUSE and blocking and (is_from_victim or is_to_victim):
                    if not hold_pause:
                        if loss_pct > 0:
                            if random.randint(1, 100) <= loss_pct:
                                continue
                            self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                            continue
                        if delay_ms > 0:
                            if len(heap) >= _MAX_LAG_HEAP_PACKETS:
                                heapq.heappop(heap)
                            due = time.perf_counter() + delay_ms / 1000.0
                            heapq.heappush(heap, (due, pkt, addr_b, h))
                            continue
                        self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                        continue
                    if len(heap) >= _MAX_LAG_HEAP_PACKETS:
                        heapq.heappop(heap)
                    heapq.heappush(heap, (_PAUSE_HOLD_DUE, pkt, addr_b, h))
                    self._packets_held += 1
                    continue

                self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                continue

            if not got_pkt:
                time.sleep(0.001)

        heap.clear()


class IcsWinDivertShaper:
    """Advanced Lag on ICS — thin wrapper over :class:`IcsWinDivertLagGate`."""

    def __init__(self, victim_ip: str):
        self._gate = IcsWinDivertLagGate(victim_ip)

    @property
    def victim_ip(self) -> str:
        return self._gate.victim_ip

    def apply_params(
        self,
        delay_out_ms: int,
        delay_in_ms: int,
        jitter_out_ms: int,
        jitter_in_ms: int,
        loss_out: int,
        loss_in: int,
        max_kbps_out: float,
        max_kbps_in: float,
    ) -> None:
        self._gate.apply_shaping_params(
            delay_out_ms,
            delay_in_ms,
            jitter_out_ms,
            jitter_in_ms,
            loss_out,
            loss_in,
            max_kbps_out,
            max_kbps_in,
        )

    def start(
        self,
        delay_out_ms: int,
        delay_in_ms: int,
        jitter_out_ms: int,
        jitter_in_ms: int,
        loss_out: int,
        loss_in: int,
        max_kbps_out: float,
        max_kbps_in: float,
    ) -> None:
        self._gate.start(direction='both')
        self._gate.set_blocking(False)
        self._gate.apply_shaping_params(
            delay_out_ms,
            delay_in_ms,
            jitter_out_ms,
            jitter_in_ms,
            loss_out,
            loss_in,
            max_kbps_out,
            max_kbps_in,
        )

    def stop(self, join_timeout: float = 2.0) -> None:
        self._gate.clear_shaping()
        self._gate.prepare_stop()
        self._gate.stop(join_timeout=join_timeout)
