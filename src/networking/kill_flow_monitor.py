"""Live Kill-path flow stats (sniff + verdict). Never on the Kill click hot path."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import monotonic, time
from typing import Any, Callable, Optional

# Scapy / crash_feedback imported lazily — keep this module light for unit tests.


# Bytes/sec above this toward the victim counts as a WAN leak signal.
_LEAK_IN_BPS = 1500.0
# Victim→net activity while replies are near-zero → classic blackhole cut.
_ATTEMPT_OUT_BPS = 400.0


@dataclass(frozen=True)
class KillFlowVerdict:
    code: str
    label: str
    detail: str
    level: str  # 'ok' | 'warn' | 'fail' | 'idle'


def classify_kill_flow_verdict(
    *,
    kill_on: bool,
    lan_reachable: Optional[bool],
    mitm_armed: bool,
    ics_path: bool,
    out_bps: float,
    in_bps: float,
    saw_any_packets: bool,
) -> KillFlowVerdict:
    """Differentiate full cut vs not-in-path vs leak (for Kill monitor UI)."""
    if not kill_on:
        return KillFlowVerdict(
            code='WAITING',
            label='Waiting for Kill',
            detail='Open this window, then turn Kill ON for the selected device.',
            level='idle',
        )

    if lan_reachable is False:
        return KillFlowVerdict(
            code='LAN_DEAD',
            label='Not talking to device',
            detail='No LAN ARP/reply from this IP — wrong network, offline, or isolation.',
            level='fail',
        )

    in_path = bool(mitm_armed or ics_path)
    if not in_path:
        return KillFlowVerdict(
            code='NOT_ARMED',
            label='Kill ON — not in path',
            detail='UI Kill is ON but MITM/hotspot backend is not armed for this device.',
            level='fail',
        )

    if in_bps >= _LEAK_IN_BPS:
        return KillFlowVerdict(
            code='LEAKING',
            label='Leaking',
            detail='Internet→device traffic still hitting this PC — Kill is not holding a full cut.',
            level='warn',
        )

    if out_bps >= _ATTEMPT_OUT_BPS and in_bps < _LEAK_IN_BPS * 0.35:
        return KillFlowVerdict(
            code='CUT_ATTEMPTS',
            label='Full cut (attempts, no replies)',
            detail='Device→net attempts seen; almost no return path — classic blackhole Kill.',
            level='ok',
        )

    if saw_any_packets and in_bps < _LEAK_IN_BPS and out_bps < _ATTEMPT_OUT_BPS:
        return KillFlowVerdict(
            code='CUT_QUIET',
            label='Full cut (quiet)',
            detail='In path and quiet — either solid cut or the device went idle.',
            level='ok',
        )

    if in_path and not saw_any_packets and lan_reachable is not False:
        return KillFlowVerdict(
            code='CUT_OR_IDLE',
            label='In path — no frames yet',
            detail=(
                'Kill armed, but no victim frames on this NIC yet. '
                'Wake the console / start a game, or wait a few seconds.'
            ),
            level='ok',
        )

    return KillFlowVerdict(
        code='WATCHING',
        label='Watching',
        detail='Collecting live rates…',
        level='idle',
    )


class KillFlowSniffer:
    """Directional host sniff for one victim IP (background thread)."""

    def __init__(self) -> None:
        self._thread: Optional[Thread] = None
        self._stop = Event()
        self._lock = Lock()
        self._victim_ip = ''
        self._iface = ''
        self._out_bytes = 0
        self._in_bytes = 0
        self._out_packets = 0
        self._in_packets = 0
        self._flows: dict[tuple, dict[str, Any]] = defaultdict(
            lambda: {'out_bytes': 0, 'in_bytes': 0, 'out_packets': 0, 'in_packets': 0, 'proto': ''}
        )
        self._window_out = 0
        self._window_in = 0
        self._window_t0 = monotonic()
        self._out_bps = 0.0
        self._in_bps = 0.0
        self._callback: Optional[Callable[[], None]] = None
        self._last_pkt_at = 0.0

    def start(self, victim_ip: str, iface: str, on_update: Optional[Callable[[], None]] = None) -> None:
        self.stop()
        self._victim_ip = str(victim_ip or '').strip()
        self._iface = str(iface or '').strip()
        self._callback = on_update
        with self._lock:
            self._out_bytes = self._in_bytes = 0
            self._out_packets = self._in_packets = 0
            self._flows.clear()
            self._window_out = self._window_in = 0
            self._window_t0 = monotonic()
            self._out_bps = self._in_bps = 0.0
            self._last_pkt_at = 0.0
        if not self._victim_ip or not self._iface:
            return
        self._stop.clear()

        def _target() -> None:
            try:
                from tools.crash_feedback import safe_daemon_target

                safe_daemon_target(self._run)()
            except Exception:
                try:
                    self._run()
                except Exception:
                    pass

        self._thread = Thread(
            target=_target,
            name='zubcut-kill-flow-sniff',
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=0.25)
        self._thread = None
        self._stop.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = monotonic()
            dt = max(0.25, now - self._window_t0)
            # Refresh rates at least when snapshot is taken (UI timer).
            self._out_bps = self._window_out / dt
            self._in_bps = self._window_in / dt
            if dt >= 1.0:
                self._window_out = 0
                self._window_in = 0
                self._window_t0 = now
            flows = []
            for (peer, port, proto), st in self._flows.items():
                flows.append(
                    {
                        'peer': peer,
                        'port': int(port),
                        'proto': proto,
                        'out_bytes': int(st['out_bytes']),
                        'in_bytes': int(st['in_bytes']),
                        'out_packets': int(st['out_packets']),
                        'in_packets': int(st['in_packets']),
                    }
                )
            flows.sort(key=lambda r: r['out_bytes'] + r['in_bytes'], reverse=True)
            return {
                'out_bytes': self._out_bytes,
                'in_bytes': self._in_bytes,
                'out_packets': self._out_packets,
                'in_packets': self._in_packets,
                'out_bps': float(self._out_bps),
                'in_bps': float(self._in_bps),
                'saw_any': (self._out_packets + self._in_packets) > 0,
                'last_pkt_at': self._last_pkt_at,
                'flows': flows[:40],
                'running': bool(self._thread and self._thread.is_alive()),
            }

    def _run(self) -> None:
        try:
            from scapy.all import sniff
        except Exception:
            return
        bpf = f'host {self._victim_ip}'
        try:
            sniff(
                prn=self._process,
                filter=bpf,
                store=False,
                iface=self._iface,
                stop_filter=lambda _p: self._stop.is_set(),
            )
        except Exception:
            pass

    def _process(self, pkt) -> None:
        try:
            from scapy.all import IP, TCP, UDP
        except Exception:
            return
        if IP not in pkt:
            return
        ip = pkt[IP]
        vip = self._victim_ip
        if ip.src != vip and ip.dst != vip:
            return
        proto = 'TCP' if TCP in pkt else ('UDP' if UDP in pkt else str(ip.proto))
        if TCP in pkt:
            dport = int(pkt[TCP].dport)
            sport = int(pkt[TCP].sport)
        elif UDP in pkt:
            dport = int(pkt[UDP].dport)
            sport = int(pkt[UDP].sport)
        else:
            dport = sport = 0
        size = int(len(bytes(pkt)))
        outgoing = ip.src == vip
        peer = ip.dst if outgoing else ip.src
        port = dport if outgoing else sport
        key = (peer, int(port), proto)
        with self._lock:
            self._last_pkt_at = time()
            flow = self._flows[key]
            flow['proto'] = proto
            if outgoing:
                self._out_bytes += size
                self._out_packets += 1
                self._window_out += size
                flow['out_bytes'] += size
                flow['out_packets'] += 1
            else:
                self._in_bytes += size
                self._in_packets += 1
                self._window_in += size
                flow['in_bytes'] += size
                flow['in_packets'] += 1
        cb = self._callback
        if cb is not None:
            try:
                cb()
            except Exception:
                pass


def probe_lan_reachable(scanner, ip: str) -> Optional[bool]:
    """Cheap LAN liveness: ARP cache, then best-effort /32 arping. None if unknown."""
    ip = str(ip or '').strip()
    if not ip or scanner is None:
        return None
    try:
        hit = scanner.probe_ip_arp_cache_only(ip)
        if hit:
            return True
    except Exception:
        pass
    try:
        hit = scanner.probe_ip(ip)
        if hit:
            return True
        # probe_ip may have refreshed cache
        hit = scanner.probe_ip_arp_cache_only(ip)
        if hit:
            return True
    except Exception:
        return None
    return False
