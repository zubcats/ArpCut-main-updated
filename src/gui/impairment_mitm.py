"""MITM shaping / LAN MITM helpers (extracted from MainWindow)."""
from __future__ import annotations

import sys
import threading
import time

from PyQt5.QtCore import QElapsedTimer, QEventLoop, QTimer

from tools.clumsy_inline import (
    clumsy_ics_resolve_victim_ip,
    clumsy_windivert_unavailable_reason,
    use_windivert_for_advanced_ics_shaping,
)
from tools.crash_feedback import safe_daemon_target
from tools.pfctl import _is_valid_ip, unblock_ip
from tools.utils_gui import get_settings
from gui.impairment_shared import (
    UI_LOG_RESTORE_FG,
    UI_LOG_VICTIM_BLOCK_FG,
    _bg_block_ip,
)


class ImpairmentMitmMixin:
    def _ensure_readiness_state(self) -> None:
        """Lazy-init readiness caches (PC + first-select-per-scan device path)."""
        if getattr(self, '_readiness_state_ready', False):
            return
        self._readiness_scan_gen = int(getattr(self, '_readiness_scan_gen', 0) or 0)
        self._readiness_device_checked: set[str] = set(
            getattr(self, '_readiness_device_checked', None) or ()
        )
        self._readiness_pc_started = bool(getattr(self, '_readiness_pc_started', False))
        self._readiness_pc_enriched = bool(getattr(self, '_readiness_pc_enriched', False))
        self._readiness_pc_in_flight = bool(getattr(self, '_readiness_pc_in_flight', False))
        self._readiness_pc_enrich_pending = bool(
            getattr(self, '_readiness_pc_enrich_pending', False)
        )
        self._readiness_pc_findings = list(getattr(self, '_readiness_pc_findings', None) or [])
        self._readiness_pc_lines_shown = set(
            getattr(self, '_readiness_pc_lines_shown', None) or ()
        )
        self._readiness_state_ready = True

    def _invalidate_device_readiness(self, *, reason: str = 'scan') -> None:
        """New scan generation — device path checks run again on next first click per IP."""
        self._ensure_readiness_state()
        self._readiness_scan_gen = int(self._readiness_scan_gen) + 1
        self._readiness_device_checked.clear()
        try:
            from tools.zubcut_log import app_log

            app_log('readiness_device_cache_cleared', reason=str(reason), gen=self._readiness_scan_gen)
        except Exception:
            pass

    def _schedule_pc_readiness_check(
        self, *, reason: str = 'startup', force: bool = False
    ) -> None:
        """Background PC readiness (Npcap/WinPcap/WinDivert/GW/Wi‑Fi). Never on Kill.

        ``force=True`` allows one enrichment pass after the first completed run
        (LAN warm / post-scan with router MAC). If warm wins the race and is the
        first run, it does not burn the enrich slot.
        """
        if not sys.platform.startswith('win'):
            return
        self._ensure_readiness_state()
        if getattr(self, '_readiness_pc_in_flight', False):
            # Startup check still running — queue one enrich after it lands.
            if force and not bool(getattr(self, '_readiness_pc_enriched', False)):
                self._readiness_pc_enrich_pending = True
            return
        if self._readiness_pc_started and not force:
            return
        if force and self._readiness_pc_started:
            if bool(getattr(self, '_readiness_pc_enriched', False)):
                return
            self._readiness_pc_enriched = True
            self._readiness_pc_enrich_pending = False
        # force + not started => first pass (do not mark enriched)
        was_enrich = bool(force and self._readiness_pc_started)
        self._readiness_pc_started = True
        self._readiness_pc_in_flight = True

        is_admin = bool(getattr(self, '_admin_elevated', False))
        iface = getattr(getattr(self, 'scanner', None), 'iface', None)
        iface_name = str(getattr(iface, 'name', None) or '')
        iface_guid = str(getattr(iface, 'guid', None) or '')
        iface_ip = str(getattr(iface, 'ip', None) or '')
        router = (
            getattr(getattr(self, 'killer', None), 'router', None)
            or getattr(getattr(self, 'scanner', None), 'router', None)
            or {}
        )
        router_ip = str((router or {}).get('ip') or '')
        router_mac = str((router or {}).get('mac') or '')
        wifi_hints = list(getattr(self, '_wifi_link_hints_cached', None) or [])

        def _work() -> None:
            findings = []
            try:
                try:
                    from tools.readiness import collect_pc_readiness

                    findings = collect_pc_readiness(
                        is_admin=is_admin,
                        iface_name=iface_name,
                        iface_guid=iface_guid,
                        iface_ip=iface_ip,
                        router_ip=router_ip,
                        router_mac=router_mac,
                        wifi_link_hints=wifi_hints,
                        # Probe Wi‑Fi in-thread when cache is empty (open-time signal).
                        probe_wifi=not bool(wifi_hints),
                    )
                except Exception as exc:
                    try:
                        from tools.zubcut_log import app_log

                        app_log(
                            'pc_readiness_failed',
                            error=repr(exc),
                            reason=str(reason),
                            exc_info=True,
                        )
                    except Exception:
                        pass
                    findings = []
                # Keep Wi‑Fi hints for device-path readiness / Kill arm messages.
                try:
                    if not wifi_hints:
                        probed = [
                            str(f.code)
                            for f in findings
                            if getattr(f, 'code', '') in ('ZC-WPA3', 'ZC-MLO', 'ZC-ISOLATION')
                        ]
                        self._wifi_link_hints_cached = probed
                except Exception:
                    pass
                self._readiness_pc_findings = list(findings)
                # Queued to GUI thread — never apply Ready lines from the worker.
                try:
                    sig = getattr(self, 'readiness_pc_done', None)
                    if sig is not None:
                        sig.emit(list(findings), str(reason))
                except Exception:
                    pass
            finally:
                self._readiness_pc_in_flight = False

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-pc-readiness',
                daemon=True,
            ).start()
        except Exception:
            self._readiness_pc_started = False
            self._readiness_pc_in_flight = False
            if was_enrich:
                self._readiness_pc_enriched = False

    def _schedule_device_readiness_check(self, device: dict) -> None:
        """First user select of this IP since last scan — path check once. Not on Kill.

        Runs on the GUI thread: device-path checks are cheap (no ping/scapy). A prior
        version scheduled QTimer from a worker thread, which often never painted the
        status strip — and the IP stayed marked checked, so re-clicks looked dead.

        Programmatic restore after scan must not consume this slot: ARP/fast scan
        re-selects the same row immediately, which used to burn the check before
        the user clicked.
        """
        if getattr(self, '_readiness_suppress_device_select', False):
            return
        if not isinstance(device, dict) or device.get('admin'):
            return
        self._ensure_readiness_state()
        victim_ip = str(device.get('ip') or '').strip()
        if not victim_ip:
            return
        key = victim_ip.lower()
        if key in self._readiness_device_checked:
            return
        # Mark immediately so itemClicked / restore-select cannot double-fire.
        self._readiness_device_checked.add(key)

        iface = getattr(getattr(self, 'scanner', None), 'iface', None)
        iface_ip = str(getattr(iface, 'ip', None) or '')
        router = (
            getattr(getattr(self, 'killer', None), 'router', None)
            or getattr(getattr(self, 'scanner', None), 'router', None)
            or {}
        )
        router_ip = str((router or {}).get('ip') or '')
        router_mac = str((router or {}).get('mac') or '')
        wifi_hints = list(getattr(self, '_wifi_link_hints_cached', None) or [])
        lan_ipv6 = getattr(self, '_lan_ipv6_enabled_cached', None)
        device_snap = {
            'ip': victim_ip,
            'mac': str(device.get('mac') or ''),
            'name': str(device.get('name') or ''),
            'vendor': str(device.get('vendor') or ''),
            'admin': bool(device.get('admin')),
        }

        try:
            from tools.readiness import collect_device_path_readiness
            from tools.zubcut_log import app_log

            app_log('device_readiness_start', ip=victim_ip)
            findings = collect_device_path_readiness(
                device_snap,
                iface_ip=iface_ip,
                router_ip=router_ip,
                router_mac=router_mac,
                wifi_link_hints=wifi_hints,
                lan_ipv6_enabled=lan_ipv6 if isinstance(lan_ipv6, bool) else None,
            )
            self._apply_readiness_findings(findings, scope='device', reason=victim_ip)
        except Exception as exc:
            try:
                self._readiness_device_checked.discard(key)
            except Exception:
                pass
            try:
                from tools.zubcut_log import app_log

                app_log(
                    'device_readiness_failed',
                    error=repr(exc),
                    ip=victim_ip,
                    exc_info=True,
                )
            except Exception:
                pass

    def _deliver_pc_readiness_findings(self, findings, reason: str = '') -> None:
        """GUI-thread slot for PC readiness (queued from background worker)."""
        rows = list(findings or [])
        reason_s = str(reason or '')
        # Follow-up passes: only surface new lines (ZC-ROUTE is reused for different issues).
        if reason_s in ('lan_warm', 'post_scan'):
            shown = set(getattr(self, '_readiness_pc_lines_shown', None) or ())
            fresh = []
            for f in rows:
                try:
                    line = f.format_line() if hasattr(f, 'format_line') else str(f)
                except Exception:
                    line = str(getattr(f, 'message', '') or f)
                if line and line not in shown:
                    fresh.append(f)
            rows = fresh
        self._apply_readiness_findings(rows, scope='pc', reason=reason_s)
        try:
            shown = set(getattr(self, '_readiness_pc_lines_shown', None) or ())
            for f in findings or []:
                try:
                    line = f.format_line() if hasattr(f, 'format_line') else str(f)
                except Exception:
                    line = str(getattr(f, 'message', '') or '')
                if line:
                    shown.add(line)
            self._readiness_pc_lines_shown = shown
        except Exception:
            pass
        # If warm/post-scan asked to enrich while the first pass was still in flight.
        try:
            if getattr(self, '_readiness_pc_enrich_pending', False) and not getattr(
                self, '_readiness_pc_enriched', False
            ):
                self._readiness_pc_enrich_pending = False
                self._schedule_pc_readiness_check(reason='lan_warm', force=True)
        except Exception:
            pass

    def _apply_readiness_findings(
        self, findings, *, scope: str = 'pc', reason: str = ''
    ) -> None:
        """Surface warn/fail on status strip; OK device path once; never auto-Clumsy."""
        try:
            from tools.readiness import ReadinessFinding, worst_level
            from tools.zubcut_log import app_log
        except Exception:
            return
        rows = [f for f in (findings or []) if isinstance(f, ReadinessFinding)]
        if not rows:
            return
        try:
            app_log(
                'readiness_result',
                scope=str(scope),
                reason=str(reason),
                worst=worst_level(rows),
                findings=[f.format_line() for f in rows],
            )
        except Exception:
            pass

        problems = [f for f in rows if f.level in ('warn', 'fail')]
        if problems:
            # Worst first; keep UI to a few lines so we don't flood.
            order = {'fail': 0, 'warn': 1, 'ok': 2}
            problems.sort(key=lambda f: order.get(f.level, 9))
            for f in problems[:4]:
                color = 'red' if f.level == 'fail' else 'orange'
                try:
                    self.log(f'Ready: {f.format_line()}', color)
                except Exception:
                    pass
            return

        if scope == 'device':
            ok = next((f for f in rows if f.level == 'ok'), None)
            if ok is not None:
                try:
                    self.log(f'Ready: {ok.format_line()}', UI_LOG_RESTORE_FG)
                except Exception:
                    pass

    def _lan_mitm_stack_is_warm(self) -> bool:
        """True when home-LAN router/iface context was refreshed recently."""
        warmed_at = float(getattr(self, '_lan_impairment_warmed_at', 0.0))
        if warmed_at <= 0.0 or time.monotonic() - warmed_at > 300.0:
            return False
        iface = getattr(self.scanner, 'iface', None)
        if iface is None or getattr(iface, 'name', None) in (None, '', 'NULL'):
            return False
        router = getattr(self.scanner, 'router', None) or getattr(self.killer, 'router', None)
        return isinstance(router, dict) and bool(str(router.get('ip') or '').strip())


    def _warm_lan_mitm_stack(self) -> None:
        """Refresh LAN MITM context once per session (router MAC, iface bind)."""
        try:
            iface = getattr(self.scanner, 'iface', None)
            if iface is not None and getattr(iface, 'name', None) not in (None, '', 'NULL'):
                self.killer.iface = iface
            # GUI-thread warm (QTimer) — skip getmacbyip; router MAC refreshed below.
            self.scanner.refresh_local_topology(allow_scapy_probe=False)
            self.killer.router = getattr(self.scanner, 'router', None) or self.killer.router
            refresh_router = getattr(self.killer, '_refresh_router_mac_for_mitm', None)
            if callable(refresh_router):
                refresh_router()
            self._lan_impairment_warmed_at = time.monotonic()
            self._schedule_npcap_prewarm('lan_warm')
            # Seal kernel forwarding during warm-up (non-blocking) so Kill's first
            # click does not race a multi-second per-iface netsh drain.
            # Skip when Clumsy/ICS is on — hotspot path may need forwarding enabled.
            if sys.platform.startswith('win'):
                try:
                    from tools.clumsy_inline import ics_forwarding_must_stay_on

                    if not ics_forwarding_must_stay_on():
                        from networking.killer import disable_ip_forwarding

                        disable_ip_forwarding(
                            priority_iface=str(
                                getattr(self.scanner.iface, 'name', None) or ''
                            )
                        )
                except Exception:
                    pass
                self._schedule_lan_ipv6_probe()
                self._schedule_wifi_link_probe()
                self._warn_vpn_iface_if_selected()
                self._warn_controlled_folder_access_once()
                # Enrich after router MAC / topology warm (one force pass).
                self._schedule_pc_readiness_check(reason='lan_warm', force=True)
        except Exception as exc:
            try:
                from tools.zubcut_log import app_log

                app_log('lan_mitm_warm_failed', error=repr(exc), exc_info=True)
            except Exception:
                pass

    def _warn_vpn_iface_if_selected(self) -> None:
        """Surface VPN/TAP/Wintun selection once — these break ARP MITM for many users."""
        try:
            if getattr(self, '_vpn_iface_warned', False):
                return
            name = str(getattr(self.scanner.iface, 'name', None) or '').lower()
            guid = str(getattr(self.scanner.iface, 'guid', None) or '').lower()
            blob = f'{name} {guid}'
            needles = (
                'vpn', 'wintun', 'wireguard', 'tap-windows', 'tap0901', 'tap adapter',
                'nordlynx', 'proton', 'mullvad', 'openvpn', 'fortinet',
                'anyconnect', 'globalprotect', 'hyper-v', 'vethernet',
                'default switch', 'vmware', 'virtualbox', 'vboxnet',
                'tailscale', 'zerotier', 'hamachi', 'wsl', 'docker',
            )
            if not any(n in blob for n in needles):
                return
            self._vpn_iface_warned = True
            self.log(
                'Selected adapter looks like VPN/virtual — LAN Kill usually fails. '
                'Pick your real Wi‑Fi/Ethernet in Settings.',
                'orange',
            )
        except Exception:
            pass

    def _warn_controlled_folder_access_once(self) -> None:
        """Soft warn once when Windows CFA may block Npcap/WinDivert drivers."""
        if getattr(self, '_cfa_warned', False):
            return
        if not sys.platform.startswith('win'):
            return

        def _work() -> None:
            enabled = False
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r'SOFTWARE\Microsoft\Windows Defender\Windows Defender Exploit Guard'
                    r'\Controlled Folder Access',
                )
                try:
                    val, _ = winreg.QueryValueEx(key, 'EnableControlledFolderAccess')
                    enabled = int(val or 0) != 0
                finally:
                    winreg.CloseKey(key)
            except Exception:
                enabled = False
            if not enabled:
                return
            self._cfa_warned = True

            def _ui() -> None:
                try:
                    from tools.user_errors import format_error_code

                    self.log(format_error_code('ZC-AV'), 'orange')
                except Exception:
                    self.log(
                        'Controlled Folder Access may block Npcap/WinDivert — allow ZubCut.',
                        'orange',
                    )

            try:
                QTimer.singleShot(0, _ui)
            except Exception:
                pass

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-cfa-probe',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _schedule_lan_ipv6_probe(self) -> None:
        """Cache whether the LAN NIC has IPv6 enabled (background; never on Kill click)."""
        if getattr(self, '_lan_ipv6_probe_in_flight', False):
            return
        self._lan_ipv6_probe_in_flight = True

        def _work() -> None:
            enabled = None
            try:
                name = str(getattr(self.scanner.iface, 'name', None) or '').strip()
                if not name or name == 'NULL':
                    return
                from tools.utils import run_command

                safe = name.replace("'", '')
                proc = run_command(
                    [
                        'powershell',
                        '-NoProfile',
                        '-Command',
                        f"(Get-NetAdapterBinding -Name '{safe}' "
                        f"-ComponentID ms_tcpip6 -ErrorAction SilentlyContinue).Enabled",
                    ],
                    shell=False,
                    timeout=4,
                )
                text = str(getattr(proc, 'stdout', None) or '').strip().lower()
                enabled = text.startswith('true')
            except Exception:
                enabled = None
            finally:
                self._lan_ipv6_probe_in_flight = False
            if enabled is not None:
                self._lan_ipv6_enabled_cached = bool(enabled)

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-lan-ipv6-probe',
                daemon=True,
            ).start()
        except Exception:
            self._lan_ipv6_probe_in_flight = False

    def _schedule_wifi_link_probe(self) -> None:
        """Cache WPA3 / Wi‑Fi 7 MLO hints from netsh (background; never on Kill click)."""
        if not sys.platform.startswith('win'):
            return
        if getattr(self, '_wifi_link_probe_in_flight', False):
            return
        self._wifi_link_probe_in_flight = True

        def _work() -> None:
            hints: list[str] = []
            try:
                from tools.utils import run_command
                from tools.support_wifi_link_diag import (
                    parse_wlan_interfaces,
                    security_zubcut_class,
                )

                proc = run_command(
                    ['netsh', 'wlan', 'show', 'interfaces'],
                    shell=False,
                    timeout=5,
                )
                raw = str(getattr(proc, 'stdout', None) or '')
                adapters = parse_wlan_interfaces(raw)
                for a in adapters:
                    if not bool(a.get('connected')):
                        continue
                    auth = str(a.get('authentication') or '')
                    sec = security_zubcut_class(auth)
                    if sec == 'wpa3':
                        hints.append('ZC-WPA3')
                    radio = str(a.get('radio_type') or '').lower()
                    band = str(a.get('band') or '').lower()
                    if (
                        '802.11be' in radio
                        or 'wi-fi 7' in radio
                        or 'wifi 7' in radio
                        or 'mlo' in radio
                        or 'multi-link' in radio
                        or ('6' in band and 'ghz' in band)
                    ):
                        hints.append('ZC-MLO')
            except Exception:
                hints = []
            finally:
                self._wifi_link_probe_in_flight = False
            # Dedupe while preserving order.
            seen: set[str] = set()
            ordered: list[str] = []
            for h in hints:
                if h not in seen:
                    seen.add(h)
                    ordered.append(h)
            self._wifi_link_hints_cached = ordered

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-wifi-link-probe',
                daemon=True,
            ).start()
        except Exception:
            self._wifi_link_probe_in_flight = False

    def _log_mitm_arm_status(self, device, *, action: str = 'Kill') -> None:
        """Surface silent MITM failures (stale MAC / bad router) in the log box."""
        try:
            from tools.utils import mac_address_is_usable

            if not isinstance(device, dict):
                return
            iface = getattr(self.scanner.iface, 'name', None) or '?'
            victim_mac = str(device.get('mac') or '')
            router_mac = str(
                (getattr(self.killer, 'router', None) or {}).get('mac')
                or getattr(self.scanner, 'router_mac', '')
                or ''
            )
            if not mac_address_is_usable(victim_mac):
                self.log(
                    f'{action} ON: victim MAC unknown for {device.get("ip")} — '
                    'ping the PS5 once, then rescan.',
                    'red',
                )
                return
            if not mac_address_is_usable(router_mac):
                self.log(
                    f'{action} ON: router MAC unknown on {iface} — '
                    'ARP cannot MITM. Check Npcap + Ethernet driver.',
                    'red',
                )
                return
            self.log(
                f'{action} MITM armed on {iface}: victim {victim_mac} router {router_mac}',
                UI_LOG_VICTIM_BLOCK_FG,
            )
            try:
                from tools.utils import (
                    _extract_adapter_guid,
                    _windows_live_guid_for_iface_name,
                )

                face = getattr(self.scanner, 'iface', None)
                live_gid = _windows_live_guid_for_iface_name(
                    str(getattr(face, 'name', '') or '')
                )
                bound_gid = _extract_adapter_guid(str(getattr(face, 'guid', '') or ''))
                if live_gid and bound_gid and live_gid != bound_gid:
                    self.log(
                        f'{action} ON: Npcap is bound to {bound_gid[:8]}…, not the live '
                        f'Windows adapter {live_gid[:8]}… — poison is going out the '
                        'wrong NIC. Restart Npcap and confirm Settings matches the live adapter.',
                        'orange',
                    )
            except Exception:
                pass
            # Defer forwarding probe — never stall the Kill click path.
            if sys.platform.startswith('win'):
                try:
                    QTimer.singleShot(
                        0,
                        lambda a=action, i=str(iface): self._check_mitm_forwarding_after_arm(
                            a, i
                        ),
                    )
                except Exception:
                    pass
                # WPA3 / Wi‑Fi 7 — UI hint from warm-up cache only (never block click).
                # IPv6 dual-stack is common and noisy in the UI log — keep it in app_log only.
                try:
                    from tools.user_errors import format_error_code
                    from tools.zubcut_log import app_log

                    if bool(getattr(self, '_lan_ipv6_enabled_cached', False)):
                        app_log(
                            'lan_ipv6_enabled',
                            action=str(action),
                            iface=str(iface),
                            code='ZC-IPV6',
                        )
                    for code in list(getattr(self, '_wifi_link_hints_cached', None) or []):
                        self.log(format_error_code(code), 'orange')
                except Exception:
                    pass
        except Exception:
            pass

    def _check_mitm_forwarding_after_arm(self, action: str, iface: str) -> None:
        """Post-arm only: reinforce disable + warn if kernel still relays (off GUI)."""

        def _work() -> None:
            try:
                from networking.killer import (
                    _lan_kill_priority_only,
                    disable_ip_forwarding,
                    is_ip_forwarding_enabled,
                )

                disable_ip_forwarding(
                    priority_iface=str(iface or ''),
                    priority_only=_lan_kill_priority_only(),
                )
                if not is_ip_forwarding_enabled():
                    return
            except Exception:
                return

            def _warn() -> None:
                try:
                    from tools.user_errors import format_error_code

                    self.log(format_error_code('ZC-FWD'), 'red')
                except Exception:
                    self.log(
                        f'{action}: Windows IP forwarding is still ON — '
                        'PS5 may lag but stay online (no full cut). '
                        'Run ZubCut as Administrator, then Kill OFF and ON again.',
                        'red',
                    )

            try:
                QTimer.singleShot(0, _warn)
            except Exception:
                pass

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-mitm-fwd-check',
                daemon=True,
            ).start()
        except Exception:
            pass


    def cut_analysis_enabled(self) -> bool:
        return bool(getattr(self, '_cut_analysis_enabled', False))

    def set_cut_analysis_enabled(self, enabled: bool) -> None:
        """Logs → Analysis toggle: before/during/after cut checks (never delays instant cut)."""
        on = bool(enabled)
        prev = bool(getattr(self, '_cut_analysis_enabled', False))
        self._cut_analysis_enabled = on
        if on == prev:
            return
        if on:
            self.log(
                'Analysis ON — baselines the selected victim, then checks DURING cut and '
                'AFTER restore for Kill / Lag / Dupe / Percent Cut (does not slow instant cut). '
                'For Dupe Analysis use ≥8000 ms (5s is often too short).',
                UI_LOG_VICTIM_BLOCK_FG,
            )
            self._ensure_cut_analysis_baseline_timer(True)
            self._refresh_cut_analysis_baseline(force=True)
        else:
            self.log('Analysis OFF', UI_LOG_RESTORE_FG)
            self._ensure_cut_analysis_baseline_timer(False)
            self._cut_analysis_session = None
            self._cut_analysis_baseline = None

    def _ensure_cut_analysis_baseline_timer(self, on: bool) -> None:
        timer = getattr(self, '_cut_analysis_baseline_timer', None)
        if on:
            if timer is None:
                timer = QTimer(self)
                timer.setInterval(4500)
                timer.timeout.connect(lambda: self._refresh_cut_analysis_baseline(force=False))
                self._cut_analysis_baseline_timer = timer
            if not timer.isActive():
                timer.start()
        elif timer is not None:
            timer.stop()

    def _cut_analysis_selected_device(self):
        try:
            dev = self._get_selected_device()
        except Exception:
            dev = None
        if isinstance(dev, dict) and not dev.get('admin'):
            return dict(dev)
        return None

    def _gather_cut_analysis_host(self, device) -> dict:
        from tools.cut_analysis import collect_host_health, probe_victim_on_lan

        iface = getattr(self.scanner, 'iface', None)
        iface_name = str(getattr(iface, 'name', None) or '')
        iface_ip = str(getattr(iface, 'ip', None) or '')
        guid = str(getattr(iface, 'guid', None) or '').strip()
        router = getattr(self.killer, 'router', None) or getattr(self.scanner, 'router', None) or {}
        gw_mac = str((router or {}).get('mac') or getattr(self.scanner, 'router_mac', '') or '')
        gw_ip = str((router or {}).get('ip') or getattr(self.scanner, 'gateway', '') or '')
        l2_ready = None
        try:
            if hasattr(self.killer, 'l2_socket_ready'):
                l2_ready = bool(self.killer.l2_socket_ready())
        except Exception:
            l2_ready = None
        ip_fwd = None
        if sys.platform.startswith('win'):
            try:
                from networking.killer import is_ip_forwarding_enabled

                ip_fwd = bool(is_ip_forwarding_enabled())
            except Exception:
                ip_fwd = None
        vip = str((device or {}).get('ip') or '').strip() if isinstance(device, dict) else ''
        vmac = str((device or {}).get('mac') or '').strip() if isinstance(device, dict) else ''
        arp_iface = guid
        try:
            from tools.cut_analysis import _npcap_safe_bind_tokens

            toks = _npcap_safe_bind_tokens(guid, iface)
            arp_iface = str(toks[0] if toks else '')
        except Exception:
            arp_iface = guid
        live = probe_victim_on_lan(
            vip,
            vmac,
            iface_ip=iface_ip,
            arp_probe_iface=arp_iface,
        )
        settings_live = None
        if iface_ip:
            settings_live = not str(iface_ip).startswith('169.254.')
        admin_ok = None
        try:
            import ctypes

            admin_ok = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            admin_ok = None
        return collect_host_health(
            iface_name=iface_name,
            iface_ip=iface_ip,
            iface_guid=guid,
            gateway_mac=gw_mac,
            gateway_ip=gw_ip,
            local_mac=str(getattr(iface, 'mac', None) or ''),
            l2_ready=l2_ready,
            ip_forwarding_on=ip_fwd,
            admin_ok=admin_ok,
            victim_in_arp=live.get('victim_in_arp'),
            settings_adapter_live=settings_live,
            victim_ping_ok=live.get('victim_ping_ok'),
            victim_arp_mac=str(live.get('victim_arp_mac') or ''),
            victim_mac_match=live.get('victim_mac_match'),
            victim_on_lan=live.get('victim_on_lan'),
            victim_live_ip=str(live.get('victim_live_ip') or ''),
            victim_liveness_note=str(live.get('victim_liveness_note') or ''),
            selected_victim_ip=vip,
            selected_victim_mac=vmac,
        )

    def _gather_cut_analysis_stack(
        self, device, *, cut_pct: int | None = None, sample_window_ok: bool | None = None
    ) -> dict:
        from tools.cut_analysis import collect_stack_state

        mac = str((device or {}).get('mac') or '').strip() if isinstance(device, dict) else ''
        plan = None
        try:
            plan = self._impairment_plan_for(device) if isinstance(device, dict) else None
        except Exception:
            plan = None
        use_wd = bool(getattr(plan, 'use_windivert', False)) if plan is not None else False
        gate = getattr(self, '_ics_lag_gate', None)
        wd_running = bool(gate is not None and gate.is_running())
        wd_paused = False
        if gate is not None:
            try:
                if hasattr(gate, 'is_paused'):
                    wd_paused = bool(gate.is_paused())
                elif hasattr(gate, 'blocking'):
                    wd_paused = bool(gate.blocking)
                else:
                    wd_paused = bool(
                        getattr(gate, '_paused', False) or getattr(gate, '_blocking', False)
                    )
            except Exception:
                wd_paused = False
        mitm_armed = bool(mac and mac in getattr(self.killer, 'killed', {}))
        fw = getattr(self.killer, 'forwarders', {}).get(mac) if mac else None
        fw_running = bool(fw and getattr(fw, 'running', False))
        fw_hard = False
        if fw_running:
            try:
                fw_hard = bool(
                    getattr(fw, 'drop_from_victim', False)
                    and getattr(fw, 'drop_to_victim', False)
                    and int(getattr(fw, 'pass_from_victim_pct', 100) or 0) == 0
                    and int(getattr(fw, 'pass_to_victim_pct', 100) or 0) == 0
                )
            except Exception:
                fw_hard = False
        seen = dropped = forwarded = None
        if mac:
            try:
                stats = self.killer.get_forwarder_stats(mac) or {}
                if stats:
                    seen = int(stats.get('packets_seen') or 0)
                    dropped = int(stats.get('packets_dropped') or 0)
                    forwarded = int(stats.get('packets_forwarded') or 0)
            except Exception:
                pass
        return collect_stack_state(
            mitm_armed=mitm_armed,
            forwarder_running=fw_running,
            forwarder_hard_drop=fw_hard,
            use_windivert=use_wd,
            windivert_running=wd_running,
            windivert_paused=wd_paused,
            cut_pct=cut_pct,
            fwd_packets_seen=seen,
            fwd_packets_dropped=dropped,
            fwd_packets_forwarded=forwarded,
            sample_window_ok=sample_window_ok,
        )

    def _refresh_cut_analysis_baseline(self, *, force: bool = False) -> None:
        """Rolling BEFORE sample while Analysis is ON (selected victim). Never blocks UI."""
        if not self.cut_analysis_enabled():
            return
        # Skip refreshing mid-flow so BEFORE stays pre-cut.
        if getattr(self, '_cut_analysis_session', None):
            return
        if any(
            (
                getattr(self, 'dupe_active', False),
                getattr(self, 'lag_active', False),
                getattr(self, 'percent_cut_active', False),
            )
        ):
            return
        # Skip while any ARP MITM victim is live (Kill ON).
        try:
            if getattr(self.killer, 'killed', None):
                return
        except Exception:
            pass
        # Skip while Kill is arming — Analysis sniff on Npcap races the forwarder.
        try:
            if getattr(self, '_kill_pending_profiles', None):
                return
        except Exception:
            pass
        device = self._cut_analysis_selected_device()
        if not isinstance(device, dict):
            return
        ip = str(device.get('ip') or '').strip()
        mac = str(device.get('mac') or '').strip()
        if not ip:
            return
        prev = getattr(self, '_cut_analysis_baseline', None) or {}
        if (
            not force
            and prev.get('ip') == ip
            and prev.get('mac') == mac
            and (time.monotonic() - float(prev.get('mono') or 0.0)) < 3.5
        ):
            return
        gen = int(getattr(self, '_cut_analysis_baseline_gen', 0)) + 1
        self._cut_analysis_baseline_gen = gen
        iface = getattr(self.scanner, 'iface', None)
        guid = str(getattr(iface, 'guid', None) or '').strip()
        device_snap = dict(device)

        def _work() -> None:
            from tools.cut_analysis import PHASE_BEFORE, PhaseSample, _sniff_cut_sample

            host_snap = self._gather_cut_analysis_host(device_snap)

            iface_now = getattr(self.scanner, 'iface', None)
            sample = _sniff_cut_sample(
                guid,
                ip,
                seconds=1.2,
                local_mac=str(getattr(iface_now, 'mac', None) or ''),
                gateway_ip=str(host_snap.get('gateway_ip') or ''),
                gateway_mac=str(host_snap.get('gateway_mac') or ''),
                victim_mac=mac,
                iface=iface_now,
            )
            if int(getattr(self, '_cut_analysis_baseline_gen', 0)) != gen:
                return
            if getattr(self, '_cut_analysis_session', None):
                return
            phase = PhaseSample(
                phase=PHASE_BEFORE,
                sample=sample,
                host=host_snap,
                stack={},
                note='rolling baseline while Analysis ON (pre-cut)',
            )
            self._cut_analysis_baseline = {
                'mono': time.monotonic(),
                'ip': ip,
                'mac': mac,
                'phase': phase,
            }

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-cut-analysis-before',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _begin_cut_analysis_session(
        self, device, *, flow: str = 'Kill', cut_pct: int | None = None
    ) -> None:
        """Freeze BEFORE baseline at flow start (instant cut must not wait)."""
        if not self.cut_analysis_enabled():
            return
        if not isinstance(device, dict):
            return
        dev = dict(device)
        try:
            dev = self._device_with_plan_ip(dev)
        except Exception:
            pass
        ip = str(dev.get('ip') or '').strip()
        mac = str(dev.get('mac') or '').strip()
        flow_s = str(flow or 'Cut')
        baseline = getattr(self, '_cut_analysis_baseline', None) or {}
        before = baseline.get('phase') if baseline.get('ip') == ip else None
        # If no fresh baseline, capture a tiny non-blocking note — do not sniff here
        # (would race/delay the cut). DURING/AFTER still run.
        if before is None:
            from tools.cut_analysis import PHASE_BEFORE, PhaseSample

            before = PhaseSample(
                phase=PHASE_BEFORE,
                sample={'ok': False, 'error': 'no pre-cut baseline yet — keep Analysis ON a few seconds', 'ipv4': 0, 'ipv6': 0, 'arp': 0, 'arp_victim': 0, 'total': 0, 'seconds': 0},
                host={},
                stack={},
                note='no rolling baseline frozen — Analysis needs a few idle seconds before the click',
            )
        sess_gen = int(getattr(self, '_cut_analysis_gen', 0)) + 1
        self._cut_analysis_gen = sess_gen
        self._cut_analysis_session = {
            'gen': sess_gen,
            'flow': flow_s,
            'device': dev,
            'ip': ip,
            'mac': mac,
            'cut_pct': cut_pct,
            'before': before,
            'during': None,
            'after': None,
            'finalized': False,
            'report_saved': False,
        }
        try:
            self.log(
                f'Analysis [{flow_s}]: collecting BEFORE/DURING/AFTER for {ip or "?"} '
                '(one report when finished)',
                'gray',
            )
        except Exception:
            pass
        # Fallback DURING: if MITM never arms (stale/offline IP), post-arm scheduling
        # never runs and the report would never save. Sample anyway after a short wait.
        try:
            self._schedule_cut_analysis_during_fallback(
                sess_gen, dev, flow=flow_s, cut_pct=cut_pct
            )
        except Exception:
            pass

    def _schedule_cut_analysis_during_fallback(
        self, gen: int, device, *, flow: str = 'Kill', cut_pct: int | None = None
    ) -> None:
        """Ensure DURING is collected even when post-arm hooks never fire."""

        def _work() -> None:
            import time as _time

            _time.sleep(1.6)
            live = getattr(self, '_cut_analysis_session', None)
            if not isinstance(live, dict) or int(live.get('gen') or 0) != gen:
                return
            if live.get('finalized') or live.get('report_saved'):
                return
            if live.get('during') is not None:
                return
            if not self.cut_analysis_enabled():
                return
            # Prefer the normal post-arm sampler if a later arm schedules it first.
            try:
                self._schedule_cut_analysis_if_enabled(
                    device, flow=flow, cut_pct=cut_pct
                )
            except Exception:
                pass

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-cut-analysis-during-fallback',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _schedule_cut_analysis_if_enabled(
        self, device, *, flow: str = 'Kill', cut_pct: int | None = None
    ) -> None:
        """DURING phase after arm — never before poison/cut."""
        if not self.cut_analysis_enabled():
            return
        if not isinstance(device, dict):
            return
        # Ensure a session exists (Kill re-ON / paths that skipped begin).
        sess = getattr(self, '_cut_analysis_session', None)
        if not isinstance(sess, dict) or sess.get('finalized'):
            self._begin_cut_analysis_session(device, flow=flow, cut_pct=cut_pct)
            sess = getattr(self, '_cut_analysis_session', None)
        if not isinstance(sess, dict):
            return
        gen = int(sess.get('gen') or 0)
        flow_s = str(sess.get('flow') or flow or 'Cut')
        pct = cut_pct if cut_pct is not None else sess.get('cut_pct')
        dev = dict(sess.get('device') or device)

        def _work() -> None:
            import time as _time

            # Short settle so poison/forwarder exist, but stay inside Dupe/hold window.
            # (1.0s sleep + 2.0s sniff often overran 5s Dupe once arm latency is included.)
            _time.sleep(0.35)
            live = getattr(self, '_cut_analysis_session', None)
            if not isinstance(live, dict) or int(live.get('gen') or 0) != gen:
                return
            if not self.cut_analysis_enabled():
                return
            from tools.cut_analysis import PHASE_DURING, PhaseSample, _sniff_cut_sample

            iface = getattr(self.scanner, 'iface', None)
            guid = str(getattr(iface, 'guid', None) or '').strip()
            local_mac = str(getattr(iface, 'mac', None) or '').strip()
            ip = str(dev.get('ip') or '').strip()
            mac = str(dev.get('mac') or live.get('mac') or '').strip()
            # Snapshot stack WHILE cut should still be ON (before long sniff).
            still_on = bool(mac and mac in getattr(self.killer, 'killed', {}))
            if not still_on:
                try:
                    still_on = bool(
                        getattr(self, 'dupe_active', False)
                        or getattr(self, 'lag_active', False)
                        or getattr(self, 'percent_cut_active', False)
                        or (
                            callable(getattr(self, '_has_explicit_kill_active', None))
                            and bool(self._has_explicit_kill_active())
                        )
                    )
                except Exception:
                    still_on = False
            host = self._gather_cut_analysis_host(dev)
            stack = self._gather_cut_analysis_stack(
                dev, cut_pct=pct, sample_window_ok=still_on
            )
            fw = getattr(self.killer, 'forwarders', {}).get(mac) if mac else None
            fw_live = bool(fw and getattr(fw, 'running', False))
            if fw_live:
                # A second Npcap sniff on this adapter starves the Kill forwarder
                # (seen=0 / "Kill does nothing") while Analysis still sees ARP TX.
                _time.sleep(1.65)
                try:
                    stack2 = self._gather_cut_analysis_stack(
                        dev, cut_pct=pct, sample_window_ok=True
                    )
                    stack.update(stack2 or {})
                except Exception:
                    pass
                seen = int(stack.get('fwd_packets_seen') or 0)
                dropped = int(stack.get('fwd_packets_dropped') or 0)
                sample = {
                    'ok': True,
                    'error': '',
                    'ipv4': max(0, seen),
                    'ipv6': 0,
                    'arp': 0,
                    'arp_victim': 0,
                    'poison_arp_seen': 0,
                    'victim_to_us': seen,
                    'victim_wan_out_to_us': dropped,
                    'victim_wan_bypass_gw': 0,
                    'wan_return_bypass': 0,
                    'victim_lan_ipv4': 0,
                    'total': seen,
                    'seconds': 1.65,
                }
            else:
                gw_ip = str(host.get('gateway_ip') or '')
                gw_mac = str(host.get('gateway_mac') or '')
                sample = _sniff_cut_sample(
                    guid,
                    ip,
                    seconds=2.0,
                    local_mac=local_mac,
                    gateway_ip=gw_ip,
                    gateway_mac=gw_mac,
                    victim_mac=mac,
                    iface=iface,
                )
            # Refresh forwarder counters after sniff if still armed.
            if mac and mac in getattr(self.killer, 'killed', {}):
                try:
                    stack2 = self._gather_cut_analysis_stack(
                        dev, cut_pct=pct, sample_window_ok=True
                    )
                    for key in (
                        'fwd_packets_seen',
                        'fwd_packets_dropped',
                        'fwd_packets_forwarded',
                        'forwarder_running',
                        'forwarder_hard_drop',
                        'mitm_armed',
                    ):
                        if stack2.get(key) is not None:
                            stack[key] = stack2.get(key)
                except Exception:
                    pass
            during = PhaseSample(
                phase=PHASE_DURING,
                sample=sample,
                host=host,
                stack=stack,
                note=(
                    'cut armed (post-instant)'
                    if still_on
                    else 'sample window missed — cut already OFF (use ≥8000 ms for Analysis)'
                ),
            )
            live = getattr(self, '_cut_analysis_session', None)
            if not isinstance(live, dict) or int(live.get('gen') or 0) != gen:
                return
            live['during'] = during
            # Only write the Desktop report when BEFORE+DURING+AFTER are all ready.
            if live.get('after') is not None or live.get('finalize_when_during'):
                self._finalize_cut_analysis_session(gen)

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-cut-analysis-during',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _schedule_cut_analysis_after_off(
        self, device, *, flow: str = 'Kill'
    ) -> None:
        """AFTER phase once UI turns OFF — complete the single full report."""
        if not self.cut_analysis_enabled():
            return
        sess = getattr(self, '_cut_analysis_session', None)
        # Already wrote the one report for this run — never start a second session.
        if isinstance(sess, dict) and (sess.get('finalized') or sess.get('report_saved')):
            return
        if not isinstance(sess, dict):
            # No session (Analysis toggled mid-flight) — still collect a full cycle.
            if isinstance(device, dict):
                self._begin_cut_analysis_session(device, flow=flow)
                sess = getattr(self, '_cut_analysis_session', None)
        if not isinstance(sess, dict):
            return
        gen = int(sess.get('gen') or 0)
        pct = sess.get('cut_pct')
        dev = dict(device) if isinstance(device, dict) else dict(sess.get('device') or {})

        def _work() -> None:
            import time as _time

            # Let unkill / reinforce_restore settle.
            _time.sleep(0.85)
            live = getattr(self, '_cut_analysis_session', None)
            if not isinstance(live, dict) or int(live.get('gen') or 0) != gen:
                return
            if live.get('finalized') or live.get('report_saved'):
                return
            from tools.cut_analysis import PHASE_AFTER, PhaseSample, _empty_cut_sample

            host = self._gather_cut_analysis_host(dev)
            stack = self._gather_cut_analysis_stack(dev, cut_pct=pct)
            # AFTER sniff on this Wi‑Fi NIC steals Npcap from restore/pass-through
            # (~1s after OFF). Stack/host only — do not open a second sniffer.
            sample = _empty_cut_sample(reason='after_off_skip_npcap')
            after = PhaseSample(
                phase=PHASE_AFTER,
                sample=sample,
                host=host,
                stack=stack,
                note='flow OFF — restore check (no Npcap sniff)',
            )
            live = getattr(self, '_cut_analysis_session', None)
            if not isinstance(live, dict) or int(live.get('gen') or 0) != gen:
                return
            if live.get('finalized') or live.get('report_saved'):
                return
            live['after'] = after
            if live.get('during') is None:
                # Prefer waiting briefly for an in-flight DURING sampler, but never
                # drop the report if MITM never armed (stale .248 / offline IP).
                live['finalize_when_during'] = True

                def _finalize_if_still_missing() -> None:
                    import time as _time

                    _time.sleep(2.2)
                    cur = getattr(self, '_cut_analysis_session', None)
                    if not isinstance(cur, dict) or int(cur.get('gen') or 0) != gen:
                        return
                    if cur.get('finalized') or cur.get('report_saved'):
                        return
                    if cur.get('during') is None:
                        from tools.cut_analysis import missing_during_phase_sample

                        cur['during'] = missing_during_phase_sample(
                            host=host,
                            stack=stack,
                            note=(
                                'DURING missing — cut never armed on this IP '
                                '(stale/offline row?). Report still saved.'
                            ),
                        )
                    self._finalize_cut_analysis_session(gen)

                try:
                    threading.Thread(
                        target=safe_daemon_target(_finalize_if_still_missing),
                        name='zubcut-cut-analysis-during-wait',
                        daemon=True,
                    ).start()
                except Exception:
                    from tools.cut_analysis import missing_during_phase_sample

                    live['during'] = missing_during_phase_sample(
                        host=host,
                        stack=stack,
                        note='DURING missing — cut never armed; report still saved.',
                    )
                    self._finalize_cut_analysis_session(gen)
                return
            self._finalize_cut_analysis_session(gen)

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-cut-analysis-after',
                daemon=True,
            ).start()
        except Exception:
            pass

    def _cut_analysis_expect_full(self, flow_s: str) -> bool:
        """Kill/Dupe require a proven full cut; Percent Cut / Lag do not."""
        flow_l = str(flow_s or '').lower()
        if flow_l.startswith('percent') or flow_l.startswith('lag'):
            return False
        return True

    def _finalize_cut_analysis_session(self, gen: int) -> None:
        """Write one Desktop report with BEFORE + DURING + AFTER — never mid-run."""
        live = getattr(self, '_cut_analysis_session', None)
        if not isinstance(live, dict) or int(live.get('gen') or 0) != gen:
            return
        if live.get('finalized') or live.get('report_saved'):
            return
        if live.get('before') is None or live.get('during') is None or live.get('after') is None:
            return
        live['finalized'] = True
        from tools.cut_analysis import save_cut_analysis_report, score_phases

        flow_s = str(live.get('flow') or 'Cut')
        dev = dict(live.get('device') or {})
        ip = str(live.get('ip') or dev.get('ip') or '').strip()
        mac = str(live.get('mac') or dev.get('mac') or '').strip()
        try:
            report = score_phases(
                flow=flow_s,
                victim_ip=ip,
                victim_mac=mac,
                expect_full_cut=self._cut_analysis_expect_full(flow_s),
                before=live.get('before'),
                during=live.get('during'),
                after=live.get('after'),
                cut_pct=live.get('cut_pct'),
            )
            # Single file: Desktop\ZubCut Diagnostics + Notepad.
            # Always attempt save/open — including stale/offline IPs (FAIL report).
            path = save_cut_analysis_report(report, open_report=True)
            live['report_saved'] = bool(path)
        except Exception:
            self._cut_analysis_session = None
            return

        def _on_main() -> None:
            overall = str(getattr(report, 'overall', '') or '')
            color = UI_LOG_VICTIM_BLOCK_FG if overall == 'SUCCESS' else 'red'
            self.log(report.summary_line, color)
            for line in report.lines:
                if 'OVERALL RESULT' in line or line.startswith('[FAIL]') or line.startswith(
                    '[RESULT]'
                ):
                    self.log(
                        f'Analysis: {line.strip()}',
                        'red' if ('FAIL' in line or overall != 'SUCCESS') and 'SUCCESS' not in line else color,
                    )
            if report.report_path:
                self.log(
                    f'Analysis report (BEFORE+DURING+AFTER) saved: {report.report_path}',
                    'gray',
                )
            elif not path:
                self.log(
                    f'Analysis [{flow_s}]: report failed to save for {ip or "?"}',
                    'red',
                )
            if getattr(self, '_cut_analysis_session', None) and int(
                (self._cut_analysis_session or {}).get('gen') or 0
            ) == gen:
                self._cut_analysis_session = None

        try:
            QTimer.singleShot(0, _on_main)
        except Exception:
            pass

    def _run_cut_analysis_now(
        self, device, *, flow: str = 'Kill', cut_pct: int | None = None
    ):
        """Legacy single-shot DURING helper (tests / fallback)."""
        from tools.cut_analysis import analyze_victim_cut

        if not isinstance(device, dict):
            return None
        mac = str(device.get('mac') or '').strip()
        ip = str(device.get('ip') or '').strip()
        iface = getattr(self.scanner, 'iface', None)
        guid = str(getattr(iface, 'guid', None) or '').strip()
        iface_name = str(getattr(iface, 'name', None) or '')
        host = self._gather_cut_analysis_host(device)
        stack = self._gather_cut_analysis_stack(device, cut_pct=cut_pct)
        before = None
        baseline = getattr(self, '_cut_analysis_baseline', None) or {}
        if baseline.get('ip') == ip:
            before = baseline.get('phase')
        # Fallback helper for tests — session finalize is the only save/Notepad path.
        return analyze_victim_cut(
            flow=str(flow or 'Cut'),
            victim_ip=ip,
            victim_mac=mac,
            gateway_mac=str(host.get('gateway_mac') or ''),
            iface_guid=guid,
            iface_name=iface_name,
            seconds=2.0,
            expect_full_cut=self._cut_analysis_expect_full(str(flow or 'Cut')),
            cut_pct=cut_pct,
            mitm_armed=bool(stack.get('mitm_armed')),
            forwarder_running=bool(stack.get('forwarder_running')),
            forwarder_hard_drop=bool(stack.get('forwarder_hard_drop')),
            ip_forwarding_on=host.get('ip_forwarding_on'),
            use_windivert=bool(stack.get('use_windivert')),
            windivert_paused=bool(stack.get('windivert_paused')),
            windivert_running=bool(stack.get('windivert_running')),
            before=before,
            host=host,
        )

    def _schedule_mitm_traffic_probe(self, device, *, flow: str = 'Kill') -> None:
        """After MITM arms, warn if no victim IP traffic reaches this NIC."""
        if not isinstance(device, dict):
            return
        mac = str(device.get('mac') or '').strip()
        ip = str(device.get('ip') or '').strip()
        iface = getattr(self.scanner, 'iface', None)
        guid = str(getattr(iface, 'guid', None) or '').strip()
        if not mac or not ip or not guid:
            self._schedule_cut_analysis_if_enabled(device, flow=flow)
            return

        def _probe() -> None:
            import time

            time.sleep(1.2)
            if mac not in getattr(self.killer, 'killed', {}):
                return
            try:
                fw = getattr(self.killer, 'forwarders', {}).get(mac)
                if fw is not None and hasattr(fw, 'get_stats'):
                    seen = int((fw.get_stats() or {}).get('packets_seen') or 0)
                else:
                    seen = int(getattr(fw, '_pkt_count', 0) or 0) if fw is not None else 0
            except Exception:
                return
            if seen != 0:
                return

            def _on_main() -> None:
                if mac not in getattr(self.killer, 'killed', {}):
                    return
                if self._retry_mitm_on_arp_iface(device, mac, ip, flow):
                    return
                from tools.mitm_probe import mitm_path_warning

                msg = mitm_path_warning(iface, ip)
                self.log(f'{flow}: {msg}', 'red')

            try:
                QTimer.singleShot(0, _on_main)
            except Exception:
                pass

        try:
            threading.Thread(
                target=safe_daemon_target(_probe), name='zubcut-mitm-probe', daemon=True
            ).start()
        except Exception:
            pass
        # Deep Analysis (Logs toggle) — after arm only; never before instant cut.
        self._schedule_cut_analysis_if_enabled(device, flow=flow)


    def _retry_mitm_on_arp_iface(self, device, mac: str, ip: str, flow: str) -> bool:
        """
        When MITM is armed but no packets arrive, rebind to the NIC whose ARP cache
        lists the victim (common when Settings points at Ethernet but PS5 is on Wi‑Fi).
        """
        if not isinstance(device, dict) or not mac or not ip:
            return False
        if mac in getattr(self, '_mitm_probe_retried_macs', set()):
            return False
        if mac not in getattr(self.killer, 'killed', {}):
            return False
        try:
            from tools.utils import (
                _iface_live_ipv4,
                _parse_windows_arp_by_interface,
                get_ifaces_cached,
            )

            by_iface = _parse_windows_arp_by_interface()
            if not by_iface:
                return False
            current_guid = str(getattr(getattr(self.scanner, 'iface', None), 'guid', '') or '')
            target = None
            for iface in get_ifaces_cached():
                lip = _iface_live_ipv4(iface)
                if not lip or ip not in by_iface.get(lip, set()):
                    continue
                if str(iface.guid) == current_guid:
                    return False
                target = iface
                break
            if target is None:
                return False
            self.scanner.iface = target
            try:
                from tools.utils import refresh_netface_live_ip

                refresh_netface_live_ip(self.scanner.iface)
            except Exception:
                pass
            self._ensure_network_context_for_victim(device, fast=False)
            self.killer.iface = self.scanner.iface
            self.killer.router = getattr(self.scanner, 'router', None) or self.killer.router
            self.killer.reassert_poison(device)
            try:
                self.killer._apply_traffic_cut_sync(device)
            except Exception:
                pass
            try:
                iface_name = self.scanner.iface.name if self.scanner.iface else 'en0'
            except Exception:
                iface_name = 'en0'
            _bg_block_ip(iface_name, ip, 'both')
            label = getattr(self.scanner.iface, 'name', None) or '?'
            self._mitm_probe_retried_macs.add(mac)
            self.log(
                f'{flow}: no traffic on prior adapter — retried MITM via {label} '
                f'({getattr(self.scanner.iface, "ip", "") or "?"})',
                UI_LOG_VICTIM_BLOCK_FG,
            )
            self._schedule_mitm_traffic_probe(device, flow=flow)
            return True
        except Exception:
            return False


    def _clear_mitm_probe_retry(self, mac: str | None) -> None:
        if mac:
            getattr(self, '_mitm_probe_retried_macs', set()).discard(str(mac).strip())


    def _refresh_advanced_lag_mitm_if_visible(self) -> None:
        dlg = getattr(self, 'advanced_lag_settings_dialog', None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg._refresh_mitm_status()
            except Exception:
                pass


    def _mitm_adv_sched_record(self, du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, gates=None):
        from tools import mitm_adv_sched

        g = gates if gates is not None else (1.0, 1.0, 1.0, 1.0)
        self._mitm_adv_last_sched = mitm_adv_sched.sched_apply_tuple(
            du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, g
        )


    def _mitm_adv_get(self, key: str, default=None):
        """Scheduler reads live Advanced Lag dialog UI when open, else saved settings."""
        dlg = getattr(self, 'advanced_lag_settings_dialog', None)
        if dlg is not None and getattr(dlg, '_chk_adv_delay_on', None) is not None:
            try:
                return dlg.mitm_adv_settings_get(key, default)
            except Exception:
                pass
        return get_settings(key, default)


    def _reset_mitm_adv_sched_clock(self, row_prefix: str | None = None) -> None:
        """Restart timer phase origin for one impairment row, or all rows."""
        from tools import mitm_adv_sched

        now = mitm_adv_sched.monotonic_now()
        if row_prefix:
            self._mitm_adv_row_t0[str(row_prefix)] = now
        else:
            self._mitm_adv_row_t0 = {p: now for p in mitm_adv_sched.ROW_PREFIXES}
            self._mitm_adv_sched_t0 = now
        self._mitm_adv_last_sched = None


    def _start_mitm_adv_schedule(self):
        t = getattr(self, '_mitm_adv_sched_timer', None)
        if t is not None and getattr(self, 'mitm_shaping_active', False) and not t.isActive():
            t.start()


    def _stop_mitm_adv_schedule(self):
        t = getattr(self, '_mitm_adv_sched_timer', None)
        if t is not None:
            t.stop()
        self._mitm_adv_last_sched = None


    def _mitm_adv_schedule_tick(self):
        if not getattr(self, 'mitm_shaping_active', False):
            self._stop_mitm_adv_schedule()
            return
        if getattr(self, 'percent_cut_active', False):
            self._stop_mitm_adv_schedule()
            return
        if getattr(self, 'lag_active', False) or getattr(self, 'dupe_active', False):
            return
        from tools import mitm_adv_sched

        now = mitm_adv_sched.monotonic_now()
        t0 = float(getattr(self, '_mitm_adv_sched_t0', 0.0) or 0.0)
        if t0 <= 0.0:
            self._reset_mitm_adv_sched_clock()
            t0 = float(self._mitm_adv_sched_t0)
        row_t0 = dict(getattr(self, '_mitm_adv_row_t0', None) or {})
        du, dd, ju, jd, cu, cd, lu, ld, gates = mitm_adv_sched.gated_mitm_params(
            now, t0, self._mitm_adv_get, row_t0
        )
        if mitm_adv_sched.all_enabled_timers_finished(
            now, t0, self._mitm_adv_get, row_t0
        ):
            self.stop_mitm_shaping(log=True)
            return
        prev = getattr(self, '_mitm_adv_last_sched', None)
        cur_tuple = mitm_adv_sched.sched_apply_tuple(
            du, dd, ju, jd, cu, cd, lu, ld, gates
        )
        if prev == cur_tuple:
            return
        self.start_mitm_shaping_from_advanced(
            du, dd, ju, jd, cu, cd, lu, ld, sched_tick=True
        )


    def _mitm_adv_apply_sched_tick(
        self,
        device,
        mac: str,
        *,
        du: int,
        dd: int,
        ju: int,
        jd: int,
        cu_mbps: float,
        cd_mbps: float,
        lu: int,
        ld: int,
        adv_gates,
        use_wd: bool,
    ) -> bool:
        """Apply one scheduler tick without full MITM restart. Returns True if handled."""
        if getattr(self, 'lag_active', False) or getattr(self, 'dupe_active', False):
            self._refresh_advanced_lag_mitm_if_visible()
            return True
        if use_wd and self._uses_windivert(device):
            if self._ics_apply_advanced_shaping_windivert(
                device,
                du=du,
                dd=dd,
                ju=ju,
                jd=jd,
                lu=lu,
                ld=ld,
                cu_mbps=cu_mbps,
                cd_mbps=cd_mbps,
            ):
                self._mitm_shaping_backend = 'windivert'
                self._ics_windivert_shaper = self._ics_lag_gate
                self._mitm_adv_sched_record(
                    du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
                )
                self._start_mitm_adv_schedule()
                self._refresh_advanced_lag_mitm_if_visible()
            return True
        backend = getattr(self, '_mitm_shaping_backend', None)
        if backend == 'windivert' and use_wd and self._ics_lag_gate is not None:
            if self._ics_apply_advanced_shaping_windivert(
                device,
                du=du,
                dd=dd,
                ju=ju,
                jd=jd,
                lu=lu,
                ld=ld,
                cu_mbps=cu_mbps,
                cd_mbps=cd_mbps,
            ):
                self._mitm_adv_sched_record(
                    du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
                )
                self._start_mitm_adv_schedule()
                self._refresh_advanced_lag_mitm_if_visible()
                return True
        if backend == 'windivert' and not use_wd and self._ics_lag_gate is not None:
            try:
                self._ics_lag_gate.clear_shaping()
                self._ics_lag_gate.prepare_stop()
                self._stop_ics_lag_gate()
            except Exception:
                pass
            self._ics_windivert_shaper = None
            self._mitm_shaping_backend = 'forwarder'
            backend = 'forwarder'
        if backend == 'forwarder':
            if self._uses_windivert(device):
                self._refresh_advanced_lag_mitm_if_visible()
                return True
            try:
                self._ensure_network_context_for_victim(device, fast=True)
                self.killer.apply_link_shaping(
                    device,
                    delay_ms_out=du,
                    delay_ms_in=dd,
                    jitter_ms_out=ju,
                    jitter_ms_in=jd,
                    loss_pct_out=lu,
                    loss_pct_in=ld,
                    max_kbps_out=cu_mbps * 1000.0,
                    max_kbps_in=cd_mbps * 1000.0,
                )
            except Exception as exc:
                self.log(f'MITM shaping update failed: {exc}', 'red')
                self._refresh_advanced_lag_mitm_if_visible()
                return True
            self._mitm_adv_sched_record(
                du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
            )
            self._start_mitm_adv_schedule()
            self._refresh_advanced_lag_mitm_if_visible()
            return True
        return False


    def start_mitm_shaping_from_advanced(
        self,
        delay_up,
        delay_down,
        jitter_up=0,
        jitter_down=0,
        cap_up=0.0,
        cap_down=0.0,
        loss_up=0,
        loss_down=0,
        *,
        sched_tick=False,
    ):
        """Forwarder shaping from Advanced Lag (delay, jitter, caps, loss)."""
        if not sched_tick:
            if not self.connected():
                self._refresh_advanced_lag_mitm_if_visible()
                return
            if self._toggle_start_blocked('mitmshape'):
                self._refresh_advanced_lag_mitm_if_visible()
                return
            device = self._get_selected_device()
            if not device:
                self.log('Select a device in the list first.', 'red')
                self._refresh_advanced_lag_mitm_if_visible()
                return
            if device.get('admin'):
                self.log('Cannot shape admin device', UI_LOG_VICTIM_BLOCK_FG)
                self._refresh_advanced_lag_mitm_if_visible()
                return
            mac = str(device.get('mac') or '').strip()
            if not _is_valid_ip(device.get('ip') or ''):
                self.log('Target has no IP yet — cannot start shaping.', 'red')
                self._refresh_advanced_lag_mitm_if_visible()
                return
            if not self.mitm_shaping_active or self.mitm_shaping_mac != mac:
                self.mitm_shaping_active = True
                self.mitm_shaping_mac = mac
                self.mitm_shaping_device_ip = str(device.get('ip') or '').strip()
                self._refresh_advanced_lag_mitm_if_visible()
                self._paint_flow_start_ui('all', device)
            self._mitmshape_start_gen = int(getattr(self, '_mitmshape_start_gen', 0)) + 1
            shape_gen = self._mitmshape_start_gen
            args = (
                delay_up,
                delay_down,
                jitter_up,
                jitter_down,
                cap_up,
                cap_down,
                loss_up,
                loss_down,
            )

            def _deferred_start():
                if int(getattr(self, '_mitmshape_start_gen', 0)) != shape_gen:
                    return
                self._await_mitm_teardown_thread()
                if int(getattr(self, '_mitmshape_start_gen', 0)) != shape_gen:
                    return
                self.start_mitm_shaping_from_advanced(*args, sched_tick=True)

            QTimer.singleShot(0, _deferred_start)
            return
        if not self.connected():
            self._refresh_advanced_lag_mitm_if_visible()
            return
        if self._toggle_start_blocked('mitmshape'):
            self._refresh_advanced_lag_mitm_if_visible()
            return
        # While shaping is already running, apply parameter changes to the shaped device even if
        # the table selection moved (otherwise toggles in Advanced Lag appear to do nothing).
        shaping_mac = self.mitm_shaping_mac if self.mitm_shaping_active else None
        if shaping_mac:
            selected = self._get_selected_device()
            if selected is not None and selected.get('mac') == shaping_mac:
                device = selected
            else:
                device = self._victim_record_for_mac(shaping_mac) or self._get_device_by_mac(
                    shaping_mac
                )
            if not device:
                self.log(
                    'The device being shaped is no longer in the list — use Stop, turn Kill off, or rescan.',
                    'red',
                )
                self._refresh_advanced_lag_mitm_if_visible()
                return
        else:
            device = self._get_selected_device()
            if not device:
                self.log('Select a device in the list first.', 'red')
                self._refresh_advanced_lag_mitm_if_visible()
                return
        if device.get('admin'):
            self.log('Cannot shape admin device', UI_LOG_VICTIM_BLOCK_FG)
            self._refresh_advanced_lag_mitm_if_visible()
            return
        mac = device['mac']
        if not _is_valid_ip(device.get('ip') or ''):
            self.log('Target has no IP yet — cannot start shaping.', 'red')
            self._refresh_advanced_lag_mitm_if_visible()
            return

        from tools import mitm_adv_sched

        prev_active = self.mitm_shaping_active
        prev_sm = self.mitm_shaping_mac
        if not prev_active or prev_sm != mac:
            self._reset_mitm_adv_sched_clock()
        row_t0 = dict(getattr(self, '_mitm_adv_row_t0', None) or {})
        du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates = mitm_adv_sched.gated_mitm_params(
            mitm_adv_sched.monotonic_now(),
            self._mitm_adv_sched_t0,
            self._mitm_adv_get,
            row_t0,
        )
        du = max(0, int(du))
        dd = max(0, int(dd))
        ju = max(0, int(ju))
        jd = max(0, int(jd))
        cu_mbps = max(0.0, float(cu_mbps))
        cd_mbps = max(0.0, float(cd_mbps))
        lu = max(0, min(100, int(lu)))
        ld = max(0, min(100, int(ld)))
        allow_zero = bool(sched_tick or (prev_active and prev_sm == mac))
        all_zero = (
            du <= 0
            and dd <= 0
            and ju <= 0
            and jd <= 0
            and cu_mbps <= 0
            and cd_mbps <= 0
            and lu <= 0
            and ld <= 0
        )
        if all_zero and not allow_zero:
            if not sched_tick:
                self.log(
                    'Enable at least one effect with non-zero values (delay, jitter, cap, or loss).',
                    'red',
                )
            self._revert_mitm_shaping_ui_if_no_backend()
            self._refresh_advanced_lag_mitm_if_visible()
            return

        use_wd = use_windivert_for_advanced_ics_shaping(self.scanner, device)
        if sched_tick and self.mitm_shaping_active and prev_sm == mac and shaping_mac == mac:
            if self._mitm_adv_apply_sched_tick(
                device,
                mac,
                du=du,
                dd=dd,
                ju=ju,
                jd=jd,
                cu_mbps=cu_mbps,
                cd_mbps=cd_mbps,
                lu=lu,
                ld=ld,
                adv_gates=adv_gates,
                use_wd=use_wd,
            ):
                return

        if (
            shaping_mac
            and shaping_mac == mac
            and self.mitm_shaping_active
            and getattr(self, '_mitm_shaping_backend', None) == 'windivert'
            and self._ics_lag_gate is not None
            and use_wd
        ):
            if getattr(self, 'lag_active', False) or getattr(self, 'dupe_active', False):
                self._refresh_advanced_lag_mitm_if_visible()
                return
            if self._ics_apply_advanced_shaping_windivert(
                device,
                du=du,
                dd=dd,
                ju=ju,
                jd=jd,
                lu=lu,
                ld=ld,
                cu_mbps=cu_mbps,
                cd_mbps=cd_mbps,
            ):
                self._mitm_adv_sched_record(
                    du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
                )
                self._start_mitm_adv_schedule()
                self._refresh_advanced_lag_mitm_if_visible()
            return

        self.stopLagSwitch(refresh_dialog=True)
        self.stopDupe(refresh_dialog=False, log=False)
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)

        use_forwarder = True
        self._mitm_shaping_backend = None
        from tools.ics_windivert_shaper import IcsWinDivertShaper

        if use_wd:
            if mac in self.killer.killed:
                try:
                    v0 = self._victim_record_for_mac(mac) or device
                    self.killer.unkill(v0)
                except Exception:
                    pass
            try:
                self.killer.disable_percent_cut(mac)
            except Exception:
                pass
            try:
                if not self._ics_apply_advanced_shaping_windivert(
                    device,
                    du=du,
                    dd=dd,
                    ju=ju,
                    jd=jd,
                    lu=lu,
                    ld=ld,
                    cu_mbps=cu_mbps,
                    cd_mbps=cd_mbps,
                ):
                    raise OSError('WinDivert gate failed')
                self._mitm_shaping_backend = 'windivert'
                use_forwarder = False
            except Exception as exc:
                detail = clumsy_windivert_unavailable_reason(device)
                if self._uses_windivert(device):
                    self.log(
                        f'Advanced lag WinDivert failed ({exc}) [{detail}]',
                        'red',
                    )
                    self._revert_mitm_shaping_ui_if_no_backend()
                else:
                    self.log(
                        f'WinDivert shaping failed ({exc}); using MITM forwarder instead.',
                        'red',
                    )
                self._ics_windivert_shaper = None
                if self._uses_windivert(device):
                    self._refresh_advanced_lag_mitm_if_visible()
                    return

        if use_forwarder:
            if self._uses_windivert(device):
                if not sched_tick:
                    reason = clumsy_windivert_unavailable_reason(device)
                    self.log(
                        'Advanced lag on PC hotspot needs WinDivert — not ARP Kill/forwarder. '
                        + reason,
                        'red',
                    )
                self._revert_mitm_shaping_ui_if_no_backend()
                self._refresh_advanced_lag_mitm_if_visible()
                return
            try:
                self._ensure_network_context_for_victim(device, fast=True)
                self.killer.apply_link_shaping(
                    device,
                    delay_ms_out=du,
                    delay_ms_in=dd,
                    jitter_ms_out=ju,
                    jitter_ms_in=jd,
                    loss_pct_out=lu,
                    loss_pct_in=ld,
                    max_kbps_out=cu_mbps * 1000.0,
                    max_kbps_in=cd_mbps * 1000.0,
                )
            except Exception as exc:
                self.log(f'MITM shaping failed: {exc}', 'red')
                self._revert_mitm_shaping_ui_if_no_backend()
                self._refresh_advanced_lag_mitm_if_visible()
                return
            self._ics_windivert_shaper = None
            self._mitm_shaping_backend = 'forwarder'

        if use_wd and self._uses_windivert(device):
            resolved_ip = self._ics_hotspot_victim_ip(device, mitmshape=True) or str(
                device.get('ip') or ''
            ).strip()
        else:
            resolved_ip = clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
                device.get('ip') or ''
            ).strip()
        self.mitm_shaping_active = True
        self.mitm_shaping_mac = mac
        self.mitm_shaping_device_ip = resolved_ip
        if self._mitm_shaping_backend == 'forwarder':
            self._set_killed_profile(device, True)
            self._sync_killed_devices()
            self._write_remembered_killed_macs()
        parts = []
        if du > 0:
            parts.append(f'out delay {du}ms')
        if dd > 0:
            parts.append(f'in delay {dd}ms')
        if ju > 0:
            parts.append(f'out jitter +0–{ju}ms')
        if jd > 0:
            parts.append(f'in jitter +0–{jd}ms')
        if cu_mbps > 0:
            parts.append(f'out cap {cu_mbps:g}Mbps')
        elif bool(get_settings('mitm_adv_cap_on')) and bool(get_settings('mitm_adv_cap_out')):
            parts.append('out cap ∞')
        if cd_mbps > 0:
            parts.append(f'in cap {cd_mbps:g}Mbps')
        elif bool(get_settings('mitm_adv_cap_on')) and bool(get_settings('mitm_adv_cap_in')):
            parts.append('in cap ∞')
        if lu > 0:
            parts.append(f'out loss {lu}%')
        if ld > 0:
            parts.append(f'in loss {ld}%')
        path_note = 'WinDivert ICS' if self._mitm_shaping_backend == 'windivert' else 'MITM'
        if not sched_tick:
            detail = ', '.join(parts) if parts else 'timers / gates (may be off this moment)'
            self.log(
                f'Advanced lag ON ({path_note}) — {detail} — for ' + str(device.get('ip', '')),
                UI_LOG_VICTIM_BLOCK_FG,
            )
        self._mitm_adv_sched_record(
            du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
        )
        self._start_mitm_adv_schedule()
        self._refresh_flow_toggle_ui()
        self._refresh_advanced_lag_mitm_if_visible()


    def _await_mitm_teardown_thread(self, timeout_s=8.0):
        """Advanced lag OFF runs sniffer teardown off-thread; wait before starting shaping again."""
        t = getattr(self, '_mitm_teardown_thread', None)
        if t is None or not t.is_alive():
            return
        # Avoid threading.Thread.join on the GUI thread — it freezes Qt for up to timeout_s.
        deadline_ms = int(float(timeout_s) * 1000)
        timer = QTimer(self)
        timer.setInterval(25)
        loop = QEventLoop(self)
        el = QElapsedTimer()
        el.start()

        def tick():
            if not t.is_alive() or el.elapsed() >= deadline_ms:
                timer.stop()
                loop.quit()

        timer.timeout.connect(tick)
        timer.start()
        tick()
        loop.exec_()


    def _on_mitm_teardown_finished(self, prev_mac: str, log: bool, log_ip: str, was_windivert: bool, victim_snap):
        self._mitm_teardown_thread = None
        mac = prev_mac or None
        if was_windivert and not self._ics_windivert_busy(mac):
            self._stop_ics_lag_gate()
        if isinstance(victim_snap, dict):
            self._set_killed_profile(victim_snap, False)
        elif mac:
            self._set_killed_profile({'mac': mac, 'ip': log_ip or ''}, False)
        self._sync_killed_devices()
        self._write_remembered_killed_macs()
        if (
            mac
            and isinstance(victim_snap, dict)
            and not was_windivert
        ):
            try:
                mseq = self._bump_flow_off_intent('mitmshape', mac)
                self._schedule_flow_off_reinforce('mitmshape', mac, mseq, 25, victim_snap)
                self._schedule_flow_off_reinforce('mitmshape', mac, mseq, 90, victim_snap)
                self._schedule_flow_off_reinforce('mitmshape', mac, mseq, 200, victim_snap)
            except Exception:
                pass
        self._updateKillButtonState()
        self._refresh_flow_toggle_ui()
        self._refresh_advanced_lag_mitm_if_visible()
        if not log:
            return
        if was_windivert:
            if log_ip:
                self.log(f'MITM shaping OFF for {log_ip} (WinDivert ICS)', UI_LOG_RESTORE_FG)
            elif mac:
                self.log('Advanced lag shaping stopped (WinDivert ICS).', UI_LOG_RESTORE_FG)
        elif log_ip:
            self.log('MITM shaping OFF for ' + str(log_ip), UI_LOG_RESTORE_FG)
        elif mac:
            self.log('Advanced lag shaping stopped (device no longer in list).', UI_LOG_RESTORE_FG)


    def _halt_mitm_shaping_traffic_now(
        self,
        prev_mac: str | None,
        backend: str | None,
        victim_snap: dict | None,
        *,
        wd_gate,
    ) -> bool:
        """
        Stop delay/jitter/loss and ARP MITM on the caller thread.

        Advanced Lag master toggle OFF must not wait on a daemon thread — the UI
        already shows Off while the forwarder/WinDivert gate was still shaping.
        Returns True when WinDivert still needs async gate.stop().
        """
        was_wd = backend == 'windivert' and wd_gate is not None
        if was_wd:
            try:
                wd_gate.clear_shaping()
                if hasattr(wd_gate, 'clear_blocking_pause'):
                    wd_gate.clear_blocking_pause()
                elif hasattr(wd_gate, 'set_blocking'):
                    wd_gate.set_blocking(False)
            except Exception:
                pass
            return True

        mac = str(prev_mac or '').strip()
        victim = dict(victim_snap) if isinstance(victim_snap, dict) else None
        if victim is None and mac:
            key = self._killer_mac_key(mac)
            killed = getattr(self.killer, 'killed', {}) or {}
            if key and key in killed:
                victim = dict(killed[key])
            elif mac in killed:
                victim = dict(killed[mac])

        if mac:
            key = self._killer_mac_key(mac) or mac
            try:
                self.killer.disable_percent_cut(key)
            except Exception:
                pass
            try:
                self.killer._stop_forwarder(key)
            except Exception:
                pass

        if isinstance(victim, dict):
            try:
                unblock_ip(victim.get('ip') or '')
            except Exception:
                pass
            try:
                self.killer.unkill(victim)
            except Exception:
                pass
        return False


    def _revert_mitm_shaping_ui_if_no_backend(self) -> None:
        """Drop optimistic Advanced Lag ON when arm failed before any backend started."""
        if getattr(self, '_mitm_shaping_backend', None):
            return
        if getattr(self, '_ics_windivert_shaper', None) is not None:
            return
        if not self.mitm_shaping_active:
            return
        self.mitm_shaping_active = False
        self.mitm_shaping_mac = None
        self.mitm_shaping_device_ip = None
        self._refresh_advanced_lag_mitm_if_visible()


    def stop_mitm_shaping(self, log=True):
        if not self.mitm_shaping_active:
            return
        self._stop_mitm_adv_schedule()
        self._mitm_adv_row_t0 = {}
        prev_mac = self.mitm_shaping_mac
        backend = getattr(self, '_mitm_shaping_backend', None)
        shaper = getattr(self, '_ics_windivert_shaper', None)

        victim = self._victim_record_for_mac(prev_mac) or self._get_device_by_mac(prev_mac)
        if victim is None and prev_mac:
            victim = (getattr(self.killer, 'killed', None) or {}).get(prev_mac)
        victim_snap = dict(victim) if isinstance(victim, dict) else None

        was_wd = backend == 'windivert' and shaper is not None
        gate = getattr(self, '_ics_lag_gate', None) if was_wd else None
        need_async_wd_stop = self._halt_mitm_shaping_traffic_now(
            prev_mac,
            backend,
            victim_snap,
            wd_gate=gate,
        )

        if isinstance(victim_snap, dict):
            self._set_killed_profile(victim_snap, False)
        elif prev_mac:
            self._set_killed_profile({'mac': prev_mac, 'ip': ''}, False)

        self.mitm_shaping_active = False
        self.mitm_shaping_mac = None
        self.mitm_shaping_device_ip = None
        self._mitm_shaping_backend = None
        self._ics_windivert_shaper = None

        self._sync_killed_devices()
        self._write_remembered_killed_macs()
        self._updateKillButtonState()
        self._refresh_flow_toggle_ui()
        self._refresh_advanced_lag_mitm_if_visible()

        def _teardown_worker():
            log_ip = ''
            try:
                if need_async_wd_stop and gate is not None:
                    try:
                        gate.prepare_stop()
                    except Exception:
                        pass
                    if isinstance(victim_snap, dict):
                        log_ip = str(victim_snap.get('ip') or '')
                elif isinstance(victim_snap, dict):
                    try:
                        self.killer.reinforce_restore(victim_snap)
                    except Exception:
                        pass
                    log_ip = str(victim_snap.get('ip') or '')
            finally:
                try:
                    self.mitm_teardown_finished.emit(
                        str(prev_mac or ''),
                        bool(log),
                        log_ip,
                        bool(need_async_wd_stop),
                        victim_snap,
                    )
                except Exception:
                    pass

        t = threading.Thread(
            target=safe_daemon_target(_teardown_worker),
            daemon=True,
            name='mitm-stop-teardown',
        )
        self._mitm_teardown_thread = t
        t.start()


    def _reconcile_idle_mitm_state(self, *, quiet: bool = True) -> None:
        """Drop ghost Kill UI and orphan MITM left behind when flows ended without cleanup."""
        self._sync_killed_devices()
        flows_busy = (
            self.lag_active
            or self.dupe_active
            or self.mitm_shaping_active
            or self.percent_cut_active
        )
        if not flows_busy:
            cleared = False
            for mac in list(getattr(self.killer, 'killed', {}).keys()):
                if self._kill_toggle_pending_for_mac(mac):
                    continue
                if self._any_explicit_kill_profile_for_mac(mac):
                    continue
                victim = self._victim_record_for_mac(mac) or {'mac': mac}
                try:
                    self.killer.unkill(victim)
                    self.killer.reinforce_restore(victim)
                    cleared = True
                except Exception:
                    pass
            for mac, fw in list(getattr(self.killer, 'forwarders', {}).items()):
                if mac in getattr(self.killer, 'killed', {}):
                    continue
                if fw is not None and getattr(fw, 'running', False):
                    until = 0.0
                    try:
                        until = float(
                            (getattr(self.killer, '_restore_pass_until', None) or {}).get(
                                mac, 0
                            )
                            or 0
                        )
                    except Exception:
                        until = 0.0
                    pass_all = False
                    try:
                        from networking.killer import _forwarder_is_pass_all

                        pass_all = _forwarder_is_pass_all(fw)
                    except Exception:
                        pass_all = False
                    if pass_all and until and time.monotonic() < until:
                        continue
                    try:
                        self.killer.disable_percent_cut(mac)
                    except Exception:
                        pass
                    cleared = True
            if cleared and not quiet:
                self.log('Cleared stale network cut after idle.', UI_LOG_RESTORE_FG)
        self._updateKillButtonState()
