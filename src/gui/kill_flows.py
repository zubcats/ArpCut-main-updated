"""Kill Flows monitor — live in/out rates while Kill is armed (charcoal/teal UI)."""
from __future__ import annotations

import threading
from typing import Any, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import constants as _zcut_constants
from constants import APP_DISPLAY_NAME
from networking.kill_flow_monitor import (
    KillFlowSniffer,
    KillFlowVerdict,
    classify_kill_flow_verdict,
    probe_lan_reachable,
)
from tools.crash_feedback import safe_daemon_target
from tools.frameless_chrome import FramelessResizableMixin, setup_frameless_main_window
from tools.utils_gui import register_window_surface_effects

_ADMIN_BG = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_BG', '#5D706E')
_SEL_BG = getattr(_zcut_constants, 'UI_TABLE_SELECTION_BG', '#316E69')
_VICTIM = getattr(_zcut_constants, 'UI_LOG_VICTIM_BLOCK_FG', '#32716D')
_MUTE = '#9a9a9a'
_TEXT = '#e8eaed'
_FAIL = '#c45c5c'
_WARN = '#d4a017'


def _fmt_bps(n: float) -> str:
    n = float(n or 0.0)
    if n < 1024:
        return f'{n:.0f} B/s'
    if n < 1024 * 1024:
        return f'{n / 1024:.1f} KB/s'
    return f'{n / (1024 * 1024):.2f} MB/s'


def _fmt_bytes(n: int) -> str:
    n = int(n or 0)
    if n < 1024:
        return f'{n} B'
    if n < 1024 * 1024:
        return f'{n / 1024:.1f} KB'
    return f'{n / (1024 * 1024):.2f} MB'


