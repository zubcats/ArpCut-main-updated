"""Advanced Lag Settings — extra lag-related options (placeholder for upcoming features).

Builds that include MITM forwarder controls show ``Latency (delay)`` and ``Bandwidth cap``
sections with per-section on/off toggles (immediate apply) and a master victim toggle that
starts or stops shaping without changing which sections stay enabled. ``Clumsy only`` covers ICS / WinDivert notes + status.
"""

from __future__ import annotations

import sys

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QWidget,
    QLabel,
    QDialogButtonBox,
    QPushButton,
    QGroupBox,
    QScrollArea,
    QFormLayout,
    QSpinBox,
    QDoubleSpinBox,
    QHBoxLayout,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from constants import ADMIN_DEVICE_TABLE_ROW_BG
from tools.frameless_chrome import FramelessResizableMixin, CustomTitleBar
from tools.utils_gui import register_window_surface_effects, get_settings, set_settings


def _mitm_sections_enabled() -> bool:
    from tools.updater_core import is_experimental_build

    return is_experimental_build()


def _settings_bool(key: str, default: bool = True) -> bool:
    try:
        v = get_settings(key)
    except Exception:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ('0', 'false', 'no', ''):
        return False
    if s in ('1', 'true', 'yes'):
        return True
    return default


def _section_font(box: QGroupBox) -> None:
    font = QFont(box.font())
    font.setPointSize(10)
    box.setFont(font)


def _stub_section(title: str, parent: QWidget) -> QGroupBox:
    """Placeholder group for sections without custom UI yet."""
    box = QGroupBox(title, parent)
    _section_font(box)
    inner = QVBoxLayout(box)
    inner.setContentsMargins(12, 10, 12, 12)
    inner.setSpacing(6)
    stub = QLabel('Controls for this section will be added here.', box)
    stub.setWordWrap(True)
    stub.setStyleSheet('color: #9a9a9a; font-size: 11px;')
    inner.addWidget(stub)
    return box


