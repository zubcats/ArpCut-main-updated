"""
ICS / Clumsy-mode advanced shaping via WinDivert (driver path).

Used only when Clumsy mode is on, WinDivert is available, and the selected device
matches the detected ICS client IP. Falls back to MITM forwarder otherwise.

Requires Administrator and WinDivert.dll next to the executable (or in ./windivert/).
"""

from __future__ import annotations

import ctypes
import heapq
import os
import random
import sys
import threading
import time
from ctypes import wintypes
from typing import Optional, Tuple

WINDIVERT_LAYER_NETWORK = 0
WINDIVERT_LAYER_NETWORK_FORWARD = 1
WINDIVERT_SHUTDOWN_BOTH = 2
WINDIVERT_RECV_FLAG_NOBLOCK = 0x0001
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
ERROR_NO_DATA = 232
ERROR_INSUFFICIENT_BUFFER = 122

ADDR_BUF = 256
MAX_PACKET = 0xFFFF


def _windivert_dll_path() -> Optional[str]:
    if not sys.platform.startswith('win'):
        return None
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.getcwd()
    for rel in ('windivert\\WinDivert.dll', 'WinDivert.dll'):
        p = os.path.join(base, rel)
        if os.path.isfile(p):
            return p
    return None


def _ipv4_quad(ip: str) -> str:
    return (ip or '').strip()


def _ipv4_bytes(b: bytes) -> str:
    return '.'.join(str(x) for x in b)


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