class KillFlowsWindow(FramelessResizableMixin, QMainWindow):
    """Auxiliary window: monitor selected victim while Kill is on."""

    lan_probe_done = pyqtSignal(object)  # Optional[bool]

    def __init__(self, parent, icon):
        super().__init__()
        self.parent = parent
        self.icon = icon
        self.setWindowIcon(icon)
        self.setObjectName('zubcutAuxiliaryWindow')
        self.setWindowTitle(f'{APP_DISPLAY_NAME} — Kill Flows')

        self._device: Optional[dict] = None
        self._sniffer = KillFlowSniffer()
        self._lan_reachable: Optional[bool] = None
        self._lan_probe_in_flight = False
        self._sniff_iface = ''
        self._want_sniff = False
        self._monitor_open = False
        self._session_had_kill = False
        self._state_dirty = False

        central = QWidget(self)
        central.setObjectName('centralwidget')
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        self.lbl_device = QLabel('No device', central)
        self.lbl_device.setObjectName('killFlowsDevice')
        self.lbl_device.setAlignment(Qt.AlignCenter)
        self.lbl_device.setStyleSheet(f'color: {_TEXT}; font-size: 13px;')
        root.addWidget(self.lbl_device)

        self.lbl_verdict = QLabel('Waiting for Kill', central)
        self.lbl_verdict.setObjectName('killFlowsVerdict')
        self.lbl_verdict.setAlignment(Qt.AlignCenter)
        self.lbl_verdict.setWordWrap(True)
        self.lbl_verdict.setStyleSheet(
            f'color: {_MUTE}; font-size: 15px; font-weight: 600; padding: 4px;'
        )
        root.addWidget(self.lbl_verdict)

        self.lbl_detail = QLabel('', central)
        self.lbl_detail.setObjectName('killFlowsDetail')
        self.lbl_detail.setAlignment(Qt.AlignCenter)
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setStyleSheet(f'color: {_MUTE}; font-size: 11px;')
        root.addWidget(self.lbl_detail)

        status = QFrame(central)
        status.setObjectName('killFlowsStatusRow')
        status.setStyleSheet(
            f'QFrame#killFlowsStatusRow {{ background: #141414; border: 1px solid #3d3d3d; '
            f'border-radius: 4px; }}'
        )
        # Table row selection uses UI_TABLE_SELECTION_BG via global aux QSS ({_SEL_BG}).
        _ = _SEL_BG
        status_l = QHBoxLayout(status)
        status_l.setContentsMargins(10, 8, 10, 8)
        status_l.setSpacing(16)

        self.lbl_lan = QLabel('LAN: —', status)
        self.lbl_mitm = QLabel('MITM: —', status)
        self.lbl_out = QLabel('Out: —', status)
        self.lbl_in = QLabel('In: —', status)
        for lab in (self.lbl_lan, self.lbl_mitm, self.lbl_out, self.lbl_in):
            lab.setStyleSheet(f'color: {_ADMIN_BG}; font-size: 12px;')
            status_l.addWidget(lab)
        status_l.addStretch(1)
        root.addWidget(status)

        self.lbl_hint = QLabel(
            'Out = device→internet attempts on this PC. In = internet→device (leak if high while Kill ON).',
            central,
        )
        self.lbl_hint.setObjectName('killFlowsHint')
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(f'color: {_MUTE}; font-size: 11px;')
        root.addWidget(self.lbl_hint)

        self.table = QTableWidget(central)
        self.table.setObjectName('killFlowsTable')
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ['Peer', 'Port', 'Proto', 'Out', 'In']
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        setup_frameless_main_window(self, self.windowTitle(), self.icon, maximizable=True)
        register_window_surface_effects(self)
        self.resize(720, 480)

        self.lan_probe_done.connect(self._on_lan_probe_done)

        self._timer = QTimer(self)
        # UI-only poll — never do sniffer join / arping on the Kill click path.
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_timer)

        self._lan_timer = QTimer(self)
        self._lan_timer.setInterval(4000)
        self._lan_timer.timeout.connect(self._schedule_lan_probe)

    def closeEvent(self, event):
        self._stop_monitoring()
        super().closeEvent(event)

    def open_for_device(self, device: dict) -> None:
        if not isinstance(device, dict) or device.get('admin'):
            return
        self._device = {
            'ip': str(device.get('ip') or '').strip(),
            'mac': str(device.get('mac') or '').strip(),
            'name': str(device.get('name') or ''),
            'vendor': str(device.get('vendor') or ''),
        }
        label = (
            self._device['name']
            if self._device['name'] and self._device['name'] != '-'
            else (self._device['vendor'] or self._device['ip'])
        )
        self.lbl_device.setText(f'{label}  ·  {self._device["ip"]}')
        self._lan_reachable = None
        self._session_had_kill = False
        # Reset prior session totals when (re)opening for a device.
        try:
            self._sniffer.stop(join=False)
        except Exception:
            pass
        self._monitor_open = True
        self._state_dirty = True
        if not self._timer.isActive():
            self._timer.start()
        if not self._lan_timer.isActive():
            self._lan_timer.start()
        self.show()
        self.setWindowState(Qt.WindowNoState)
        self.raise_()
        self.activateWindow()
        # Defer sniff/UI work to the timer — never block the opener / Kill click.
        self._schedule_lan_probe()
        QTimer.singleShot(0, self._on_timer)

    def notify_kill_state_changed(self) -> None:
        """Mark dirty only — never sniff/join/refresh on the Kill toggle stack."""
        if not self._monitor_open or not self._device:
            return
        self._state_dirty = True

    def _stop_monitoring(self) -> None:
        self._want_sniff = False
        self._monitor_open = False
        self._state_dirty = False
        try:
            self._timer.stop()
            self._lan_timer.stop()
        except Exception:
            pass
        try:
            self._sniffer.stop(join=False)
        except Exception:
            pass

    def _device_ip(self) -> str:
        return str((self._device or {}).get('ip') or '').strip()

    def _live_device(self) -> Optional[dict]:
        """Prefer the live scan-table row (profile keys match Kill bookkeeping)."""
        snap = self._device
        if not isinstance(snap, dict):
            return None
        app = self.parent
        ip = str(snap.get('ip') or '').strip()
        mac = str(snap.get('mac') or '').strip()
        try:
            devices = list(getattr(getattr(app, 'scanner', None), 'devices', None) or [])
        except Exception:
            devices = []
        for d in devices:
            if not isinstance(d, dict) or d.get('admin'):
                continue
            if ip and str(d.get('ip') or '').strip() == ip:
                return d
        for d in devices:
            if not isinstance(d, dict) or d.get('admin'):
                continue
            if mac and str(d.get('mac') or '').strip().lower() == mac.lower():
                return d
        return snap

    def _kill_on(self) -> bool:
        """True when Kill is intended ON or the cut backend is live for this device.

        Do not rely only on ``killed_devices`` — ``_sync_killed_devices`` can clear the
        profile for a beat before ``killer.killed`` is populated, which made this
        window flash "Waiting for Kill" during a real short Kill.
        """
        app = self.parent
        dev = self._live_device()
        if not app or not isinstance(dev, dict):
            return False
        mac = str(dev.get('mac') or '').strip()
        try:
            if callable(getattr(app, '_kill_toggle_pending_for_mac', None)):
                if app._kill_toggle_pending_for_mac(mac):
                    return True
        except Exception:
            pass
        try:
            if app._kill_ui_shows_on(mac, dev.get('ip'), dev):
                return True
        except Exception:
            pass
        try:
            if callable(getattr(app, '_any_explicit_kill_profile_for_mac', None)):
                if app._any_explicit_kill_profile_for_mac(mac):
                    return True
        except Exception:
            pass
        try:
            if callable(getattr(app, '_explicit_kill_backend_live', None)):
                if app._explicit_kill_backend_live(mac, dev):
                    return True
        except Exception:
            pass
        return self._mitm_armed()

    def _mitm_armed(self) -> bool:
        app = self.parent
        dev = self._live_device() or self._device or {}
        mac = str(dev.get('mac') or '').strip()
        if not app or not mac:
            return False
        try:
            if callable(getattr(app, '_killer_mac_key', None)):
                if app._killer_mac_key(mac):
                    return True
        except Exception:
            pass
        try:
            from tools.utils import good_mac

            mac_n = good_mac(mac)
            killed = getattr(getattr(app, 'killer', None), 'killed', None) or {}
            for key in killed:
                if good_mac(str(key)) == mac_n:
                    return True
            forwarders = getattr(getattr(app, 'killer', None), 'forwarders', None) or {}
            for key in forwarders:
                if good_mac(str(key)) == mac_n:
                    return True
            ics = getattr(app, '_ics_kill_profile_macs', None)
            if isinstance(ics, set) and (mac in ics or mac_n in ics):
                return True
        except Exception:
            pass
        return False

    def _ics_path(self) -> bool:
        app = self.parent
        dev = self._device
        if not app or not isinstance(dev, dict):
            return False
        try:
            if callable(getattr(app, '_is_ics_downstream', None)):
                if app._is_ics_downstream(dev):
                    return True
        except Exception:
            pass
        try:
            plan = app._impairment_plan_for(dev)
            return bool(
                getattr(plan, 'is_ics_downstream', False)
                or getattr(plan, 'use_windivert', False)
            )
        except Exception:
            return False

    def _capture_iface(self) -> str:
        app = self.parent
        iface = getattr(getattr(app, 'scanner', None), 'iface', None)
        if iface is None:
            return ''
        # Windows Npcap prefers GUID; name is a fallback.
        guid = str(getattr(iface, 'guid', None) or '').strip()
        name = str(getattr(iface, 'name', None) or '').strip()
        if guid and guid.upper() != 'NULL':
            return guid
        return name if name != 'NULL' else ''

    def _kill_pending(self) -> bool:
        app = self.parent
        dev = self._live_device() or self._device or {}
        mac = str(dev.get('mac') or '').strip()
        if not app or not mac:
            return False
        try:
            return bool(app._kill_toggle_pending_for_mac(mac))
        except Exception:
            return False

    def _sync_sniff_for_state(self) -> None:
        vip = self._device_ip()
        iface = self._capture_iface()
        kill_on = self._kill_on()
        if kill_on:
            self._session_had_kill = True
        want = bool(self._monitor_open and vip and kill_on and iface)
        self._want_sniff = want
        if not want:
            # Stop capture on Kill OFF but keep counters for "Kill ended" verdict.
            if self._sniffer.snapshot().get('running'):
                try:
                    self._sniffer.stop(join=False)
                except Exception:
                    pass
            self._sniff_iface = ''
            return
        if (
            self._sniffer.snapshot().get('running')
            and self._sniff_iface == iface
            and getattr(self._sniffer, '_victim_ip', '') == vip
        ):
            return
        self._sniff_iface = iface
        # No per-packet UI callback — timer refreshes only.
        self._sniffer.start(vip, iface, on_update=None)

    def _schedule_lan_probe(self) -> None:
        if not self._monitor_open or not self._device_ip():
            return
        if self._lan_probe_in_flight:
            return
        self._lan_probe_in_flight = True
        app = self.parent
        ip = self._device_ip()
        scanner = getattr(app, 'scanner', None)

        def _work() -> None:
            result: Optional[bool] = None
            try:
                # ARP cache only — never probe_ip/arping (fights MITM + merges table rows).
                result = probe_lan_reachable(scanner, ip)
            except Exception:
                result = None
            try:
                self.lan_probe_done.emit(result)
            except Exception:
                self._lan_probe_in_flight = False

        try:
            threading.Thread(
                target=safe_daemon_target(_work),
                name='zubcut-kill-flow-lan',
                daemon=True,
            ).start()
        except Exception:
            self._lan_probe_in_flight = False

    def _on_lan_probe_done(self, result) -> None:
        self._lan_probe_in_flight = False
        if isinstance(result, bool):
            self._lan_reachable = result
        # Don't rebuild UI from the probe thread's emit during Kill paint — timer will.

    def _on_timer(self) -> None:
        if not self._monitor_open:
            return
        self._state_dirty = False
        self._sync_sniff_for_state()
        self._refresh_ui()

    def _apply_verdict_style(self, verdict: KillFlowVerdict) -> None:
        color = {
            'ok': _VICTIM,
            'warn': _WARN,
            'fail': _FAIL,
            'idle': _MUTE,
        }.get(verdict.level, _MUTE)
        self.lbl_verdict.setText(verdict.label)
        self.lbl_verdict.setStyleSheet(
            f'color: {color}; font-size: 15px; font-weight: 600; padding: 4px;'
        )
        self.lbl_detail.setText(verdict.detail)

    def _refresh_ui(self) -> None:
        snap = self._sniffer.snapshot()
        kill_on = self._kill_on()
        if kill_on:
            self._session_had_kill = True
        mitm = self._mitm_armed()
        ics = self._ics_path()
        verdict = classify_kill_flow_verdict(
            kill_on=kill_on,
            lan_reachable=self._lan_reachable,
            mitm_armed=mitm,
            ics_path=ics,
            out_bps=float(snap.get('out_bps') or 0.0),
            in_bps=float(snap.get('in_bps') or 0.0),
            saw_any_packets=bool(snap.get('saw_any')),
            kill_pending=self._kill_pending(),
            out_bytes=int(snap.get('out_bytes') or 0),
            in_bytes=int(snap.get('in_bytes') or 0),
            session_had_kill=bool(self._session_had_kill),
        )
        self._apply_verdict_style(verdict)

        if self._lan_reachable is True:
            self.lbl_lan.setText('LAN: Reachable')
            self.lbl_lan.setStyleSheet(f'color: {_VICTIM}; font-size: 12px;')
        elif self._lan_reachable is False:
            self.lbl_lan.setText('LAN: Unreachable')
            self.lbl_lan.setStyleSheet(f'color: {_FAIL}; font-size: 12px;')
        else:
            self.lbl_lan.setText('LAN: …')
            self.lbl_lan.setStyleSheet(f'color: {_MUTE}; font-size: 12px;')

        if mitm or ics:
            path = 'Hotspot' if ics and not mitm else 'Armed'
            self.lbl_mitm.setText(f'MITM: {path}')
            self.lbl_mitm.setStyleSheet(f'color: {_VICTIM}; font-size: 12px;')
        elif kill_on:
            self.lbl_mitm.setText('MITM: Not armed')
            self.lbl_mitm.setStyleSheet(f'color: {_FAIL}; font-size: 12px;')
        else:
            self.lbl_mitm.setText('MITM: Idle')
            self.lbl_mitm.setStyleSheet(f'color: {_MUTE}; font-size: 12px;')

        out_bps = float(snap.get('out_bps') or 0.0)
        in_bps = float(snap.get('in_bps') or 0.0)
        self.lbl_out.setText(
            f'Out: {_fmt_bps(out_bps)}  ({_fmt_bytes(int(snap.get("out_bytes") or 0))})'
        )
        self.lbl_in.setText(
            f'In: {_fmt_bps(in_bps)}  ({_fmt_bytes(int(snap.get("in_bytes") or 0))})'
        )
        self.lbl_out.setStyleSheet(f'color: {_TEXT}; font-size: 12px;')
        in_color = _WARN if (kill_on and in_bps >= 1500) else _TEXT
        self.lbl_in.setStyleSheet(f'color: {in_color}; font-size: 12px;')

        if ics:
            self.lbl_hint.setText(
                'Hotspot/Clumsy path: rates are what Npcap sees on the selected adapter. '
                'Pair with Analysis if capture looks empty.'
            )
        else:
            self.lbl_hint.setText(
                'Out = device→internet on this PC. In = internet→device '
                '(high In while Kill ON means leak). Empty + LAN dead ≠ full cut.'
            )

        flows = list(snap.get('flows') or [])
        self.table.setRowCount(len(flows))
        for row, f in enumerate(flows):
            vals = [
                str(f.get('peer') or ''),
                str(f.get('port') or 0),
                str(f.get('proto') or ''),
                _fmt_bytes(int(f.get('out_bytes') or 0)),
                _fmt_bytes(int(f.get('in_bytes') or 0)),
            ]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
