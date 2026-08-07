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


def _fmt_session_bytes(n: int) -> str:
    n = int(n or 0)
    if n < 1024:
        return f'{n} B'
    if n < 1024 * 1024:
        return f'{n / 1024:.1f} KB'
    return f'{n / (1024 * 1024):.2f} MB'


def classify_kill_flow_verdict(
    *,
    kill_on: bool,
    lan_reachable: Optional[bool],
    mitm_armed: bool,
    ics_path: bool,
    out_bps: float,
    in_bps: float,
    saw_any_packets: bool,
    kill_pending: bool = False,
    out_bytes: int = 0,
    in_bytes: int = 0,
    session_had_kill: bool = False,
) -> KillFlowVerdict:
    """Differentiate full cut vs not-in-path vs leak (for Kill monitor UI)."""
    if not kill_on:
        # Keep last-session read after a short Kill instead of snapping back to Waiting.
        if session_had_kill and (saw_any_packets or out_bytes > 0 or in_bytes > 0):
            if in_bytes <= 0 and out_bytes > 0:
                return KillFlowVerdict(
                    code='ENDED_CUT',
                    label='Kill ended — looked like a full cut',
                    detail=(
                        f'Last session: {_fmt_session_bytes(out_bytes)} out, '
                        f'{_fmt_session_bytes(in_bytes)} in (attempts, no replies).'
                    ),
                    level='ok',
                )
            if in_bytes > 0 and in_bytes >= max(1500, out_bytes // 2):
                return KillFlowVerdict(
                    code='ENDED_LEAK',
                    label='Kill ended — had return traffic',
                    detail=(
                        f'Last session: {_fmt_session_bytes(out_bytes)} out, '
                        f'{_fmt_session_bytes(in_bytes)} in — possible leak while armed.'
                    ),
                    level='warn',
                )
            return KillFlowVerdict(
                code='ENDED',
                label='Kill ended',
                detail=(
                    f'Last session totals: {_fmt_session_bytes(out_bytes)} out, '
                    f'{_fmt_session_bytes(in_bytes)} in. Turn Kill ON again to watch live.'
                ),
                level='idle',
            )
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
        if kill_pending:
            return KillFlowVerdict(
                code='ARMING',
                label='Arming Kill…',
                detail='Kill clicked — waiting for MITM/hotspot backend to arm.',
                level='idle',
            )
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

    # Prefer lifetime totals during a short Kill (rates can already be 0 B/s).
    if (
        saw_any_packets
        and out_bytes > 0
        and in_bytes <= max(64, out_bytes // 20)
        and in_bps < _LEAK_IN_BPS * 0.35
    ):
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
        self._gen = 0

    def start(self, victim_ip: str, iface: str, on_update: Optional[Callable[[], None]] = None) -> None:
        # Never join on the caller thread (often the GUI) — that stalled Kill toggles.
        self.stop(join=False)
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
        self._gen += 1
        gen = self._gen

        def _target() -> None:
            try:
                self._run(gen)
            except Exception:
                pass

        self._thread = Thread(
            target=_target,
            name='zubcut-kill-flow-sniff',
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, join: bool = False) -> None:
        self._gen += 1
        self._stop.set()
        thread = self._thread
        self._thread = None
        if join and thread is not None and thread.is_alive():
            thread.join(timeout=0.2)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = monotonic()
            dt = max(0.25, now - self._window_t0)
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

    def _run(self, gen: int) -> None:
        try:
            from scapy.all import sniff
        except Exception:
            return
        bpf = f'host {self._victim_ip}'
        try:
            sniff(
                prn=lambda pkt: self._process(pkt, gen),
                filter=bpf,
                store=False,
                iface=self._iface,
                stop_filter=lambda _p: self._stop.is_set() or gen != self._gen,
            )
        except Exception:
            pass

    def _process(self, pkt, gen: int) -> None:
        if gen != self._gen or self._stop.is_set():
            return
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
            if gen != self._gen:
                return
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
        # Do not callback per-packet — GUI timer refreshes (avoids event-loop storms).


def probe_lan_reachable(scanner, ip: str) -> Optional[bool]:
    """ARP-cache-only liveness. Never arping/ping/merge — those fight Kill/MITM + selection."""
    ip = str(ip or '').strip()
    if not ip or scanner is None:
        return None
    try:
        # Prefer read-only lookup; fall back only if an older scanner lacks it.
        lookup = getattr(scanner, 'lookup_ip_in_arp_cache', None)
        if callable(lookup):
            return bool(lookup(ip))
        # Legacy scanner without read-only lookup — skip (merging probes fight selection).
        return None
    except Exception:
        return None
