"""
Impairment toggle coordinator + teardown gate (extracted from MainWindow).

Slice 1: pure toggle gating / labels (no Qt, no network I/O).
Slice 2: teardown busy latch so Kill/Lag/Dupe/Pct cannot race OFF work.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


def toggle_kind_label(kind: str) -> str:
    return {
        'kill': 'Kill',
        'lag': 'Lag Switch',
        'dupe': 'Dupe',
        'pctcut': 'Percent Cut',
        'mitmshape': 'MITM shaping',
    }.get(kind, kind)


@dataclass
class ImpairmentFlowState:
    """Snapshot of which impairment flows are latched ON."""

    lag_active: bool = False
    lag_device_mac: Optional[str] = None
    dupe_active: bool = False
    dupe_device_mac: Optional[str] = None
    percent_cut_active: bool = False
    percent_cut_device_mac: Optional[str] = None
    mitm_shaping_active: bool = False
    mitm_shaping_mac: Optional[str] = None
    killed_devices: dict = field(default_factory=dict)

    def has_explicit_kill_active(self) -> bool:
        return any(bool(v) for v in (self.killed_devices or {}).values())


class ImpairmentTeardownGate:
    """Serialize OFF/teardown so a new ON cannot race ARP/WinDivert cleanup."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kind: Optional[str] = None
        self._mac: Optional[str] = None
        self._started: float = 0.0

    def begin(self, kind: str, mac: Optional[str] = None) -> bool:
        """Claim the gate. Returns False if another teardown is already in progress."""
        with self._lock:
            if self._kind is not None:
                return False
            self._kind = str(kind or '') or 'unknown'
            self._mac = (str(mac).strip() if mac else None) or None
            self._started = time.monotonic()
            return True

    def end(self, kind: Optional[str] = None) -> None:
        with self._lock:
            if kind and self._kind and kind != self._kind:
                return
            self._kind = None
            self._mac = None
            self._started = 0.0

    def busy(self) -> bool:
        with self._lock:
            return self._kind is not None

    def busy_for(self, mac: Optional[str] = None) -> bool:
        with self._lock:
            if self._kind is None:
                return False
            if not mac:
                return True
            if not self._mac:
                return True
            return str(mac).strip().lower() == str(self._mac).strip().lower()

    def snapshot(self) -> tuple[Optional[str], Optional[str]]:
        with self._lock:
            return self._kind, self._mac


class ImpairmentController:
    """
    Toggle coordinator used by MainWindow.

    ``state_provider`` returns a live ImpairmentFlowState (or compatible object).
    ``killed_profile_on`` optionally reports whether ``device`` already has Kill ON
    (allows lag/dupe to clear Kill on the same victim).
    """

    def __init__(
        self,
        *,
        state_provider: Callable[[], Any],
        killed_profile_on: Optional[Callable[[Any], bool]] = None,
        log: Optional[Callable[[str, str], None]] = None,
        teardown_gate: Optional[ImpairmentTeardownGate] = None,
    ) -> None:
        self._state_provider = state_provider
        self._killed_profile_on = killed_profile_on
        self._log = log
        self.teardown = teardown_gate or ImpairmentTeardownGate()
        self._edge_debounce: dict[str, tuple[Optional[str], Optional[str], float]] = {}

    def _state(self) -> Any:
        return self._state_provider()

    def active_toggle_kind(self) -> Optional[str]:
        st = self._state()
        if getattr(st, 'lag_active', False) and getattr(st, 'lag_device_mac', None):
            return 'lag'
        if getattr(st, 'dupe_active', False) and getattr(st, 'dupe_device_mac', None):
            return 'dupe'
        if getattr(st, 'mitm_shaping_active', False) and getattr(st, 'mitm_shaping_mac', None):
            return 'mitmshape'
        if getattr(st, 'percent_cut_active', False) and getattr(st, 'percent_cut_device_mac', None):
            return 'pctcut'
        killed = getattr(st, 'killed_devices', None) or {}
        if any(bool(v) for v in killed.values()):
            return 'kill'
        return None

    def toggle_start_blocked(self, requested_kind: str, device=None) -> bool:
        if self.teardown.busy():
            kind, _mac = self.teardown.snapshot()
            msg = (
                f'{toggle_kind_label(kind or "flow")} is still restoring. '
                'Wait a moment, then try again.'
            )
            if self._log:
                self._log(msg, 'restore')
            return True
        active_kind = self.active_toggle_kind()
        if active_kind and active_kind != requested_kind:
            if (
                requested_kind in ('dupe', 'lag')
                and active_kind == 'kill'
                and device is not None
                and self._killed_profile_on is not None
                and self._killed_profile_on(device)
            ):
                return False
            if self._log:
                self._log(
                    f'{toggle_kind_label(active_kind)} is active. Turn it off first.',
                    'block',
                )
            return True
        return False

    def ignore_duplicate_toggle_edge(self, kind: str, mac: Optional[str], edge: str) -> bool:
        if not mac:
            return False
        now = time.monotonic()
        prev = self._edge_debounce.get(kind)
        if (
            prev
            and prev[0] == mac
            and prev[1] == edge
            and now < prev[2]
        ):
            return True
        self._edge_debounce[kind] = (mac, edge, now + 0.03)
        return False
