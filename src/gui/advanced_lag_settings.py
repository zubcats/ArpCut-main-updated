"""Advanced Lag Settings — extra lag-related options (placeholder for upcoming features).

Section titles: ``More options`` (stub), optional ``Latency & bandwidth (MITM, experimental)`` when
the build is experimental, and ``Clumsy only`` (ICS / WinDivert notes + status).
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
    QHBoxLayout,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from constants import ADMIN_DEVICE_TABLE_ROW_BG
from tools.frameless_chrome import FramelessResizableMixin, CustomTitleBar
from tools.utils_gui import register_window_surface_effects, get_settings, set_settings

MITM_SHAPING_SECTION_TITLE = 'Latency & bandwidth (MITM, experimental)'


def _section_titles() -> tuple[str, ...]:
    from tools.updater_core import is_experimental_build

    t: list[str] = ['More options']
    if is_experimental_build():
        t.append(MITM_SHAPING_SECTION_TITLE)
    t.append('Clumsy only')
    return tuple(t)


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
        self._spin_delay_up: QSpinBox | None = None
        self._spin_delay_down: QSpinBox | None = None
        self._spin_cap_up: QSpinBox | None = None
        self._spin_cap_down: QSpinBox | None = None
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowTitle('Advanced Lag Settings')
        self.setModal(False)
        self.setMinimumWidth(400)
        self.setMinimumHeight(320)

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

        self._section_groups = []
        for title in _section_titles():
            if title == self._CLUMSY_ONLY_TITLE:
                grp = self._clumsy_only_section(scroll_inner)
            elif title == MITM_SHAPING_SECTION_TITLE:
                grp = self._mitm_shaping_section(scroll_inner)
            else:
                grp = _stub_section(title, scroll_inner)
            self._section_groups.append(grp)
            scroll_layout.addWidget(grp)

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

    def _persist_mitm_spins(self) -> None:
        if self._spin_delay_up is None:
            return
        try:
            set_settings('mitm_delay_up_ms', int(self._spin_delay_up.value()))
            set_settings('mitm_delay_down_ms', int(self._spin_delay_down.value()))
            set_settings('mitm_cap_up_kbps', int(self._spin_cap_up.value()))
            set_settings('mitm_cap_down_kbps', int(self._spin_cap_down.value()))
        except Exception:
            pass

    def _refresh_mitm_status(self) -> None:
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
            f'Shaping is active (victim MAC {mac}). Use Stop below or turn Kill OFF for that device.'
        )
        self._lbl_mitm_status.setStyleSheet('color: #8fbcbb; font-size: 11px;')

    def _on_mitm_apply(self) -> None:
        main = self.elmocut
        if main is None:
            return
        self._persist_mitm_spins()
        main.start_mitm_shaping_from_advanced(
            int(self._spin_delay_up.value()),
            int(self._spin_delay_down.value()),
            float(self._spin_cap_up.value()),
            float(self._spin_cap_down.value()),
        )
        self._refresh_mitm_status()

    def _on_mitm_stop(self) -> None:
        main = self.elmocut
        if main is None:
            return
        main.stop_mitm_shaping(log=True)
        self._refresh_mitm_status()

    def _mitm_shaping_section(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox(MITM_SHAPING_SECTION_TITLE, parent)
        _section_font(box)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(8)

        intro = QLabel(
            'Adds queued delay and/or token-bucket bandwidth caps on the same ARP MITM forwarder '
            'path as Percent Cut. Requires a selected victim on your LAN; traffic must flow through '
            'this PC. High traffic + long delay can backlog or drop packets (experimental).',
            box,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet('color: #c5c5c5; font-size: 11px;')
        inner.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)
        self._spin_delay_up = QSpinBox(box)
        self._spin_delay_up.setRange(0, 800)
        self._spin_delay_up.setSuffix(' ms')
        self._spin_delay_up.setValue(int(get_settings('mitm_delay_up_ms') or 0))
        self._spin_delay_up.setToolTip('Extra delay before forwarding victim → router traffic (0 = off).')
        form.addRow('Delay upload (out)', self._spin_delay_up)

        self._spin_delay_down = QSpinBox(box)
        self._spin_delay_down.setRange(0, 800)
        self._spin_delay_down.setSuffix(' ms')
        self._spin_delay_down.setValue(int(get_settings('mitm_delay_down_ms') or 0))
        self._spin_delay_down.setToolTip('Extra delay before forwarding router → victim traffic (0 = off).')
        form.addRow('Delay download (in)', self._spin_delay_down)

        self._spin_cap_up = QSpinBox(box)
        self._spin_cap_up.setRange(0, 1_000_000)
        self._spin_cap_up.setSuffix(' Kbps')
        self._spin_cap_up.setValue(int(get_settings('mitm_cap_up_kbps') or 0))
        self._spin_cap_up.setToolTip('0 = unlimited. Drops packets over this approximate rate (upload).')
        form.addRow('Cap upload', self._spin_cap_up)

        self._spin_cap_down = QSpinBox(box)
        self._spin_cap_down.setRange(0, 1_000_000)
        self._spin_cap_down.setSuffix(' Kbps')
        self._spin_cap_down.setValue(int(get_settings('mitm_cap_down_kbps') or 0))
        self._spin_cap_down.setToolTip('0 = unlimited. Drops packets over this approximate rate (download).')
        form.addRow('Cap download', self._spin_cap_down)

        inner.addLayout(form)

        row = QHBoxLayout()
        btn_apply = QPushButton('Apply shaping', box)
        btn_apply.clicked.connect(self._on_mitm_apply)
        btn_stop = QPushButton('Stop shaping', box)
        btn_stop.clicked.connect(self._on_mitm_stop)
        row.addWidget(btn_apply)
        row.addWidget(btn_stop)
        inner.addLayout(row)

        self._lbl_mitm_status = QLabel(box)
        self._lbl_mitm_status.setWordWrap(True)
        self._lbl_mitm_status.setVisible(False)
        inner.addWidget(self._lbl_mitm_status)

        for b in (btn_apply, btn_stop):
            b.setAutoDefault(False)
            b.setDefault(False)

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

        ics_note = QLabel(
            'Experimental-channel builds include a MITM forwarder latency/bandwidth section above '
            'when present. On ICS shared clients or when ARP MITM is unreliable, prefer external '
            'clumsy + WinDivert for predictable delay and rate limits.',
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
