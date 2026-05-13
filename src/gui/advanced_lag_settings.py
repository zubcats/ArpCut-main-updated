"""Advanced Lag Settings — clumsy-style rows + master victim toggle (experimental MITM path).

Each row: enable, In/Out, and values. Turning the victim toggle on applies every enabled row
to the selected device; off stops. ``Clumsy only`` covers ICS / WinDivert notes + status.
"""

from __future__ import annotations

import sys

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QVBoxLayout,
    QWidget,
    QLabel,
    QDialogButtonBox,
    QPushButton,
    QGroupBox,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QGridLayout,
    QSizePolicy,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from constants import ADMIN_DEVICE_TABLE_ROW_BG
from tools.frameless_chrome import FramelessResizableMixin, CustomTitleBar
from tools.utils_gui import register_window_surface_effects, get_settings, set_settings


def _mitm_sections_enabled() -> bool:
    from tools.updater_core import is_experimental_build

    return is_experimental_build()


def _section_font(box: QGroupBox) -> None:
    font = QFont(box.font())
    font.setPointSize(10)
    box.setFont(font)


def _bool_setting(key: str, default: bool = False) -> bool:
    try:
        v = get_settings(key)
    except KeyError:
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


def _int_setting(key: str, default: int = 0) -> int:
    try:
        return int(get_settings(key))
    except KeyError:
        return default
    except (TypeError, ValueError):
        return default


def _float_setting(key: str, default: float = 0.0) -> float:
    try:
        return float(get_settings(key))
    except KeyError:
        return default
    except (TypeError, ValueError):
        return default


