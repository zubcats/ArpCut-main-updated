import heapq
import random
import threading
import time

from scapy.all import IP, Ether, AsyncSniffer, conf

from tools.crash_feedback import safe_daemon_target

# MITM user-space shaping limits (experimental).
# 800ms felt too mild for Advanced Lag; 5s matches meaningful game stall without
# unbounded queue growth (heap still capped below).
_MAX_DELAY_MS = 5000
_MAX_DELAY_QUEUE_PACKETS = 2000
# Upper bound for token-bucket rate (kbps); 10e6 kbps ≈ 10 Gbps.
_MAX_SHAPING_KBPS = 10_000_000.0


def _mac_key(value) -> str:
    return str(value or '').strip().lower().replace('-', ':')


class MitmForwarder:
    """
    Simple user-space forwarder that optionally drops traffic in one direction.
    It assumes ARP poisoning is already in place so frames arrive at our NIC.
    Uses persistent L2 socket to avoid Windows socket exhaustion.

    Optional experimental shaping (same MITM path as percent cut):
    - Per-direction fixed delay (queued send, milliseconds).
    - Per-direction token-bucket rate cap (Kbps); excess packets are dropped.
    """

    def __init__(self, debug=False):
        self.running = False
        self.sniffer = None
        self.victim = None
        self.router = None
        self.iface = None
        self.my_mac = None
        self.drop_from_victim = False
        self.drop_to_victim = False
        self.pass_from_victim_pct = 100
        self.pass_to_victim_pct = 100
        self.delay_ms_from_victim = 0
        self.delay_ms_to_victim = 0
        self.jitter_ms_from_victim = 0
        self.jitter_ms_to_victim = 0
        self.loss_pct_from_victim = 0
        self.loss_pct_to_victim = 0
        self.max_kbps_from_victim = 0.0
        self.max_kbps_to_victim = 0.0
        self._pkt_count = 0
        self._drop_count = 0
        self._fwd_count = 0
        self._debug = debug
        self._socket = None  # Persistent L2 socket
        self._byte_budget_from_victim = 0.0
        self._byte_budget_to_victim = 0.0
        self._send_lock = threading.Lock()
        self._delay_heap = []
        self._delay_lock = threading.Lock()
        self._delay_seq = 0
        self._delay_event = threading.Event()
        self._delay_thread = None
        self._bucket_last_out = None
        self._bucket_tokens_out = 0.0
        self._bucket_last_in = None
        self._bucket_tokens_in = 0.0

    def start(
        self,
        victim: dict,
        router: dict,
        iface_name: str,
        iface_mac: str,
        should_drop=None,  # unused; kept for call compatibility
        drop_from_victim: bool = False,
        drop_to_victim: bool = False,
        pass_from_victim_pct: int = 100,
        pass_to_victim_pct: int = 100,
        delay_ms_from_victim: int = 0,
        delay_ms_to_victim: int = 0,
        jitter_ms_from_victim: int = 0,
        jitter_ms_to_victim: int = 0,
        loss_pct_from_victim: int = 0,
        loss_pct_to_victim: int = 0,
        max_kbps_from_victim: float = 0.0,
        max_kbps_to_victim: float = 0.0,
        iface_alts: list[str] | None = None,
    ):
        """
        Start capturing traffic for victim/router and rewrite MACs before sending.
        """
        self.stop()
        self.victim = victim
        self.router = router
        iface_candidates: list[str] = []
        for raw in [iface_name, *(iface_alts or [])]:
            s = str(raw or '').strip()
            if s and s != 'NULL' and s not in iface_candidates:
                iface_candidates.append(s)
        self.iface = iface_candidates[0] if iface_candidates else iface_name
        self.my_mac = iface_mac
        self.drop_from_victim = drop_from_victim
        self.drop_to_victim = drop_to_victim
        self.pass_from_victim_pct = max(0, min(100, int(pass_from_victim_pct)))
        self.pass_to_victim_pct = max(0, min(100, int(pass_to_victim_pct)))
        self.delay_ms_from_victim = max(0, min(_MAX_DELAY_MS, int(delay_ms_from_victim)))
        self.delay_ms_to_victim = max(0, min(_MAX_DELAY_MS, int(delay_ms_to_victim)))
        self.jitter_ms_from_victim = max(0, min(_MAX_DELAY_MS, int(jitter_ms_from_victim)))
        self.jitter_ms_to_victim = max(0, min(_MAX_DELAY_MS, int(jitter_ms_to_victim)))
        self.loss_pct_from_victim = max(0, min(100, int(loss_pct_from_victim)))
        self.loss_pct_to_victim = max(0, min(100, int(loss_pct_to_victim)))
        self.max_kbps_from_victim = max(0.0, min(_MAX_SHAPING_KBPS, float(max_kbps_from_victim)))
        self.max_kbps_to_victim = max(0.0, min(_MAX_SHAPING_KBPS, float(max_kbps_to_victim)))
        self._byte_budget_from_victim = 0.0
        self._byte_budget_to_victim = 0.0
        self._bucket_last_out = None
        self._bucket_tokens_out = 0.0
        self._bucket_last_in = None
        self._bucket_tokens_in = 0.0
        self._delay_seq = 0
        self.running = True

        if not (self.victim.get('ip') and self.victim.get('mac')):
            print('[forwarder] victim information incomplete; not starting')
            self.running = False
            return
        if not (self.router.get('ip') and self.router.get('mac')):
            print('[forwarder] router information incomplete; not starting')
            self.running = False
            return

        # Create persistent L2 socket (try alternate Npcap tokens on Realtek/Wi‑Fi).
        self._socket = None
        for cand in iface_candidates:
            try:
                self._socket = conf.L2socket(iface=cand)
                self.iface = cand
                if self._debug:
                    print(f"[forwarder] L2 socket created for {cand}")
                break
            except Exception as e:
                if self._debug:
                    print(f"[forwarder] Failed to create L2 socket on {cand}: {e}")
                self._socket = None

        bpf = f"ip and host {self.victim['ip']}"
        if self._debug:
            print(f"[forwarder] Starting on {self.iface} (candidates={iface_candidates})")
            print(f"[forwarder] victim={self.victim['ip']}/{self.victim['mac']}")
            print(f"[forwarder] router={self.router['ip']}/{self.router['mac']}")
            print(
                "[forwarder] drop_from_victim=%s, drop_to_victim=%s"
                % (self.drop_from_victim, self.drop_to_victim)
            )
            print(
                "[forwarder] pass_from_victim_pct=%s, pass_to_victim_pct=%s"
                % (self.pass_from_victim_pct, self.pass_to_victim_pct)
            )
            print(
                "[forwarder] delay_ms out/in=%s/%s jitter out/in=%s/%s loss%% out/in=%s/%s max_kbps out/in=%s/%s"
                % (
                    self.delay_ms_from_victim,
                    self.delay_ms_to_victim,
                    self.jitter_ms_from_victim,
                    self.jitter_ms_to_victim,
                    self.loss_pct_from_victim,
                    self.loss_pct_to_victim,
                    self.max_kbps_from_victim,
                    self.max_kbps_to_victim,
                )
            )
        self.sniffer = None
        sniffer_err = None
        for cand in iface_candidates:
            try:
                self.sniffer = AsyncSniffer(
                    iface=cand,
                    filter=bpf,
                    prn=self._process_packet,
                    store=False,
                    promisc=True,
                )
                self.sniffer.start()
                self.iface = cand
                if self._debug:
                    print(f"[forwarder] Sniffer started successfully on {cand}")
                break
            except Exception as e:
                sniffer_err = e
                if self._debug:
                    print(f"[forwarder] Sniffer failed on {cand}: {e}")
                self.sniffer = None
        if self.sniffer is None:
            if self._debug and sniffer_err is not None:
                print(f"[forwarder] Sniffer failed on all candidates: {sniffer_err}")
            self.running = False
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None
            return

        need_delay = (
            (self.delay_ms_from_victim + self.jitter_ms_from_victim) > 0
            or (self.delay_ms_to_victim + self.jitter_ms_to_victim) > 0
        )
        if need_delay:
            self._delay_event.clear()
            self._delay_thread = threading.Thread(
                target=safe_daemon_target(self._delay_worker), daemon=True
            )
            self._delay_thread.start()

    def pass_all_live(self) -> None:
        """Resume full forwarding without stopping the sniffer (instant Percent Cut OFF)."""
        self.drop_from_victim = False
        self.drop_to_victim = False
        self.pass_from_victim_pct = 100
        self.pass_to_victim_pct = 100
        self.loss_pct_from_victim = 0
        self.loss_pct_to_victim = 0
        self.delay_ms_from_victim = 0
        self.delay_ms_to_victim = 0
        self.jitter_ms_from_victim = 0
        self.jitter_ms_to_victim = 0
        self.max_kbps_from_victim = 0.0
        self.max_kbps_to_victim = 0.0
        self._delay_event.set()
        with self._delay_lock:
            self._delay_heap.clear()

    def stop(self):
        self.running = False
        self._delay_event.set()
        with self._delay_lock:
            self._delay_heap.clear()
        sniffer = self.sniffer
        self.sniffer = None
        sock = self._socket
        self._socket = None
        # AsyncSniffer.stop() and L2socket.close() can hang on Npcap while recv
        # is in flight — never run either on the GUI/OFF click thread.
        def _stop_sniff():
            try:
                if sniffer is not None:
                    sniffer.stop()
            except Exception:
                pass
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

        try:
            threading.Thread(
                target=safe_daemon_target(_stop_sniff), daemon=True
            ).start()
        except Exception:
            _stop_sniff()
        thr = getattr(self, '_delay_thread', None)
        if thr is not None and thr.is_alive():
            try:
                thr.join(timeout=0.05)
            except Exception:
                pass
        self._delay_thread = None

    def get_stats(self):
        """Return current packet statistics"""
        return {
            'running': self.running,
            'packets_seen': self._pkt_count,
            'packets_dropped': self._drop_count,
            'packets_forwarded': self._fwd_count,
            'drop_from_victim': self.drop_from_victim,
            'drop_to_victim': self.drop_to_victim,
            'pass_from_victim_pct': self.pass_from_victim_pct,
            'pass_to_victim_pct': self.pass_to_victim_pct,
            'delay_ms_from_victim': self.delay_ms_from_victim,
            'delay_ms_to_victim': self.delay_ms_to_victim,
            'jitter_ms_from_victim': self.jitter_ms_from_victim,
            'jitter_ms_to_victim': self.jitter_ms_to_victim,
            'loss_pct_from_victim': self.loss_pct_from_victim,
            'loss_pct_to_victim': self.loss_pct_to_victim,
            'max_kbps_from_victim': self.max_kbps_from_victim,
            'max_kbps_to_victim': self.max_kbps_to_victim,
        }

    def _delay_worker(self):
        while self.running:
            with self._delay_lock:
                empty = len(self._delay_heap) == 0
            if empty:
                self._delay_event.wait(timeout=0.25)
            if not self.running:
                break
            now = time.monotonic()
            while self.running:
                raw = None
                with self._delay_lock:
                    if not self._delay_heap or self._delay_heap[0][0] > now:
                        break
                    _, __, raw = heapq.heappop(self._delay_heap)
                if raw is not None:
                    self._send_raw(raw)
                    self._fwd_count += 1
                now = time.monotonic()

    def _enqueue_delayed(self, raw: bytes, delay_ms: int) -> bool:
        delay_ms = max(0, min(_MAX_DELAY_MS, int(delay_ms)))
        if delay_ms <= 0:
            return False
        rel = time.monotonic() + delay_ms / 1000.0
        with self._delay_lock:
            if len(self._delay_heap) >= _MAX_DELAY_QUEUE_PACKETS:
                return False
            self._delay_seq += 1
            heapq.heappush(self._delay_heap, (rel, self._delay_seq, raw))
        self._delay_event.set()
        return True

    def _token_bucket_peek(self, direction: str, nbytes: int, now: float) -> bool:
        """True if cap allows this packet (does not deduct tokens)."""
        if direction == 'out':
            max_kbps = self.max_kbps_from_victim
            last_attr = '_bucket_last_out'
            tok_attr = '_bucket_tokens_out'
        else:
            max_kbps = self.max_kbps_to_victim
            last_attr = '_bucket_last_in'
            tok_attr = '_bucket_tokens_in'
        if max_kbps <= 0:
            return True
        rate = max_kbps * 1000.0 / 8.0
        burst_max = max(rate * 0.12, float(nbytes))
        last = getattr(self, last_attr)
        tokens = getattr(self, tok_attr)
        if last is None:
            tokens = min(burst_max, rate * 0.05 + float(nbytes))
            setattr(self, last_attr, now)
            setattr(self, tok_attr, tokens)
        else:
            dt = max(0.0, now - last)
            tokens = min(burst_max, tokens + dt * rate)
            setattr(self, last_attr, now)
            setattr(self, tok_attr, tokens)
        return tokens >= nbytes

    def _token_bucket_commit(self, direction: str, nbytes: int) -> bool:
        """Deduct tokens after a forward decision (call only if peek was True)."""
        if direction == 'out':
            max_kbps = self.max_kbps_from_victim
            tok_attr = '_bucket_tokens_out'
        else:
            max_kbps = self.max_kbps_to_victim
            tok_attr = '_bucket_tokens_in'
        if max_kbps <= 0:
            return True
        tokens = getattr(self, tok_attr)
        if tokens >= nbytes:
            setattr(self, tok_attr, tokens - nbytes)
            return True
        return False

    def _token_bucket_allow(self, direction: str, nbytes: int, now: float) -> bool:
        """Peek + commit (legacy helper)."""
        if not self._token_bucket_peek(direction, nbytes, now):
            return False
        return self._token_bucket_commit(direction, nbytes)

    def _should_drop_shaped_packet(
        self,
        loss_pct: int,
        direction: str,
        nbytes: int,
        now: float,
    ) -> bool:
        """Loss and cap drops: one compounded survival roll."""
        from tools.mitm_compound_loss import CAP_OVERFLOW_LOSS_PCT, should_drop_compounded

        cap_active = (
            self.max_kbps_from_victim > 0 if direction == 'out' else self.max_kbps_to_victim > 0
        )
        cap_ok = self._token_bucket_peek(direction, nbytes, now)
        return should_drop_compounded(
            loss_pct,
            cap_active=cap_active,
            cap_can_forward=cap_ok,
            overflow_loss_pct=CAP_OVERFLOW_LOSS_PCT,
        )

    @staticmethod
    def _queued_delay_ms(base: int, jitter_max: int) -> int:
        b = max(0, min(_MAX_DELAY_MS, int(base)))
        j = max(0, min(_MAX_DELAY_MS, int(jitter_max)))
        extra = random.randint(0, j) if j > 0 else 0
        return min(_MAX_DELAY_MS, b + extra)

    def _passes_ratio(self, pass_pct: int, direction: str, pkt_size: int) -> bool:
        """Per-packet stochastic pass (smoother than byte-budget bursts that feel like full cut)."""
        del direction, pkt_size
        pct = max(0, min(100, int(pass_pct)))
        if pct <= 0:
            return False
        if pct >= 100:
            return True
        return random.randint(1, 100) <= pct

    def _l2_addressed_to_us(self, pkt) -> bool:
        """Only leftover MITM (frames sent to this PC) should be rewritten.

        Promiscuous Npcap also sees native victim↔router copies and our own
        reinjects. Rewriting those duplicates the real path and leaves lag
        after Kill/Dupe OFF without a full red chain.
        """
        mine = _mac_key(self.my_mac)
        if not mine:
            return True
        src = _mac_key(pkt[Ether].src)
        dst = _mac_key(pkt[Ether].dst)
        if src == mine:
            return False
        return dst == mine

    def _process_packet(self, pkt):
        if not self.running or not pkt.haslayer(IP) or not pkt.haslayer(Ether):
            return
        if not self._l2_addressed_to_us(pkt):
            return

        ip_layer = pkt[IP]
        src = ip_layer.src
        dst = ip_layer.dst
        self._pkt_count += 1

        # Debug first few packets
        if self._debug and self._pkt_count <= 5:
            print(f"[forwarder] pkt#{self._pkt_count}: {src} -> {dst}")

        now = time.monotonic()

        # Outbound: victim -> router/internet
        if src == self.victim['ip']:
            if self.drop_from_victim:
                self._drop_count += 1
                if self._debug and self._drop_count <= 3:
                    print(f"[forwarder] DROPPING outbound: {src} -> {dst}")
                return
            sz = self._packet_size_bytes(pkt)
            if not self._passes_ratio(self.pass_from_victim_pct, 'out', sz):
                self._drop_count += 1
                return
            if self._should_drop_shaped_packet(self.loss_pct_from_victim, 'out', sz, now):
                self._drop_count += 1
                return
            if self.max_kbps_from_victim > 0 and not self._token_bucket_commit('out', sz):
                self._drop_count += 1
                return
            pkt[Ether].src = self.my_mac
            pkt[Ether].dst = self.router['mac']
            self._fix_checksums(pkt)
            dms = self._queued_delay_ms(self.delay_ms_from_victim, self.jitter_ms_from_victim)
            if dms > 0:
                raw = bytes(pkt)
                if self._enqueue_delayed(raw, dms):
                    return
                self._drop_count += 1
                return
            self._send(pkt)
            self._fwd_count += 1

        # Inbound: router -> victim
        elif dst == self.victim['ip']:
            if self.drop_to_victim:
                self._drop_count += 1
                if self._debug and self._drop_count <= 3:
                    print(f"[forwarder] DROPPING inbound: {src} -> {dst}")
                return
            sz = self._packet_size_bytes(pkt)
            if not self._passes_ratio(self.pass_to_victim_pct, 'in', sz):
                self._drop_count += 1
                return
            if self._should_drop_shaped_packet(self.loss_pct_to_victim, 'in', sz, now):
                self._drop_count += 1
                return
            if self.max_kbps_to_victim > 0 and not self._token_bucket_commit('in', sz):
                self._drop_count += 1
                return
            pkt[Ether].src = self.my_mac
            pkt[Ether].dst = self.victim['mac']
            self._fix_checksums(pkt)
            dms = self._queued_delay_ms(self.delay_ms_to_victim, self.jitter_ms_to_victim)
            if dms > 0:
                raw = bytes(pkt)
                if self._enqueue_delayed(raw, dms):
                    return
                self._drop_count += 1
                return
            self._send(pkt)
            self._fwd_count += 1

        # Periodic stats
        if self._debug and self._pkt_count % 100 == 0:
            print(f"[forwarder] stats: {self._pkt_count} seen, {self._drop_count} dropped, {self._fwd_count} fwd")

    def _note_send_error(self, exc: BaseException) -> None:
        """Rate-limited durable log for silent L2 send failures (compat debugging)."""
        try:
            import time as _time

            now = _time.monotonic()
            last = float(getattr(self, '_last_send_err_log', 0.0) or 0.0)
            if now - last < 2.0:
                return
            self._last_send_err_log = now
            from tools.zubcut_log import app_log

            app_log(
                'forwarder_send_failed',
                iface=str(getattr(self, 'iface', '') or ''),
                error=repr(exc),
            )
        except Exception:
            pass

    def _send(self, pkt):
        """Send using persistent socket, prevents Windows socket exhaustion"""
        with self._send_lock:
            try:
                if self._socket:
                    self._socket.send(pkt)
                else:
                    from scapy.all import sendp
                    sendp(pkt, iface=self.iface, verbose=0)
            except Exception as exc:
                self._note_send_error(exc)

    def _send_raw(self, raw: bytes):
        with self._send_lock:
            try:
                pkt = Ether(raw)
                if self._socket:
                    self._socket.send(pkt)
                else:
                    from scapy.all import sendp
                    sendp(pkt, iface=self.iface, verbose=0)
            except Exception as exc:
                self._note_send_error(exc)

    @staticmethod
    def _fix_checksums(pkt):
        # Force recalculation to avoid checksum issues after modifications
        try:
            if IP in pkt and hasattr(pkt[IP], 'chksum'):
                del pkt[IP].chksum
            if IP in pkt and hasattr(pkt[IP], 'len'):
                del pkt[IP].len
            if pkt.haslayer('TCP') and hasattr(pkt['TCP'], 'chksum'):
                del pkt['TCP'].chksum
            if pkt.haslayer('UDP') and hasattr(pkt['UDP'], 'chksum'):
                del pkt['UDP'].chksum
        except Exception:
            pass

    @staticmethod
    def _packet_size_bytes(pkt) -> int:
        """Best-effort packet size for byte-aware pass-through gating."""
        try:
            return len(bytes(pkt))
        except Exception:
            try:
                return len(pkt)
            except Exception:
                return 1