class IcsWinDivertShaper:
    """
    Divert IPv4 traffic to/from a single host; apply loss, simple token-bucket caps,
    and queued delay (fixed + optional jitter) before reinjecting.
    """

    def __init__(self, victim_ip: str):
        self._victim = _ipv4_quad(victim_ip)
        self._dll: Optional[ctypes.WinDLL] = None
        self._handle: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # Mutable shaping params (updated from GUI thread)
        self._delay_out_ms = 0
        self._delay_in_ms = 0
        self._jitter_out_ms = 0
        self._jitter_in_ms = 0
        self._loss_out = 0
        self._loss_in = 0
        self._cap_out_bps = 0.0  # bytes/sec (max_kbps * 1000 / 8)
        self._cap_in_bps = 0.0
        self._bucket_out = 0.0
        self._bucket_in = 0.0
        self._last_bucket = 0.0

    def _tick_buckets(self, dt: float) -> None:
        with self._lock:
            if self._cap_out_bps > 0:
                self._bucket_out = min(self._cap_out_bps, self._bucket_out + self._cap_out_bps * dt)
            if self._cap_in_bps > 0:
                self._bucket_in = min(self._cap_in_bps, self._bucket_in + self._cap_in_bps * dt)

    def _cap_peek(self, n: int, is_from_victim: bool, is_to_victim: bool) -> bool:
        """True if bandwidth cap allows this packet (does not deduct)."""
        with self._lock:
            if self._cap_out_bps > 0 and is_from_victim:
                if self._bucket_out < float(n):
                    return False
            if self._cap_in_bps > 0 and is_to_victim:
                if self._bucket_in < float(n):
                    return False
        return True

    def _cap_commit(self, n: int, is_from_victim: bool, is_to_victim: bool) -> bool:
        with self._lock:
            if self._cap_out_bps > 0 and is_from_victim:
                if self._bucket_out < float(n):
                    return False
                self._bucket_out -= float(n)
            if self._cap_in_bps > 0 and is_to_victim:
                if self._bucket_in < float(n):
                    return False
                self._bucket_in -= float(n)
        return True

    def _consume_caps(self, n: int, is_from_victim: bool, is_to_victim: bool) -> bool:
        """Return False if packet should be dropped (over cap)."""
        if not self._cap_peek(n, is_from_victim, is_to_victim):
            return False
        return self._cap_commit(n, is_from_victim, is_to_victim)

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
        with self._lock:
            self._delay_out_ms = max(0, int(delay_out_ms))
            self._delay_in_ms = max(0, int(delay_in_ms))
            self._jitter_out_ms = max(0, int(jitter_out_ms))
            self._jitter_in_ms = max(0, int(jitter_in_ms))
            self._loss_out = max(0, min(100, int(loss_out)))
            self._loss_in = max(0, min(100, int(loss_in)))
            self._cap_out_bps = max(0.0, float(max_kbps_out)) * 1000.0 / 8.0
            self._cap_in_bps = max(0.0, float(max_kbps_in)) * 1000.0 / 8.0

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
        self.stop(join_timeout=3.0)
        self.apply_params(
            delay_out_ms,
            delay_in_ms,
            jitter_out_ms,
            jitter_in_ms,
            loss_out,
            loss_in,
            max_kbps_out,
            max_kbps_in,
        )
        self._stop.clear()
        dll_path = _windivert_dll_path()
        if not dll_path:
            raise OSError('WinDivert.dll not found (expected next to ZubCut or in windivert\\).')
        self._dll = ctypes.WinDLL(dll_path)
        self._bind_api()
        vip = self._victim
        filt = f'ip and (ip.SrcAddr == {vip} or ip.DstAddr == {vip})'
        hrv = self._open_handle(filt, WINDIVERT_LAYER_NETWORK)
        if hrv < 0:
            hrv = self._open_handle(filt, WINDIVERT_LAYER_NETWORK_FORWARD)
        if hrv < 0:
            raise OSError('WinDivertOpen failed (run as Administrator; check WinDivert driver).')
        self._handle = hrv
        self._thread = threading.Thread(
            target=self._run_loop,
            name='ics_windivert_shaper',
            daemon=True,
        )
        self._thread.start()

    def _open_handle(self, filt: str, layer: int) -> int:
        assert self._dll is not None
        f = filt.encode('ascii', errors='ignore')
        h = self._dll.WinDivertOpen(ctypes.c_char_p(f), ctypes.c_int(layer), ctypes.c_int16(0), ctypes.c_uint64(0))
        if not h:
            return -1
        hv = int(h) if not isinstance(h, ctypes.c_void_p) else int(h.value or 0)
        maxptr = (1 << 64) - 1
        if hv == 0 or hv == maxptr:
            return -1
        return hv

    def _bind_api(self) -> None:
        assert self._dll is not None
        d = self._dll
        d.WinDivertOpen.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int16,
            ctypes.c_uint64,
        ]
        d.WinDivertOpen.restype = ctypes.c_void_p

        d.WinDivertRecvEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_void_p,
        ]
        d.WinDivertRecvEx.restype = wintypes.BOOL

        d.WinDivertSend.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_void_p,
        ]
        d.WinDivertSend.restype = wintypes.BOOL

        d.WinDivertShutdown.argtypes = [wintypes.HANDLE, ctypes.c_int]
        d.WinDivertShutdown.restype = wintypes.BOOL

        d.WinDivertClose.argtypes = [wintypes.HANDLE]
        d.WinDivertClose.restype = wintypes.BOOL

    def stop(self, join_timeout: float = 2.0) -> None:
        self._stop.set()
        h = self._handle
        if h is not None and self._dll is not None:
            try:
                self._dll.WinDivertShutdown(h, WINDIVERT_SHUTDOWN_BOTH)
            except Exception:
                pass
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout=join_timeout)
        self._thread = None
        if h is not None and self._dll is not None:
            try:
                self._dll.WinDivertClose(h)
            except Exception:
                pass
        self._handle = None
        self._dll = None

    def _run_loop(self) -> None:
        assert self._dll is not None
        dll = self._dll
        h = self._handle
        assert h is not None
        buf = (ctypes.c_ubyte * MAX_PACKET)()
        addr = (ctypes.c_ubyte * ADDR_BUF)()
        recv_len = ctypes.c_uint(0)
        addr_len = ctypes.c_uint(ADDR_BUF)
        send_len = ctypes.c_uint(0)
        kernel32 = ctypes.windll.kernel32
        heap: list[Tuple[float, bytes, bytes]] = []
        victim = self._victim

        while not self._stop.is_set():
            now = time.perf_counter()
            while heap and heap[0][0] <= now:
                _, pkt_b, addr_b = heapq.heappop(heap)
                if self._stop.is_set():
                    break
                send_len.value = 0
                pkt_buf = (ctypes.c_ubyte * len(pkt_b)).from_buffer_copy(pkt_b)
                addr_buf = (ctypes.c_ubyte * len(addr_b)).from_buffer_copy(addr_b)
                dll.WinDivertSend(
                    h,
                    ctypes.cast(pkt_buf, ctypes.c_void_p),
                    len(pkt_b),
                    ctypes.byref(send_len),
                    ctypes.cast(addr_buf, ctypes.c_void_p),
                )
                del pkt_buf, addr_buf

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
                err = kernel32.GetLastError()
                if err == ERROR_NO_DATA:
                    break
                if err in (0, ERROR_INSUFFICIENT_BUFFER):
                    time.sleep(0.001)
                    continue
                time.sleep(0.002)
                continue

            n = int(recv_len.value)
            if n <= 0:
                continue
            pkt = bytes(ctypes.string_at(ctypes.addressof(buf), n))
            addr_b = bytes(ctypes.string_at(ctypes.addressof(addr), int(addr_len.value)))

            parsed = _parse_ipv4_src_dst(pkt)
            if not parsed:
                self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))
                continue
            src, dst = parsed
            is_from_victim = src == victim
            is_to_victim = dst == victim

            with self._lock:
                d_out = self._delay_out_ms
                d_in = self._delay_in_ms
                j_out = self._jitter_out_ms
                j_in = self._jitter_in_ms
                l_out = self._loss_out
                l_in = self._loss_in
                cap_out = self._cap_out_bps
                cap_in = self._cap_in_bps

            now = time.perf_counter()
            if self._last_bucket <= 0:
                self._last_bucket = now
            dt = max(0.0, now - self._last_bucket)
            self._last_bucket = now
            self._tick_buckets(dt)

            cap_ok = self._cap_peek(n, is_from_victim, is_to_victim)
            loss_pct = l_out if is_from_victim else (l_in if is_to_victim else 0)
            cap_active = (cap_out > 0 and is_from_victim) or (cap_in > 0 and is_to_victim)
            from tools.mitm_compound_loss import CAP_OVERFLOW_LOSS_PCT, should_drop_compounded

            if should_drop_compounded(
                loss_pct,
                cap_active=cap_active,
                cap_can_forward=cap_ok,
                overflow_loss_pct=CAP_OVERFLOW_LOSS_PCT,
            ):
                continue

            if cap_active and not self._cap_commit(n, is_from_victim, is_to_victim):
                continue

            extra_j = 0
            base_d = 0
            if is_from_victim:
                base_d = d_out
                extra_j = random.randint(0, j_out) if j_out else 0
            elif is_to_victim:
                base_d = d_in
                extra_j = random.randint(0, j_in) if j_in else 0
            delay_ms = base_d + extra_j
            if delay_ms > 0:
                due = time.perf_counter() + delay_ms / 1000.0
                heapq.heappush(heap, (due, pkt, addr_b))
            else:
                self._send_immediate(h, dll, pkt, addr_b, ctypes.byref(send_len))

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
