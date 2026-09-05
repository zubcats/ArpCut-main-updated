"""Load the bundled Clumzy WinDivert engine (C DLL). Used only by Clumzy Mode."""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
import threading
from ctypes import c_char_p, c_float, c_int
from typing import Optional


def _app_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _cache_dir() -> str:
    base = os.environ.get('LOCALAPPDATA', '').strip()
    if not base:
        base = os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
    path = os.path.join(base, 'ZubCut', 'windivert')
    os.makedirs(path, exist_ok=True)
    return path


def _first_existing(*paths: str) -> Optional[str]:
    for path in paths:
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    return None


def clumzy_engine_dll_path() -> Optional[str]:
    here = _app_dir()
    meipass = getattr(sys, '_MEIPASS', '')
    native_out = os.path.join(here, 'native', 'clumzy_engine', 'out', 'clumzy_engine.dll')
    return _first_existing(
        os.path.join(here, 'clumzy_engine.dll'),
        os.path.join(here, 'windivert', 'clumzy_engine.dll'),
        os.path.join(meipass, 'clumzy_engine.dll') if meipass else '',
        native_out,
    )


def _windivert_pair() -> tuple[Optional[str], Optional[str]]:
    here = _app_dir()
    dll = _first_existing(
        os.path.join(here, 'windivert', 'WinDivert.dll'),
        os.path.join(here, 'WinDivert.dll'),
    )
    sys_p = _first_existing(
        os.path.join(here, 'windivert', 'WinDivert64.sys'),
        os.path.join(here, 'WinDivert64.sys'),
    )
    return dll, sys_p


def materialize_clumzy_runtime() -> tuple[Optional[str], Optional[str]]:
    """Colocate clumzy_engine.dll with WinDivert.dll/.sys in a no-space cache dir."""
    engine_src = clumzy_engine_dll_path()
    wd_dll, wd_sys = _windivert_pair()
    if not engine_src or not wd_dll or not wd_sys:
        return None, None
    cache = _cache_dir()
    dst_engine = os.path.join(cache, 'clumzy_engine.dll')
    dst_dll = os.path.join(cache, 'WinDivert.dll')
    dst_sys = os.path.join(cache, 'WinDivert64.sys')
    try:
        for src, dst in ((engine_src, dst_engine), (wd_dll, dst_dll), (wd_sys, dst_sys)):
            if not os.path.isfile(dst) or os.path.getsize(dst) != os.path.getsize(src):
                shutil.copy2(src, dst)
            elif os.path.getmtime(dst) < os.path.getmtime(src):
                shutil.copy2(src, dst)
    except OSError:
        return None, None
    if not os.path.isfile(dst_engine):
        return None, None
    return dst_engine, cache


class ClumzyEngine:
    def __init__(self, dll_path: str) -> None:
        self.dll = ctypes.WinDLL(dll_path)
        self.dll.clumzy_engine_init.restype = c_int
        self.dll.clumzy_is_admin.restype = c_int
        self.dll.clumzy_set_network.argtypes = [c_int]
        self.dll.clumzy_start.argtypes = [c_char_p, c_char_p, c_int]
        self.dll.clumzy_start.restype = c_int
        self.dll.clumzy_stop.restype = None
        self.dll.clumzy_is_running.restype = c_int
        self.dll.clumzy_enable.argtypes = [c_char_p, c_int]
        self.dll.clumzy_lag.argtypes = [c_int, c_int, c_int]
        self.dll.clumzy_drop.argtypes = [c_int, c_int, c_float]
        self.dll.clumzy_disconnect.argtypes = [c_int, c_int]
        self.dll.clumzy_bandwidth.argtypes = [c_int, c_int, c_int, c_int, c_int]
        self.dll.clumzy_throttle.argtypes = [c_int, c_int, c_float, c_int, c_int]
        self.dll.clumzy_duplicate.argtypes = [c_int, c_int, c_float, c_int]
        self.dll.clumzy_ood.argtypes = [c_int, c_int, c_float]
        self.dll.clumzy_tamper.argtypes = [c_int, c_int, c_float, c_int]
        self.dll.clumzy_reset.argtypes = [c_int, c_int, c_float]
        self._lock = threading.RLock()
        if self.dll.clumzy_engine_init() == 0:
            raise RuntimeError('clumzy_engine_init failed')

    def set_network(self, network_type: int) -> None:
        with self._lock:
            self.dll.clumzy_set_network(int(network_type))

    def start(self, filt: str) -> str | None:
        err = ctypes.create_string_buffer(512)
        with self._lock:
            if self.dll.clumzy_start(filt.encode('utf-8', 'replace'), err, 512) == 0:
                return err.value.decode('utf-8', 'replace') or 'Failed to start filtering.'
        return None

    def stop(self) -> None:
        with self._lock:
            self.dll.clumzy_stop()

    def is_running(self) -> bool:
        with self._lock:
            return bool(self.dll.clumzy_is_running())

    def enable(self, name: str, on: bool) -> None:
        with self._lock:
            self.dll.clumzy_enable(name.encode('ascii'), 1 if on else 0)

    def lag(self, inbound: int, outbound: int, time_ms: int) -> None:
        with self._lock:
            self.dll.clumzy_lag(int(inbound), int(outbound), int(time_ms))

    def drop(self, inbound: int, outbound: int, chance_pct: float) -> None:
        with self._lock:
            self.dll.clumzy_drop(int(inbound), int(outbound), c_float(chance_pct))

    def disconnect(self, inbound: int, outbound: int) -> None:
        with self._lock:
            self.dll.clumzy_disconnect(int(inbound), int(outbound))

    def bandwidth(self, inbound: int, outbound: int, limit: int, queue_size: int, kb: int) -> None:
        with self._lock:
            self.dll.clumzy_bandwidth(int(inbound), int(outbound), int(limit), int(queue_size), int(kb))

    def throttle(
        self,
        inbound: int,
        outbound: int,
        chance_pct: float,
        timeframe_ms: int,
        drop_throttled: int,
    ) -> None:
        with self._lock:
            self.dll.clumzy_throttle(
                int(inbound),
                int(outbound),
                c_float(chance_pct),
                int(timeframe_ms),
                int(drop_throttled),
            )

    def duplicate(self, inbound: int, outbound: int, chance_pct: float, count: int) -> None:
        with self._lock:
            self.dll.clumzy_duplicate(int(inbound), int(outbound), c_float(chance_pct), int(count))

    def ood(self, inbound: int, outbound: int, chance_pct: float) -> None:
        with self._lock:
            self.dll.clumzy_ood(int(inbound), int(outbound), c_float(chance_pct))

    def tamper(self, inbound: int, outbound: int, chance_pct: float, redo_checksum: int) -> None:
        with self._lock:
            self.dll.clumzy_tamper(
                int(inbound), int(outbound), c_float(chance_pct), int(redo_checksum)
            )


def load_clumzy_engine() -> ClumzyEngine:
    dll_path, cache = materialize_clumzy_runtime()
    if not dll_path or not cache:
        raise FileNotFoundError(
            'Clumzy engine or WinDivert files are missing. Reinstall ZubCut with Clumzy mode checked.'
        )
    old = os.getcwd()
    try:
        os.chdir(cache)
        return ClumzyEngine(dll_path)
    finally:
        try:
            os.chdir(old)
        except OSError:
            pass