def _stub_section(title: str, parent: QWidget) -> QGroupBox:
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
        super().__init__(None)
        self.setObjectName('zubcutLagDupeDialog')
        self.elmocut = parent
        self._lbl_clumsy_status: QLabel | None = None
        self._lbl_mitm_status: QLabel | None = None
        self._mitm_sync_guard = False
        self._tog_victim_all: QPushButton | None = None

        self._chk_adv_delay_on: QCheckBox | None = None
        self._chk_adv_delay_in: QCheckBox | None = None
        self._chk_adv_delay_out: QCheckBox | None = None
        self._spin_adv_delay_ms: QSpinBox | None = None

        self._chk_adv_jitter_on: QCheckBox | None = None
        self._chk_adv_jitter_in: QCheckBox | None = None
        self._chk_adv_jitter_out: QCheckBox | None = None
        self._spin_adv_jitter_ms: QSpinBox | None = None

        self._chk_adv_cap_on: QCheckBox | None = None
        self._chk_adv_cap_in: QCheckBox | None = None
        self._chk_adv_cap_out: QCheckBox | None = None
        self._spin_adv_cap_out_mbps: QDoubleSpinBox | None = None
        self._spin_adv_cap_in_mbps: QDoubleSpinBox | None = None

        self._chk_adv_loss_on: QCheckBox | None = None
        self._chk_adv_loss_in: QCheckBox | None = None
        self._chk_adv_loss_out: QCheckBox | None = None
        self._spin_adv_loss_pct: QSpinBox | None = None

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle('Advanced Lag Settings')
        self.setModal(False)
        self.setMinimumWidth(720)
        self.setMinimumHeight(520)
        self.resize(780, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        win_icon = parent.icon if parent else None
        if win_icon is not None and not win_icon.isNull():
            self.setWindowIcon(win_icon)
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
        scroll.setObjectName('zubcutAdvLagScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_inner = QWidget(scroll)
        scroll_inner.setObjectName('zubcutAdvLagScrollInner')
        scroll_layout = QVBoxLayout(scroll_inner)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(10)

        if _mitm_sections_enabled():
            scroll_layout.addWidget(self._mitm_impairments_section(scroll_inner))
            scroll_layout.addWidget(self._mitm_victim_section(scroll_inner))
        else:
            scroll_layout.addWidget(_stub_section('More options', scroll_inner))
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
        if self._chk_adv_delay_on is None:
            return
        try:
            set_settings('mitm_adv_delay_on', self._chk_adv_delay_on.isChecked())
            set_settings('mitm_adv_delay_in', self._chk_adv_delay_in.isChecked())
            set_settings('mitm_adv_delay_out', self._chk_adv_delay_out.isChecked())
            set_settings('mitm_adv_delay_ms', int(self._spin_adv_delay_ms.value()))
            set_settings('mitm_adv_jitter_on', self._chk_adv_jitter_on.isChecked())
            set_settings('mitm_adv_jitter_in', self._chk_adv_jitter_in.isChecked())
            set_settings('mitm_adv_jitter_out', self._chk_adv_jitter_out.isChecked())
            set_settings('mitm_adv_jitter_ms', int(self._spin_adv_jitter_ms.value()))
            set_settings('mitm_adv_cap_on', self._chk_adv_cap_on.isChecked())
            set_settings('mitm_adv_cap_in', self._chk_adv_cap_in.isChecked())
            set_settings('mitm_adv_cap_out', self._chk_adv_cap_out.isChecked())
            set_settings('mitm_adv_cap_out_mbps', float(self._spin_adv_cap_out_mbps.value()))
            set_settings('mitm_adv_cap_in_mbps', float(self._spin_adv_cap_in_mbps.value()))
            set_settings('mitm_adv_loss_on', self._chk_adv_loss_on.isChecked())
            set_settings('mitm_adv_loss_in', self._chk_adv_loss_in.isChecked())
            set_settings('mitm_adv_loss_out', self._chk_adv_loss_out.isChecked())
            set_settings('mitm_adv_loss_pct', int(self._spin_adv_loss_pct.value()))
            du, dd, ju, jd, cu, cd, lu, ld = self._mitm_effective_params()
            set_settings('mitm_delay_up_ms', du)
            set_settings('mitm_delay_down_ms', dd)
            set_settings('mitm_cap_up_mbps', cu)
            set_settings('mitm_cap_down_mbps', cd)
            set_settings(
                'mitm_delay_enabled',
                self._chk_adv_delay_on.isChecked() and (du > 0 or dd > 0),
            )
            set_settings(
                'mitm_cap_enabled',
                self._chk_adv_cap_on.isChecked() and (cu > 0.0 or cd > 0.0),
            )
        except Exception:
            pass

    def _mitm_effective_params(
        self,
    ) -> tuple[int, int, int, int, float, float, int, int]:
        """du, dd, ju, jd, cap_out_mbps, cap_in_mbps, loss_out_pct, loss_in_pct."""
        d_on = self._chk_adv_delay_on.isChecked()
        d_ms = int(self._spin_adv_delay_ms.value())
        du = d_ms if d_on and self._chk_adv_delay_out.isChecked() else 0
        dd = d_ms if d_on and self._chk_adv_delay_in.isChecked() else 0

        j_on = self._chk_adv_jitter_on.isChecked()
        j_ms = int(self._spin_adv_jitter_ms.value())
        ju = j_ms if j_on and self._chk_adv_jitter_out.isChecked() else 0
        jd = j_ms if j_on and self._chk_adv_jitter_in.isChecked() else 0

        c_on = self._chk_adv_cap_on.isChecked()
        cu = float(self._spin_adv_cap_out_mbps.value()) if c_on and self._chk_adv_cap_out.isChecked() else 0.0
        cd = float(self._spin_adv_cap_in_mbps.value()) if c_on and self._chk_adv_cap_in.isChecked() else 0.0

        l_on = self._chk_adv_loss_on.isChecked()
        lp = int(self._spin_adv_loss_pct.value())
        lu = lp if l_on and self._chk_adv_loss_out.isChecked() else 0
        ld = lp if l_on and self._chk_adv_loss_in.isChecked() else 0
        return du, dd, ju, jd, cu, cd, lu, ld

    def _has_valid_mitm_config(self) -> bool:
        du, dd, ju, jd, cu, cd, lu, ld = self._mitm_effective_params()
        return any(
            (
                du > 0,
                dd > 0,
                ju > 0,
                jd > 0,
                cu > 0.0,
                cd > 0.0,
                lu > 0,
                ld > 0,
            )
        )

    def _sync_victim_master_toggle(self) -> None:
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
            f'Advanced lag is active for this session (device {mac}). '
            'Turn the victim toggle off, use Stop, or turn Kill off.'
        )
        self._lbl_mitm_status.setStyleSheet('color: #8fbcbb; font-size: 11px;')

    def _log(self, msg: str, color: str = 'red') -> None:
        main = self.elmocut
        if main is not None and hasattr(main, 'log'):
            try:
                main.log(msg, color)
            except Exception:
                pass

    def _push_shaping_if_active(self) -> None:
        main = self.elmocut
        if main is None or not getattr(main, 'mitm_shaping_active', False):
            return
        if not self._has_valid_mitm_config():
            main.stop_mitm_shaping(log=True)
            self._refresh_mitm_status()
            return
        du, dd, ju, jd, cu, cd, lu, ld = self._mitm_effective_params()
        main.start_mitm_shaping_from_advanced(du, dd, ju, jd, cu, cd, lu, ld)
        self._refresh_mitm_status()

    def _on_mitm_field_changed(self, *_args) -> None:
        if self._mitm_sync_guard:
            return
        self._persist_mitm_ui()
        self._sync_mitm_row_enables()
        self._push_shaping_if_active()

    def _on_victim_shaping_toggled(self, checked: bool) -> None:
        main = self.elmocut
        if main is None or self._mitm_sync_guard:
            return
        self._persist_mitm_ui()
        if checked:
            if not self._has_valid_mitm_config():
                self._log(
                    'Enable at least one row, tick In or Out, and set non-zero values, then turn the victim toggle on.',
                    'red',
                )
                self._set_toggle_state(self._tog_victim_all, False)
                self._refresh_mitm_status()
                return
            du, dd, ju, jd, cu, cd, lu, ld = self._mitm_effective_params()
            main.start_mitm_shaping_from_advanced(du, dd, ju, jd, cu, cd, lu, ld)
        else:
            main.stop_mitm_shaping(log=True)
        self._refresh_mitm_status()

    def _on_mitm_stop(self) -> None:
        main = self.elmocut
        if main is None:
            return
        main.stop_mitm_shaping(log=True)
        self._refresh_mitm_status()

    def _sync_mitm_row_enables(self) -> None:
        if self._chk_adv_delay_on is None:
            return
        d_on = self._chk_adv_delay_on.isChecked()
        for w in (self._chk_adv_delay_in, self._chk_adv_delay_out, self._spin_adv_delay_ms):
            w.setEnabled(d_on)
        j_on = self._chk_adv_jitter_on.isChecked()
        for w in (self._chk_adv_jitter_in, self._chk_adv_jitter_out, self._spin_adv_jitter_ms):
            w.setEnabled(j_on)
        c_on = self._chk_adv_cap_on.isChecked()
        for w in (
            self._chk_adv_cap_in,
            self._chk_adv_cap_out,
            self._spin_adv_cap_out_mbps,
            self._spin_adv_cap_in_mbps,
        ):
            w.setEnabled(c_on)
        l_on = self._chk_adv_loss_on.isChecked()
        for w in (self._chk_adv_loss_in, self._chk_adv_loss_out, self._spin_adv_loss_pct):
            w.setEnabled(l_on)

    def _mitm_victim_section(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox('Victim', parent)
        _section_font(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        row_v = QHBoxLayout()
        lbl_v = QLabel('Lag victim (master)', box)
        lbl_v.setStyleSheet('color: #e8eaed;')
        self._tog_victim_all = self._mitm_toggle(
            box,
            'On: apply every enabled impairment row to the selected device. Off: stop immediately.',
        )
        self._set_toggle_state(self._tog_victim_all, False)
        self._tog_victim_all.toggled.connect(self._on_victim_shaping_toggled)
        row_v.addWidget(lbl_v)
        row_v.addStretch()
        row_v.addWidget(self._tog_victim_all)
        lay.addLayout(row_v)

        hint = QLabel(
            'Turn on after configuring the rows above. Edits apply live while this is on. '
            'Select the target device in the main list before starting.',
            box,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #9a9a9a; font-size: 11px;')
        lay.addWidget(hint)

        row = QHBoxLayout()
        btn_stop = QPushButton('Stop', box)
        btn_stop.setToolTip('Same as turning the victim toggle off.')
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
        return box

    def _add_impairment_row(
        self,
        grid: QGridLayout,
        row: int,
        *,
        title: str,
        chk_on: QCheckBox,
        chk_in: QCheckBox,
        chk_out: QCheckBox,
        tail_widgets: list,
    ) -> None:
        """Columns: impairment | row On | In/Out strip | values (matches header row)."""
        lbl = QLabel(title)
        lbl.setStyleSheet('color: #e8eaed;')
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(lbl, row, 0)
        ca = Qt.AlignCenter
        grid.addWidget(chk_on, row, 1, ca)
        par = chk_on.parent()
        dir_strip = QWidget(par)
        dir_strip.setObjectName('zubcutAdvLagDirStrip')
        dlay = QHBoxLayout(dir_strip)
        dlay.setContentsMargins(10, 4, 10, 4)
        dlay.setSpacing(18)
        dlay.addWidget(chk_in, 0, ca)
        dlay.addWidget(chk_out, 0, ca)
        grid.addWidget(dir_strip, row, 2)
        tail = QHBoxLayout()
        tail.setSpacing(8)
        tail.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for w in tail_widgets:
            tail.addWidget(w)
        tail.addStretch()
        wrap = QWidget(par)
        wrap.setLayout(tail)
        grid.addWidget(wrap, row, 3)

    def _mitm_impairments_section(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox('Impairments (clumsy-style)', parent)
        _section_font(box)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(6)

        hdr = QGridLayout()
        hdr.setHorizontalSpacing(14)
        hdr.setVerticalSpacing(4)
        hdr.setColumnStretch(3, 1)
        h0 = QLabel('Impairment')
        h1 = QLabel('On')
        h_dir = QLabel('In / Out')
        h4 = QLabel('Values')
        for h, c in ((h0, 0), (h1, 1), (h_dir, 2), (h4, 3)):
            h.setStyleSheet('color: #9a9a9a; font-size: 11px;')
            hdr.addWidget(h, 0, c)
        hdr.setColumnMinimumWidth(0, 140)
        hdr.setColumnMinimumWidth(1, 38)
        hdr.setColumnMinimumWidth(2, 104)
        inner.addLayout(hdr)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(3, 1)
        grid.setColumnMinimumWidth(0, 140)
        grid.setColumnMinimumWidth(1, 38)
        grid.setColumnMinimumWidth(2, 104)

        def _mk_chk_on(key: str, default: bool) -> QCheckBox:
            c = QCheckBox('', box)
            c.setObjectName('zubcutAdvLagChkOn')
            c.setTristate(False)
            c.setChecked(_bool_setting(key, default))
            c.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            c.setFixedWidth(24)
            c.setAttribute(Qt.WA_StyledBackground, True)
            c.stateChanged.connect(self._on_mitm_field_changed)
            return c

        def _mk_chk_dir(key: str, default: bool) -> QCheckBox:
            c = QCheckBox('', box)
            c.setObjectName('zubcutAdvLagChkDir')
            c.setTristate(False)
            c.setChecked(_bool_setting(key, default))
            c.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            c.setFixedWidth(22)
            c.setAttribute(Qt.WA_StyledBackground, True)
            c.stateChanged.connect(self._on_mitm_field_changed)
            return c

        r = 0
        self._chk_adv_delay_on = _mk_chk_on('mitm_adv_delay_on', False)
        self._chk_adv_delay_in = _mk_chk_dir('mitm_adv_delay_in', True)
        self._chk_adv_delay_out = _mk_chk_dir('mitm_adv_delay_out', True)
        self._spin_adv_delay_ms = QSpinBox(box)
        self._spin_adv_delay_ms.setRange(0, 800)
        self._spin_adv_delay_ms.setSuffix(' ms')
        self._spin_adv_delay_ms.setValue(_int_setting('mitm_adv_delay_ms', 0))
        self._spin_adv_delay_ms.setToolTip('Fixed extra delay before forwarding.')
        self._spin_adv_delay_ms.valueChanged.connect(self._on_mitm_field_changed)
        self._add_impairment_row(
            grid,
            r,
            title='Lag / delay',
            chk_on=self._chk_adv_delay_on,
            chk_in=self._chk_adv_delay_in,
            chk_out=self._chk_adv_delay_out,
            tail_widgets=[self._spin_adv_delay_ms],
        )
        r += 1

        self._chk_adv_jitter_on = _mk_chk_on('mitm_adv_jitter_on', False)
        self._chk_adv_jitter_in = _mk_chk_dir('mitm_adv_jitter_in', True)
        self._chk_adv_jitter_out = _mk_chk_dir('mitm_adv_jitter_out', True)
        self._spin_adv_jitter_ms = QSpinBox(box)
        self._spin_adv_jitter_ms.setRange(0, 800)
        self._spin_adv_jitter_ms.setSuffix(' ms')
        self._spin_adv_jitter_ms.setValue(_int_setting('mitm_adv_jitter_ms', 0))
        self._spin_adv_jitter_ms.setToolTip(
            'Random extra delay 0…N ms added on top of fixed delay (uniform per packet).'
        )
        self._spin_adv_jitter_ms.valueChanged.connect(self._on_mitm_field_changed)
        self._add_impairment_row(
            grid,
            r,
            title='Jitter',
            chk_on=self._chk_adv_jitter_on,
            chk_in=self._chk_adv_jitter_in,
            chk_out=self._chk_adv_jitter_out,
            tail_widgets=[self._spin_adv_jitter_ms],
        )
        r += 1

        self._chk_adv_cap_on = _mk_chk_on('mitm_adv_cap_on', False)
        self._chk_adv_cap_in = _mk_chk_dir('mitm_adv_cap_in', True)
        self._chk_adv_cap_out = _mk_chk_dir('mitm_adv_cap_out', True)
        lbl_cap_in = QLabel('In:')
        self._spin_adv_cap_in_mbps = QDoubleSpinBox(box)
        self._spin_adv_cap_in_mbps.setRange(0.0, 10_000.0)
        self._spin_adv_cap_in_mbps.setDecimals(2)
        self._spin_adv_cap_in_mbps.setSingleStep(0.5)
        self._spin_adv_cap_in_mbps.setSuffix(' Mbps')
        self._spin_adv_cap_in_mbps.setMinimumWidth(108)
        self._spin_adv_cap_in_mbps.setValue(_float_setting('mitm_adv_cap_in_mbps', 0.0))
        self._spin_adv_cap_in_mbps.valueChanged.connect(self._on_mitm_field_changed)
        lbl_cap_out = QLabel('Out:')
        self._spin_adv_cap_out_mbps = QDoubleSpinBox(box)
        self._spin_adv_cap_out_mbps.setRange(0.0, 10_000.0)
        self._spin_adv_cap_out_mbps.setDecimals(2)
        self._spin_adv_cap_out_mbps.setSingleStep(0.5)
        self._spin_adv_cap_out_mbps.setSuffix(' Mbps')
        self._spin_adv_cap_out_mbps.setMinimumWidth(108)
        self._spin_adv_cap_out_mbps.setValue(_float_setting('mitm_adv_cap_out_mbps', 0.0))
        self._spin_adv_cap_out_mbps.valueChanged.connect(self._on_mitm_field_changed)
        self._add_impairment_row(
            grid,
            r,
            title='Bandwidth cap',
            chk_on=self._chk_adv_cap_on,
            chk_in=self._chk_adv_cap_in,
            chk_out=self._chk_adv_cap_out,
            tail_widgets=[lbl_cap_in, self._spin_adv_cap_in_mbps, lbl_cap_out, self._spin_adv_cap_out_mbps],
        )
        r += 1

        self._chk_adv_loss_on = _mk_chk_on('mitm_adv_loss_on', False)
        self._chk_adv_loss_in = _mk_chk_dir('mitm_adv_loss_in', True)
        self._chk_adv_loss_out = _mk_chk_dir('mitm_adv_loss_out', True)
        self._spin_adv_loss_pct = QSpinBox(box)
        self._spin_adv_loss_pct.setRange(0, 100)
        self._spin_adv_loss_pct.setSuffix(' %')
        self._spin_adv_loss_pct.setValue(_int_setting('mitm_adv_loss_pct', 0))
        self._spin_adv_loss_pct.setToolTip('Random drop chance before forwarding.')
        self._spin_adv_loss_pct.valueChanged.connect(self._on_mitm_field_changed)
        lp = QLabel('Chance')
        self._add_impairment_row(
            grid,
            r,
            title='% loss',
            chk_on=self._chk_adv_loss_on,
            chk_in=self._chk_adv_loss_in,
            chk_out=self._chk_adv_loss_out,
            tail_widgets=[lp, self._spin_adv_loss_pct],
        )

        inner.addLayout(grid)
        intro = QLabel(
            'Enable a row, tick In and/or Out, set values. Nothing is applied until the victim toggle is on.',
            box,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet('color: #c5c5c5; font-size: 11px;')
        inner.addWidget(intro)

        self._sync_mitm_row_enables()
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
        box = QGroupBox(self._CLUMSY_ONLY_TITLE, parent)
        _section_font(box)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(8)

        intro = QLabel(
            'These controls apply only when Clumsy mode is enabled in Settings (Windows ICS / '
            'shared clients and the inline device row). They do not change the standard '
            'Lag Switch on the normal adapter path.',
            box,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet('color: #c5c5c5; font-size: 11px;')
        inner.addWidget(intro)

        if _mitm_sections_enabled():
            ics_note = QLabel(
                'On ICS shared clients, advanced shaping uses WinDivert in the driver when Clumsy mode '
                'is on, WinDivert is available next to the app, and the selected row matches the detected '
                'ICS client IP; otherwise it uses the in-app MITM forwarder path. You can still tune delay, '
                'loss, and caps with the spin boxes above.',
                box,
            )
        else:
            ics_note = QLabel(
                'On ICS shared clients, use external clumsy + WinDivert for predictable delay and rate limits.',
                box,
            )
        ics_note.setWordWrap(True)
        ics_note.setStyleSheet('color: #9a9a9a; font-size: 11px;')
        inner.addWidget(ics_note)

        self._lbl_clumsy_status = QLabel(box)
        self._lbl_clumsy_status.setWordWrap(True)
        inner.addWidget(self._lbl_clumsy_status)

        stub = QLabel(
            'No separate WinDivert presets here: the same spin values drive shaping on whichever path is active.',
            box,
        )
        stub.setWordWrap(True)
        stub.setStyleSheet('color: #9a9a9a; font-size: 11px;')
        inner.addWidget(stub)
        return box