class AdvancedLagSettingsDialog(FramelessResizableMixin, QDialog):
    """Non-modal panel opened from the main flow toggles (right-click → Advanced Lag Settings)."""

    _CLUMSY_ONLY_TITLE = 'Clumsy only'

    def __init__(self, parent=None):
        super().__init__(parent)
        # Same QSS object name as Lag Switch / Dupe panels (shared chrome in utils_gui).
        self.setObjectName('zubcutLagDupeDialog')
        self.elmocut = parent
        self._lbl_clumsy_status: QLabel | None = None
        self._lbl_mitm_status: QLabel | None = None
        self._mitm_sync_guard = False
        self._tog_victim_all: QPushButton | None = None
        self._tog_delay_enable: QPushButton | None = None
        self._tog_cap_enable: QPushButton | None = None
        self._spin_delay_up: QSpinBox | None = None
        self._spin_delay_down: QSpinBox | None = None
        self._spin_cap_up: QDoubleSpinBox | None = None
        self._spin_cap_down: QDoubleSpinBox | None = None
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowTitle('Advanced Lag Settings')
        self.setModal(False)
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self.resize(600, 580)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        win_icon = parent.icon if parent else None
        root.addWidget(
            CustomTitleBar(
                self,
                'Advanced Lag Settings',
                win_icon,
                maximizable=False,
                caption_accent=ADMIN_DEVICE_TABLE_ROW_BG,
            )
        )

        body = QWidget(self)
        body.setObjectName('zubcutDialogBody')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        scroll = QScrollArea(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_inner = QWidget(scroll)
        scroll_layout = QVBoxLayout(scroll_inner)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(10)

        scroll_layout.addWidget(_stub_section('More options', scroll_inner))
        if _mitm_sections_enabled():
            scroll_layout.addWidget(self._mitm_delay_section(scroll_inner))
            scroll_layout.addWidget(self._mitm_bandwidth_section(scroll_inner))
            scroll_layout.addWidget(self._mitm_stop_row(scroll_inner))
        scroll_layout.addWidget(self._clumsy_only_section(scroll_inner))

        scroll_layout.addStretch()
        scroll.setWidget(scroll_inner)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, body)
        buttons.rejected.connect(self.hide)
        layout.addWidget(buttons)

        root.addWidget(body, 1)
        for _pb in self.findChildren(QPushButton):
            _pb.setAutoDefault(False)
            _pb.setDefault(False)
        self._zubcut_use_translucent_surface = False
        register_window_surface_effects(self)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_clumsy_status()
        self._refresh_mitm_status()

    def _mitm_toggle(self, parent: QWidget, tooltip: str = '') -> QPushButton:
        btn = QPushButton(parent)
        btn.setObjectName('zubcutMitmToggle')
        btn.setCheckable(True)
        btn.setAutoDefault(False)
        btn.setDefault(False)
        btn.setFixedHeight(28)
        btn.setMinimumWidth(56)
        if tooltip:
            btn.setToolTip(tooltip)

        def _sync_text(checked: bool) -> None:
            btn.setText('On' if checked else 'Off')

        btn.toggled.connect(_sync_text)
        _sync_text(btn.isChecked())
        return btn

    def _set_toggle_state(self, btn: QPushButton | None, checked: bool) -> None:
        if btn is None:
            return
        btn.blockSignals(True)
        btn.setChecked(checked)
        btn.setText('On' if checked else 'Off')
        btn.blockSignals(False)

    def _persist_mitm_ui(self) -> None:
        if self._spin_delay_up is None or self._tog_delay_enable is None:
            return
        try:
            set_settings('mitm_delay_up_ms', int(self._spin_delay_up.value()))
            set_settings('mitm_delay_down_ms', int(self._spin_delay_down.value()))
            set_settings('mitm_cap_up_mbps', float(self._spin_cap_up.value()))
            set_settings('mitm_cap_down_mbps', float(self._spin_cap_down.value()))
            set_settings('mitm_delay_enabled', bool(self._tog_delay_enable.isChecked()))
            set_settings('mitm_cap_enabled', bool(self._tog_cap_enable.isChecked()))
        except Exception:
            pass

    def _mitm_effective_params(self) -> tuple[int, int, float, float]:
        """Resolve enabled sections into values passed to the main window (Mbps for caps)."""
        du = int(self._spin_delay_up.value()) if self._tog_delay_enable.isChecked() else 0
        dd = int(self._spin_delay_down.value()) if self._tog_delay_enable.isChecked() else 0
        cu = float(self._spin_cap_up.value()) if self._tog_cap_enable.isChecked() else 0.0
        cd = float(self._spin_cap_down.value()) if self._tog_cap_enable.isChecked() else 0.0
        return du, dd, cu, cd

    def _sync_victim_master_toggle(self) -> None:
        """Keep the victim-wide toggle aligned with whether shaping is actually running."""
        if self._tog_victim_all is None:
            return
        main = self.elmocut
        active = main is not None and bool(getattr(main, 'mitm_shaping_active', False))
        self._tog_victim_all.blockSignals(True)
        self._tog_victim_all.setChecked(active)
        self._tog_victim_all.setText('On' if active else 'Off')
        self._tog_victim_all.blockSignals(False)

    def _refresh_mitm_status(self) -> None:
        self._sync_victim_master_toggle()
        if self._lbl_mitm_status is None:
            return
        main = self.elmocut
        if main is None or not getattr(main, 'mitm_shaping_active', False):
            self._lbl_mitm_status.setText('')
            self._lbl_mitm_status.setVisible(False)
            return
        mac = getattr(main, 'mitm_shaping_mac', None) or ''
        self._lbl_mitm_status.setVisible(True)
        self._lbl_mitm_status.setText(
            f'Shaping is active (victim MAC {mac}). Turn the victim toggle off, use Stop, or turn Kill OFF.'
        )
        self._lbl_mitm_status.setStyleSheet('color: #8fbcbb; font-size: 11px;')

    def _log(self, msg: str, color: str = 'red') -> None:
        main = self.elmocut
        if main is not None and hasattr(main, 'log'):
            try:
                main.log(msg, color)
            except Exception:
                pass

    def _apply_or_stop_from_toggles(self) -> None:
        """Push merged latency + bandwidth from current toggles; stop shaping if nothing is active."""
        main = self.elmocut
        if main is None:
            return
        self._persist_mitm_ui()
        du, dd, cu, cd = self._mitm_effective_params()
        if du <= 0 and dd <= 0 and cu <= 0 and cd <= 0:
            if getattr(main, 'mitm_shaping_active', False):
                main.stop_mitm_shaping(log=True)
            self._refresh_mitm_status()
            return
        main.start_mitm_shaping_from_advanced(du, dd, cu, cd)
        self._refresh_mitm_status()

    def _on_section_delay_toggled(self, checked: bool) -> None:
        if self._mitm_sync_guard:
            return
        self._persist_mitm_ui()
        if checked:
            du = int(self._spin_delay_up.value()) if self._spin_delay_up else 0
            dd = int(self._spin_delay_down.value()) if self._spin_delay_down else 0
            if du <= 0 and dd <= 0:
                self._log('Set a non-zero upload or download delay before turning delay shaping on.', 'red')
                self._set_toggle_state(self._tog_delay_enable, False)
                self._sync_delay_widgets_enabled()
                return
        self._apply_or_stop_from_toggles()

    def _on_section_cap_toggled(self, checked: bool) -> None:
        if self._mitm_sync_guard:
            return
        self._persist_mitm_ui()
        if checked:
            cu = float(self._spin_cap_up.value()) if self._spin_cap_up else 0.0
            cd = float(self._spin_cap_down.value()) if self._spin_cap_down else 0.0
            if cu <= 0 and cd <= 0:
                self._log(
                    'Set a non-zero upload or download cap (Mbps) before turning bandwidth cap on.',
                    'red',
                )
                self._set_toggle_state(self._tog_cap_enable, False)
                self._sync_cap_widgets_enabled()
                return
        self._apply_or_stop_from_toggles()

    def _on_mitm_spins_changed(self) -> None:
        """While shaping is running, live-update parameters when spins change."""
        if self._mitm_sync_guard:
            return
        main = self.elmocut
        if main is None or not getattr(main, 'mitm_shaping_active', False):
            self._persist_mitm_ui()
            return
        self._apply_or_stop_from_toggles()

    def _on_victim_shaping_toggled(self, checked: bool) -> None:
        """Master: on applies whatever sections are already enabled; off stops shaping only (sections unchanged)."""
        main = self.elmocut
        if main is None or self._mitm_sync_guard:
            return
        if checked:
            self._persist_mitm_ui()
            du, dd, cu, cd = self._mitm_effective_params()
            if du <= 0 and dd <= 0 and cu <= 0 and cd <= 0:
                self._log(
                    'Turn on at least one section with non-zero delay or cap, then turn the victim toggle on.',
                    'red',
                )
                self._set_toggle_state(self._tog_victim_all, False)
                return
            main.start_mitm_shaping_from_advanced(du, dd, cu, cd)
        else:
            main.stop_mitm_shaping(log=True)
        self._refresh_mitm_status()

    def _on_mitm_stop(self) -> None:
        main = self.elmocut
        if main is None:
            return
        main.stop_mitm_shaping(log=True)
        self._refresh_mitm_status()

    def _sync_delay_widgets_enabled(self) -> None:
        if self._tog_delay_enable is None:
            return
        on = self._tog_delay_enable.isChecked()
        for w in (self._spin_delay_up, self._spin_delay_down):
            if w is not None:
                w.setEnabled(on)

    def _sync_cap_widgets_enabled(self) -> None:
        if self._tog_cap_enable is None:
            return
        on = self._tog_cap_enable.isChecked()
        for w in (self._spin_cap_up, self._spin_cap_down):
            if w is not None:
                w.setEnabled(on)

    def _mitm_delay_section(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox('Latency (delay)', parent)
        _section_font(box)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(8)

        intro = QLabel(
            'Queue packets for a fixed time before forwarding (same ARP MITM path as Percent Cut). '
            'Select a victim on your LAN; traffic must pass through this PC. Heavy load or long '
            'delays can backlog or drop packets.',
            box,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet('color: #c5c5c5; font-size: 11px;')
        inner.addWidget(intro)

        row_en = QHBoxLayout()
        lbl_en = QLabel('Delay shaping', box)
        lbl_en.setStyleSheet('color: #e8eaed;')
        self._tog_delay_enable = self._mitm_toggle(
            box,
            'When off, delay is not applied; bandwidth cap may still run.',
        )
        self._set_toggle_state(self._tog_delay_enable, _settings_bool('mitm_delay_enabled', True))
        self._tog_delay_enable.toggled.connect(self._sync_delay_widgets_enabled)
        self._tog_delay_enable.toggled.connect(self._on_section_delay_toggled)
        row_en.addWidget(lbl_en)
        row_en.addStretch()
        row_en.addWidget(self._tog_delay_enable)
        inner.addLayout(row_en)

        form = QFormLayout()
        form.setSpacing(8)
        self._spin_delay_up = QSpinBox(box)
        self._spin_delay_up.setRange(0, 800)
        self._spin_delay_up.setSuffix(' ms')
        self._spin_delay_up.setValue(int(get_settings('mitm_delay_up_ms') or 0))
        self._spin_delay_up.setToolTip('Extra delay before forwarding victim → router traffic (0 = off).')
        self._spin_delay_up.valueChanged.connect(lambda _v: self._on_mitm_spins_changed())
        form.addRow('Upload (out)', self._spin_delay_up)

        self._spin_delay_down = QSpinBox(box)
        self._spin_delay_down.setRange(0, 800)
        self._spin_delay_down.setSuffix(' ms')
        self._spin_delay_down.setValue(int(get_settings('mitm_delay_down_ms') or 0))
        self._spin_delay_down.setToolTip('Extra delay before forwarding router → victim traffic (0 = off).')
        self._spin_delay_down.valueChanged.connect(lambda _v: self._on_mitm_spins_changed())
        form.addRow('Download (in)', self._spin_delay_down)

        inner.addLayout(form)

        self._sync_delay_widgets_enabled()
        return box

    def _mitm_bandwidth_section(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox('Bandwidth cap', parent)
        _section_font(box)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(8)

        intro = QLabel(
            'Token-bucket rate limits per direction: traffic over the cap is dropped. '
            '0 Mbps means unlimited for that direction. Uses the same forwarder path as above.',
            box,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet('color: #c5c5c5; font-size: 11px;')
        inner.addWidget(intro)

        row_en = QHBoxLayout()
        lbl_en = QLabel('Bandwidth cap', box)
        lbl_en.setStyleSheet('color: #e8eaed;')
        self._tog_cap_enable = self._mitm_toggle(
            box,
            'When off, caps are not applied; delay shaping may still run.',
        )
        self._set_toggle_state(self._tog_cap_enable, _settings_bool('mitm_cap_enabled', True))
        self._tog_cap_enable.toggled.connect(self._sync_cap_widgets_enabled)
        self._tog_cap_enable.toggled.connect(self._on_section_cap_toggled)
        row_en.addWidget(lbl_en)
        row_en.addStretch()
        row_en.addWidget(self._tog_cap_enable)
        inner.addLayout(row_en)

        form = QFormLayout()
        form.setSpacing(8)
        self._spin_cap_up = QDoubleSpinBox(box)
        self._spin_cap_up.setRange(0.0, 10_000.0)
        self._spin_cap_up.setDecimals(2)
        self._spin_cap_up.setSingleStep(0.5)
        self._spin_cap_up.setSuffix(' Mbps')
        self._spin_cap_up.setValue(float(get_settings('mitm_cap_up_mbps') or 0.0))
        self._spin_cap_up.setToolTip('0 = unlimited. Drops packets over this approximate rate (upload).')
        self._spin_cap_up.valueChanged.connect(lambda _v: self._on_mitm_spins_changed())
        form.addRow('Upload cap', self._spin_cap_up)

        self._spin_cap_down = QDoubleSpinBox(box)
        self._spin_cap_down.setRange(0.0, 10_000.0)
        self._spin_cap_down.setDecimals(2)
        self._spin_cap_down.setSingleStep(0.5)
        self._spin_cap_down.setSuffix(' Mbps')
        self._spin_cap_down.setValue(float(get_settings('mitm_cap_down_mbps') or 0.0))
        self._spin_cap_down.setToolTip('0 = unlimited. Drops packets over this approximate rate (download).')
        self._spin_cap_down.valueChanged.connect(lambda _v: self._on_mitm_spins_changed())
        form.addRow('Download cap', self._spin_cap_down)

        inner.addLayout(form)

        self._sync_cap_widgets_enabled()
        return box

    def _mitm_stop_row(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox('Selected victim', parent)
        _section_font(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        row_v = QHBoxLayout()
        lbl_v = QLabel('All shaping for victim', box)
        lbl_v.setStyleSheet('color: #e8eaed;')
        self._tog_victim_all = self._mitm_toggle(
            box,
            'On: applies every section that is already turned on (delay and/or cap) to the selected device. '
            'Off: stops shaping only; section toggles stay as you left them.',
        )
        self._set_toggle_state(self._tog_victim_all, False)
        self._tog_victim_all.toggled.connect(self._on_victim_shaping_toggled)
        row_v.addWidget(lbl_v)
        row_v.addStretch()
        row_v.addWidget(self._tog_victim_all)
        lay.addLayout(row_v)

        hint = QLabel(
            'Per-section toggles choose delay and/or cap. The victim toggle starts or stops shaping for the '
            'selected device without changing which sections stay on.',
            box,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #9a9a9a; font-size: 11px;')
        lay.addWidget(hint)

        row = QHBoxLayout()
        btn_stop = QPushButton('Stop shaping', box)
        btn_stop.setToolTip(
            'Stops MITM shaping for the victim. Section toggles are unchanged (same idea as turning the victim toggle off).'
        )
        btn_stop.clicked.connect(self._on_mitm_stop)
        row.addWidget(btn_stop)
        row.addStretch()
        lay.addLayout(row)

        self._lbl_mitm_status = QLabel(box)
        self._lbl_mitm_status.setWordWrap(True)
        self._lbl_mitm_status.setVisible(False)
        lay.addWidget(self._lbl_mitm_status)

        btn_stop.setAutoDefault(False)
        btn_stop.setDefault(False)
        self._tog_victim_all.setAutoDefault(False)

        return box

    def _refresh_clumsy_status(self):
        if self._lbl_clumsy_status is None:
            return
        if not sys.platform.startswith('win'):
            self._lbl_clumsy_status.setText('Clumsy mode is only available on Windows.')
            self._lbl_clumsy_status.setStyleSheet('color: #9a9a9a; font-size: 11px;')
            return
        try:
            from tools.clumsy_inline import (
                clumsy_bundle_offered,
                clumsy_mode_enabled,
                clumsy_runtime_ready,
                windivert_driver_installed,
            )
        except Exception:
            self._lbl_clumsy_status.setText('Could not read Clumsy status.')
            self._lbl_clumsy_status.setStyleSheet('color: #c9a227; font-size: 11px;')
            return
        mode = clumsy_mode_enabled()
        bundle = clumsy_bundle_offered()
        driver = windivert_driver_installed()
        ready = clumsy_runtime_ready()
        lines = [
            f'Clumsy mode (Settings): {"on" if mode else "off"}',
            f'WinDivert driver: {"present" if driver else "missing"}',
        ]
        if getattr(sys, 'frozen', False):
            lines.append(f'Portable clumsy bundle flag: {"yes" if bundle else "no"}')
        lines.append(f'Ready for inline ICS row: {"yes" if ready and mode else "no"}')
        self._lbl_clumsy_status.setText('\n'.join(lines))
        if mode and ready:
            self._lbl_clumsy_status.setStyleSheet('color: #8fbcbb; font-size: 11px;')
        elif mode and not ready:
            self._lbl_clumsy_status.setStyleSheet('color: #c9a227; font-size: 11px;')
        else:
            self._lbl_clumsy_status.setStyleSheet('color: #9a9a9a; font-size: 11px;')

    def _clumsy_only_section(self, parent: QWidget) -> QGroupBox:
        """WinDivert / ICS shared-client path — not the normal ARP + firewall lag switch."""
        box = QGroupBox(self._CLUMSY_ONLY_TITLE, parent)
        _section_font(box)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(8)

        intro = QLabel(
            'These controls apply only when Clumsy mode is enabled in Settings (Windows ICS / '
            'shared clients and the inline device row). They do not change the standard '
            'Lag Switch, which uses ARP and the firewall on the normal adapter path.',
            box,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet('color: #c5c5c5; font-size: 11px;')
        inner.addWidget(intro)

        if _mitm_sections_enabled():
            ics_note = QLabel(
                'On ICS shared clients or when ARP MITM is unreliable, use external clumsy + WinDivert '
                'for predictable delay and rate limits. The Latency and Bandwidth sections above use '
                'the in-app forwarder when traffic crosses this PC.',
                box,
            )
        else:
            ics_note = QLabel(
                'On ICS shared clients or when ARP MITM is unreliable, use external clumsy + WinDivert '
                'for predictable delay and rate limits.',
                box,
            )
        ics_note.setWordWrap(True)
        ics_note.setStyleSheet('color: #9a9a9a; font-size: 11px;')
        inner.addWidget(ics_note)

        self._lbl_clumsy_status = QLabel(box)
        self._lbl_clumsy_status.setWordWrap(True)
        inner.addWidget(self._lbl_clumsy_status)

        stub = QLabel(
            'WinDivert impairment presets (delay, loss, cap, etc.) will be added here.',
            box,
        )
        stub.setWordWrap(True)
        stub.setStyleSheet('color: #9a9a9a; font-size: 11px;')
        inner.addWidget(stub)
        return box
