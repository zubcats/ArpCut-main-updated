"""Advanced Lag Settings — clumsy-style rows + master victim toggle (MITM shaping path).

Each row: enable, In/Out, values, and optional timer (Lag ms, Pause ms, Repeat, Cycles).
Repeat: use pause and repeat lag→pause cycles; off = one lag phase then that row's timer
stays off (other rows unaffected). Cycles = −1 shows ∞ and means unlimited cycles when Repeat
is on; otherwise Cycles is how many full lag→pause cycles that row runs before stopping only
that impairment. Turning the victim toggle on applies enabled rows; off stops all.
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
from tools.utils_gui import register_window_surface_effects, get_settings, set_settings, set_settings_many


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


def _configure_infinity_at_minimum(
    spin: QSpinBox | QDoubleSpinBox,
    *,
    suffix: str = '',
    tooltip: str = '',
) -> None:
    """Display ∞ at the spin minimum (usually 0 = unlimited / no effect); hide suffix at minimum."""
    spin.setSpecialValueText('∞')
    if tooltip:
        spin.setToolTip(tooltip)

    def _sync_suffix(_v=None) -> None:
        try:
            at_min = float(spin.value()) <= float(spin.minimum()) + 1e-9
        except (TypeError, ValueError):
            at_min = False
        spin.setSuffix('' if at_min else suffix)

    spin.valueChanged.connect(_sync_suffix)
    _sync_suffix()


def _mk_cap_mbps_spin(parent: QWidget, key: str, default: float) -> QDoubleSpinBox:
    s = QDoubleSpinBox(parent)
    s.setRange(0.0, 10_000.0)
    s.setDecimals(2)
    s.setSingleStep(0.5)
    s.setMinimumWidth(108)
    s.setValue(max(0.0, _float_setting(key, default)))
    _configure_infinity_at_minimum(
        s,
        suffix=' Mbps',
        tooltip='0 (∞) = no bandwidth cap for this direction. Raise the value to limit speed in Mbps.',
    )
    return s


def _mk_effect_ms_spin(parent: QWidget, key: str, default: int, *, effect_name: str) -> QSpinBox:
    from networking.forwarder import _MAX_DELAY_MS

    s = QSpinBox(parent)
    s.setRange(0, int(_MAX_DELAY_MS))
    s.setSingleStep(50 if int(_MAX_DELAY_MS) >= 1000 else 10)
    s.setValue(max(0, min(int(_MAX_DELAY_MS), _int_setting(key, default))))
    _configure_infinity_at_minimum(
        s,
        suffix=' ms',
        tooltip=(
            f'0 (∞) = no added {effect_name} for this direction. '
            f'Set milliseconds to apply the effect (max {int(_MAX_DELAY_MS)} ms).'
        ),
    )
    return s


class AdvancedLagSettingsDialog(FramelessResizableMixin, QDialog):
    """Non-modal panel opened from the main flow toggles (right-click → Advanced Lag Settings)."""

    @staticmethod
    def _center_cell(parent: QWidget, inner: QWidget) -> QWidget:
        """Keep spinboxes aligned under column headers."""
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addStretch(1)
        lay.addWidget(inner, 0, Qt.AlignHCenter)
        lay.addStretch(1)
        return w

    def __init__(self, parent=None):
        super().__init__(None)
        self.setObjectName('zubcutLagDupeDialog')
        self.app = parent
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

        self._chk_adv_delay_timer_on: QCheckBox | None = None
        self._spin_adv_delay_timer_lag_ms: QSpinBox | None = None
        self._spin_adv_delay_timer_pause_ms: QSpinBox | None = None
        self._chk_adv_delay_timer_repeat_forever: QCheckBox | None = None
        self._spin_adv_delay_timer_runs: QSpinBox | None = None
        self._chk_adv_jitter_timer_on: QCheckBox | None = None
        self._spin_adv_jitter_timer_lag_ms: QSpinBox | None = None
        self._spin_adv_jitter_timer_pause_ms: QSpinBox | None = None
        self._chk_adv_jitter_timer_repeat_forever: QCheckBox | None = None
        self._spin_adv_jitter_timer_runs: QSpinBox | None = None
        self._chk_adv_cap_timer_on: QCheckBox | None = None
        self._spin_adv_cap_timer_lag_ms: QSpinBox | None = None
        self._spin_adv_cap_timer_pause_ms: QSpinBox | None = None
        self._chk_adv_cap_timer_repeat_forever: QCheckBox | None = None
        self._spin_adv_cap_timer_runs: QSpinBox | None = None
        self._chk_adv_loss_timer_on: QCheckBox | None = None
        self._spin_adv_loss_timer_lag_ms: QSpinBox | None = None
        self._spin_adv_loss_timer_pause_ms: QSpinBox | None = None
        self._chk_adv_loss_timer_repeat_forever: QCheckBox | None = None
        self._spin_adv_loss_timer_runs: QSpinBox | None = None

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle('Advanced Lag Settings')
        self.setModal(False)
        self.setMinimumWidth(1180)
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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_inner = QWidget(scroll)
        scroll_inner.setObjectName('zubcutAdvLagScrollInner')
        scroll_layout = QVBoxLayout(scroll_inner)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(10)

        scroll_layout.addWidget(self._top_info_banner(scroll_inner))
        scroll_layout.addWidget(self._mitm_impairments_section(scroll_inner))
        scroll_layout.addWidget(self._mitm_victim_section(scroll_inner))

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

    def _top_info_banner(self, parent: QWidget) -> QWidget:
        wrap = QWidget(parent)
        wrap.setObjectName('zubcutAdvLagIntroWrap')
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(6)

        main = QLabel(
            'In Clumzy Mode these rows drive the Clumzy engine: delay is lag, loss is drop, '
            'cap is bandwidth. Jitter is extra lag (Clumzy has no separate jitter module). '
            'Each row can have its own timer and Repeat. Nothing applies until the victim toggle is on.',
            wrap,
        )
        main.setWordWrap(True)
        main.setStyleSheet('color: #c5c5c5; font-size: 11px; background-color: #000000;')
        lay.addWidget(main)

        self._lbl_clumsy_status = QLabel(wrap)
        self._lbl_clumsy_status.setWordWrap(True)
        lay.addWidget(self._lbl_clumsy_status)
        return wrap

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

    def live_mitm_adv_settings(self) -> dict:
        """Current Advanced Lag UI values (for the scheduler; does not write disk)."""
        if self._chk_adv_delay_on is None:
            return {}
        du, dd, ju, jd, cu, cd, lu, ld = self._mitm_effective_params()
        return {
            'mitm_adv_delay_on': self._chk_adv_delay_on.isChecked(),
            'mitm_adv_delay_in': self._chk_adv_delay_in.isChecked(),
            'mitm_adv_delay_out': self._chk_adv_delay_out.isChecked(),
            'mitm_adv_delay_ms': int(self._spin_adv_delay_ms.value()),
            'mitm_adv_jitter_on': self._chk_adv_jitter_on.isChecked(),
            'mitm_adv_jitter_in': self._chk_adv_jitter_in.isChecked(),
            'mitm_adv_jitter_out': self._chk_adv_jitter_out.isChecked(),
            'mitm_adv_jitter_ms': int(self._spin_adv_jitter_ms.value()),
            'mitm_adv_cap_on': self._chk_adv_cap_on.isChecked(),
            'mitm_adv_cap_in': self._chk_adv_cap_in.isChecked(),
            'mitm_adv_cap_out': self._chk_adv_cap_out.isChecked(),
            'mitm_adv_cap_out_mbps': float(self._spin_adv_cap_out_mbps.value()),
            'mitm_adv_cap_in_mbps': float(self._spin_adv_cap_in_mbps.value()),
            'mitm_adv_loss_on': self._chk_adv_loss_on.isChecked(),
            'mitm_adv_loss_in': self._chk_adv_loss_in.isChecked(),
            'mitm_adv_loss_out': self._chk_adv_loss_out.isChecked(),
            'mitm_adv_loss_pct': int(self._spin_adv_loss_pct.value()),
            'mitm_adv_delay_timer_on': self._chk_adv_delay_timer_on.isChecked(),
            'mitm_adv_delay_timer_lag_ms': int(self._spin_adv_delay_timer_lag_ms.value()),
            'mitm_adv_delay_timer_pause_ms': int(self._spin_adv_delay_timer_pause_ms.value()),
            'mitm_adv_delay_timer_repeat_forever': self._chk_adv_delay_timer_repeat_forever.isChecked(),
            'mitm_adv_delay_timer_runs': int(self._spin_adv_delay_timer_runs.value()),
            'mitm_adv_jitter_timer_on': self._chk_adv_jitter_timer_on.isChecked(),
            'mitm_adv_jitter_timer_lag_ms': int(self._spin_adv_jitter_timer_lag_ms.value()),
            'mitm_adv_jitter_timer_pause_ms': int(self._spin_adv_jitter_timer_pause_ms.value()),
            'mitm_adv_jitter_timer_repeat_forever': self._chk_adv_jitter_timer_repeat_forever.isChecked(),
            'mitm_adv_jitter_timer_runs': int(self._spin_adv_jitter_timer_runs.value()),
            'mitm_adv_cap_timer_on': self._chk_adv_cap_timer_on.isChecked(),
            'mitm_adv_cap_timer_lag_ms': int(self._spin_adv_cap_timer_lag_ms.value()),
            'mitm_adv_cap_timer_pause_ms': int(self._spin_adv_cap_timer_pause_ms.value()),
            'mitm_adv_cap_timer_repeat_forever': self._chk_adv_cap_timer_repeat_forever.isChecked(),
            'mitm_adv_cap_timer_runs': int(self._spin_adv_cap_timer_runs.value()),
            'mitm_adv_loss_timer_on': self._chk_adv_loss_timer_on.isChecked(),
            'mitm_adv_loss_timer_lag_ms': int(self._spin_adv_loss_timer_lag_ms.value()),
            'mitm_adv_loss_timer_pause_ms': int(self._spin_adv_loss_timer_pause_ms.value()),
            'mitm_adv_loss_timer_repeat_forever': self._chk_adv_loss_timer_repeat_forever.isChecked(),
            'mitm_adv_loss_timer_runs': int(self._spin_adv_loss_timer_runs.value()),
            'mitm_delay_up_ms': du,
            'mitm_delay_down_ms': dd,
            'mitm_cap_up_mbps': cu,
            'mitm_cap_down_mbps': cd,
        }

    def mitm_adv_settings_get(self, key: str, default=None):
        live = self.live_mitm_adv_settings()
        if key in live:
            return live[key]
        try:
            return get_settings(key)
        except KeyError:
            return default

    def _persist_mitm_ui(self) -> None:
        if self._chk_adv_delay_on is None:
            return
        try:
            du, dd, ju, jd, cu, cd, lu, ld = self._mitm_effective_params()
            set_settings_many(
                {
                    'mitm_adv_delay_on': self._chk_adv_delay_on.isChecked(),
                    'mitm_adv_delay_in': self._chk_adv_delay_in.isChecked(),
                    'mitm_adv_delay_out': self._chk_adv_delay_out.isChecked(),
                    'mitm_adv_delay_ms': int(self._spin_adv_delay_ms.value()),
                    'mitm_adv_jitter_on': self._chk_adv_jitter_on.isChecked(),
                    'mitm_adv_jitter_in': self._chk_adv_jitter_in.isChecked(),
                    'mitm_adv_jitter_out': self._chk_adv_jitter_out.isChecked(),
                    'mitm_adv_jitter_ms': int(self._spin_adv_jitter_ms.value()),
                    'mitm_adv_cap_on': self._chk_adv_cap_on.isChecked(),
                    'mitm_adv_cap_in': self._chk_adv_cap_in.isChecked(),
                    'mitm_adv_cap_out': self._chk_adv_cap_out.isChecked(),
                    'mitm_adv_cap_out_mbps': float(self._spin_adv_cap_out_mbps.value()),
                    'mitm_adv_cap_in_mbps': float(self._spin_adv_cap_in_mbps.value()),
                    'mitm_adv_loss_on': self._chk_adv_loss_on.isChecked(),
                    'mitm_adv_loss_in': self._chk_adv_loss_in.isChecked(),
                    'mitm_adv_loss_out': self._chk_adv_loss_out.isChecked(),
                    'mitm_adv_loss_pct': int(self._spin_adv_loss_pct.value()),
                    'mitm_adv_delay_timer_on': self._chk_adv_delay_timer_on.isChecked(),
                    'mitm_adv_delay_timer_lag_ms': int(self._spin_adv_delay_timer_lag_ms.value()),
                    'mitm_adv_delay_timer_pause_ms': int(self._spin_adv_delay_timer_pause_ms.value()),
                    'mitm_adv_delay_timer_repeat_forever': self._chk_adv_delay_timer_repeat_forever.isChecked(),
                    'mitm_adv_delay_timer_runs': int(self._spin_adv_delay_timer_runs.value()),
                    'mitm_adv_jitter_timer_on': self._chk_adv_jitter_timer_on.isChecked(),
                    'mitm_adv_jitter_timer_lag_ms': int(self._spin_adv_jitter_timer_lag_ms.value()),
                    'mitm_adv_jitter_timer_pause_ms': int(self._spin_adv_jitter_timer_pause_ms.value()),
                    'mitm_adv_jitter_timer_repeat_forever': self._chk_adv_jitter_timer_repeat_forever.isChecked(),
                    'mitm_adv_jitter_timer_runs': int(self._spin_adv_jitter_timer_runs.value()),
                    'mitm_adv_cap_timer_on': self._chk_adv_cap_timer_on.isChecked(),
                    'mitm_adv_cap_timer_lag_ms': int(self._spin_adv_cap_timer_lag_ms.value()),
                    'mitm_adv_cap_timer_pause_ms': int(self._spin_adv_cap_timer_pause_ms.value()),
                    'mitm_adv_cap_timer_repeat_forever': self._chk_adv_cap_timer_repeat_forever.isChecked(),
                    'mitm_adv_cap_timer_runs': int(self._spin_adv_cap_timer_runs.value()),
                    'mitm_adv_loss_timer_on': self._chk_adv_loss_timer_on.isChecked(),
                    'mitm_adv_loss_timer_lag_ms': int(self._spin_adv_loss_timer_lag_ms.value()),
                    'mitm_adv_loss_timer_pause_ms': int(self._spin_adv_loss_timer_pause_ms.value()),
                    'mitm_adv_loss_timer_repeat_forever': self._chk_adv_loss_timer_repeat_forever.isChecked(),
                    'mitm_adv_loss_timer_runs': int(self._spin_adv_loss_timer_runs.value()),
                    'mitm_delay_up_ms': du,
                    'mitm_delay_down_ms': dd,
                    'mitm_cap_up_mbps': cu,
                    'mitm_cap_down_mbps': cd,
                    'mitm_delay_enabled': self._chk_adv_delay_on.isChecked() and (du > 0 or dd > 0),
                    'mitm_cap_enabled': self._chk_adv_cap_on.isChecked() and (cu > 0.0 or cd > 0.0),
                }
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
        main = self.app
        active = main is not None and bool(getattr(main, 'mitm_shaping_active', False))
        self._tog_victim_all.blockSignals(True)
        self._tog_victim_all.setChecked(active)
        self._tog_victim_all.setText('On' if active else 'Off')
        self._tog_victim_all.blockSignals(False)

    def _refresh_mitm_status(self) -> None:
        self._sync_victim_master_toggle()
        if self._lbl_mitm_status is None:
            return
        main = self.app
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
        main = self.app
        if main is not None and hasattr(main, 'log'):
            try:
                main.log(msg, color)
            except Exception:
                pass

    def _push_shaping_if_active(self) -> None:
        main = self.app
        if main is None or not getattr(main, 'mitm_shaping_active', False):
            return
        if not self._has_valid_mitm_config():
            main.stop_mitm_shaping(log=True)
            self._refresh_mitm_status()
            return
        main._mitm_adv_schedule_tick()
        main._start_mitm_adv_schedule()
        self._refresh_mitm_status()

    def _on_mitm_timer_schedule_changed(self, row_prefix: str = '', *_args) -> None:
        """Timer column edits restart that row's schedule from now."""
        if self._mitm_sync_guard:
            return
        main = self.app
        if main is not None and getattr(main, 'mitm_shaping_active', False):
            try:
                main._reset_mitm_adv_sched_clock(row_prefix or None)
            except Exception:
                pass
        self._on_mitm_field_changed(*_args)

    def _on_mitm_field_changed(self, *_args) -> None:
        if self._mitm_sync_guard:
            return
        self._persist_mitm_ui()
        self._sync_mitm_row_enables()
        self._push_shaping_if_active()

    def _on_victim_shaping_toggled(self, checked: bool) -> None:
        main = self.app
        if main is None or self._mitm_sync_guard:
            return
        try:
            from tools.utils_gui import repair_settings

            repair_settings()
        except Exception:
            pass
        if hasattr(main, 'apply_advanced_clumzy'):
            if checked:
                self._persist_mitm_ui()
                if not self._has_valid_mitm_config():
                    self._log(
                        'Enable at least one row, tick In or Out, and set non-zero values, then turn the victim toggle on.',
                        'red',
                    )
                    self._set_toggle_state(self._tog_victim_all, False)
                    self._refresh_mitm_status()
                    return
                try:
                    main.apply_advanced_clumzy(self.live_mitm_adv_settings())
                except Exception as exc:
                    self._log(f'Advanced Lag failed to start: {exc}', 'red')
                    self._set_toggle_state(self._tog_victim_all, False)
            else:
                try:
                    main.stop_advanced_clumzy()
                except Exception as exc:
                    self._log(f'Advanced Lag failed to stop: {exc}', 'red')
                self._persist_mitm_ui()
            self._refresh_mitm_status()
            return
        if checked:
            self._persist_mitm_ui()
            if not self._has_valid_mitm_config():
                self._log(
                    'Enable at least one row, tick In or Out, and set non-zero values, then turn the victim toggle on.',
                    'red',
                )
                self._set_toggle_state(self._tog_victim_all, False)
                self._refresh_mitm_status()
                return
            try:
                du, dd, ju, jd, cu, cd, lu, ld = self._mitm_effective_params()
                main.start_mitm_shaping_from_advanced(du, dd, ju, jd, cu, cd, lu, ld)
            except Exception as exc:
                self._log(f'Advanced Lag failed to start: {exc}', 'red')
                self._set_toggle_state(self._tog_victim_all, False)
        else:
            try:
                main.stop_mitm_shaping(log=True)
            except Exception as exc:
                self._log(f'Advanced Lag failed to stop: {exc}', 'red')
            self._persist_mitm_ui()
        self._refresh_mitm_status()

    def _on_mitm_stop(self) -> None:
        main = self.app
        if main is None:
            return
        if hasattr(main, 'stop_advanced_clumzy'):
            main.stop_advanced_clumzy()
            self._refresh_mitm_status()
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

        def _row_timer_enables(
            row_on: bool,
            chk_t: QCheckBox,
            sp_lag: QSpinBox,
            sp_pause: QSpinBox,
            chk_forever: QCheckBox,
            sp_runs: QSpinBox,
        ) -> None:
            chk_t.setEnabled(row_on)
            t_on = row_on and chk_t.isChecked()
            for w in (sp_lag, sp_pause, chk_forever):
                w.setEnabled(t_on)
            sp_runs.setEnabled(t_on and chk_forever.isChecked())

        _row_timer_enables(
            d_on,
            self._chk_adv_delay_timer_on,
            self._spin_adv_delay_timer_lag_ms,
            self._spin_adv_delay_timer_pause_ms,
            self._chk_adv_delay_timer_repeat_forever,
            self._spin_adv_delay_timer_runs,
        )
        _row_timer_enables(
            j_on,
            self._chk_adv_jitter_timer_on,
            self._spin_adv_jitter_timer_lag_ms,
            self._spin_adv_jitter_timer_pause_ms,
            self._chk_adv_jitter_timer_repeat_forever,
            self._spin_adv_jitter_timer_runs,
        )
        _row_timer_enables(
            c_on,
            self._chk_adv_cap_timer_on,
            self._spin_adv_cap_timer_lag_ms,
            self._spin_adv_cap_timer_pause_ms,
            self._chk_adv_cap_timer_repeat_forever,
            self._spin_adv_cap_timer_runs,
        )
        _row_timer_enables(
            l_on,
            self._chk_adv_loss_timer_on,
            self._spin_adv_loss_timer_lag_ms,
            self._spin_adv_loss_timer_pause_ms,
            self._chk_adv_loss_timer_repeat_forever,
            self._spin_adv_loss_timer_runs,
        )

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
            'Per-row Timer gates only that row: when a row’s Cycles finish, that impairment stops cycling; '
            'other enabled rows keep their own Lag / Pause / Repeat / Cycles. Select the target device in the main list before starting.',
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
        chk_timer_on: QCheckBox,
        spin_timer_lag_ms: QSpinBox,
        spin_timer_pause_ms: QSpinBox,
        chk_timer_repeat: QCheckBox,
        spin_timer_runs: QSpinBox,
    ) -> None:
        """Columns: impairment | row On | In/Out | values | Timer | Lag | Pause | Repeat | Cycles."""
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
        grid.addWidget(chk_timer_on, row, 4, ca)
        grid.addWidget(self._center_cell(par, spin_timer_lag_ms), row, 5)
        grid.addWidget(self._center_cell(par, spin_timer_pause_ms), row, 6)
        grid.addWidget(chk_timer_repeat, row, 7, ca)
        grid.addWidget(self._center_cell(par, spin_timer_runs), row, 8)

    def _mitm_impairments_section(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox('Impairments (clumsy-style)', parent)
        _section_font(box)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(6)

        hdr = QGridLayout()
        hdr.setHorizontalSpacing(10)
        hdr.setVerticalSpacing(4)
        hdr.setColumnStretch(3, 1)

        def _sched_hdr(text: str, tip: str) -> QLabel:
            h = QLabel(text)
            h.setWordWrap(True)
            h.setAlignment(Qt.AlignCenter)
            h.setToolTip(tip)
            h.setStyleSheet('color: #9a9a9a; font-size: 11px;')
            return h

        h0 = QLabel('Impairment')
        h0.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h1 = QLabel('On')
        h1.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        h_dir = QLabel('In / Out')
        h_dir.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        h4 = QLabel('Values')
        h4.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        h_tm = _sched_hdr(
            'Timer',
            'Turns the schedule on for this row. Off: this row is always applied whenever the row On box is set.',
        )
        h_lag = _sched_hdr(
            'Lag (ms)',
            'How long this impairment stays fully on (same values as the row) before the pause.',
        )
        h_pause = _sched_hdr(
            'Pause (ms)',
            'How long this row is off (no extra lag/cap/loss from this row) before the next lag.',
        )
        h_rep = _sched_hdr(
            'Repeat',
            'When checked: use Pause (ms), then repeat Lag→Pause cycles. When unchecked: one Lag phase only, '
            'then this row’s timer stops for that impairment only (others keep their own schedules).',
        )
        h_runs = _sched_hdr(
            'Cycles',
            'How many full Lag→Pause cycles while Repeat is on. Minimum value −1 shows as ∞ = unlimited. '
            'Only that row stops when its cycles finish.',
        )
        for h, c in (
            (h0, 0),
            (h1, 1),
            (h_dir, 2),
            (h4, 3),
            (h_tm, 4),
            (h_lag, 5),
            (h_pause, 6),
            (h_rep, 7),
            (h_runs, 8),
        ):
            if not h.toolTip():
                h.setStyleSheet('color: #9a9a9a; font-size: 11px;')
            hdr.addWidget(h, 0, c)
        hdr.setColumnMinimumWidth(0, 112)
        hdr.setColumnMinimumWidth(1, 40)
        hdr.setColumnMinimumWidth(2, 104)
        hdr.setColumnMinimumWidth(4, 44)
        hdr.setColumnMinimumWidth(5, 92)
        hdr.setColumnMinimumWidth(6, 92)
        hdr.setColumnMinimumWidth(7, 76)
        hdr.setColumnMinimumWidth(8, 88)
        inner.addLayout(hdr)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(3, 1)
        grid.setColumnMinimumWidth(0, 112)
        grid.setColumnMinimumWidth(1, 40)
        grid.setColumnMinimumWidth(2, 104)
        grid.setColumnMinimumWidth(4, 44)
        grid.setColumnMinimumWidth(5, 92)
        grid.setColumnMinimumWidth(6, 92)
        grid.setColumnMinimumWidth(7, 76)
        grid.setColumnMinimumWidth(8, 88)

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

        def _mk_timer_on_chk(key: str, default: bool, tip: str, row_prefix: str) -> QCheckBox:
            c = QCheckBox('', box)
            c.setObjectName('zubcutAdvLagChkDir')
            c.setTristate(False)
            c.setChecked(_bool_setting(key, default))
            c.setToolTip(tip)
            c.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            c.setFixedWidth(22)
            c.setAttribute(Qt.WA_StyledBackground, True)
            c.stateChanged.connect(
                lambda *_a, p=row_prefix: self._on_mitm_timer_schedule_changed(p)
            )
            return c

        def _mk_timer_repeat_chk(key: str, default: bool, tip: str, row_prefix: str) -> QCheckBox:
            c = QCheckBox('Repeat', box)
            c.setObjectName('zubcutAdvLagChkDir')
            c.setTristate(False)
            c.setChecked(_bool_setting(key, default))
            c.setToolTip(tip)
            c.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            c.setMinimumWidth(72)
            c.setAttribute(Qt.WA_StyledBackground, True)
            c.stateChanged.connect(
                lambda *_a, p=row_prefix: self._on_mitm_timer_schedule_changed(p)
            )
            return c

        def _mk_timer_lag_spin(key: str, default: int, row_prefix: str) -> QSpinBox:
            s = QSpinBox(box)
            s.setRange(1, 600_000)
            s.setSingleStep(50)
            s.setSuffix(' ms')
            s.setValue(_int_setting(key, default))
            s.setToolTip('Duration this row applies at full strength (matches your Lag / cap / loss values).')
            s.valueChanged.connect(
                lambda *_a, p=row_prefix: self._on_mitm_timer_schedule_changed(p)
            )
            return s

        def _mk_timer_pause_spin(key: str, default: int, row_prefix: str) -> QSpinBox:
            s = QSpinBox(box)
            s.setRange(0, 600_000)
            s.setSingleStep(50)
            s.setSuffix(' ms')
            s.setValue(_int_setting(key, default))
            s.setToolTip(
                'Duration this row contributes nothing extra (0 Mbps cap = no cap, 0 ms delay = no added delay) '
                'before the next lag phase.'
            )
            s.valueChanged.connect(
                lambda *_a, p=row_prefix: self._on_mitm_timer_schedule_changed(p)
            )
            return s

        def _mk_timer_runs_spin(key: str, default: int, row_prefix: str) -> QSpinBox:
            s = QSpinBox(box)
            s.setRange(-1, 999_999)
            s.setSpecialValueText('∞')
            s.setToolTip(
                'Full Lag→Pause cycles while Repeat is checked. −1 (∞) = unlimited for this row only. '
                'A positive count stops only this impairment when done; other rows keep running.'
            )
            v = _int_setting(key, default)
            if v == 0:
                v = 1
            s.setValue(v)

            def _sync_runs_suffix(_v=None) -> None:
                s.setSuffix('' if int(s.value()) < 0 else ' cycles')

            s.valueChanged.connect(_sync_runs_suffix)
            _sync_runs_suffix()
            s.valueChanged.connect(
                lambda *_a, p=row_prefix: self._on_mitm_timer_schedule_changed(p)
            )
            return s

        r = 0
        self._chk_adv_delay_on = _mk_chk_on('mitm_adv_delay_on', False)
        self._chk_adv_delay_in = _mk_chk_dir('mitm_adv_delay_in', True)
        self._chk_adv_delay_out = _mk_chk_dir('mitm_adv_delay_out', True)
        self._spin_adv_delay_ms = _mk_effect_ms_spin(box, 'mitm_adv_delay_ms', 0, effect_name='delay')
        self._spin_adv_delay_ms.valueChanged.connect(self._on_mitm_field_changed)
        self._chk_adv_delay_timer_on = _mk_timer_on_chk(
            'mitm_adv_delay_timer_on',
            False,
            'Use lag and pause durations to pulse this row on and off.',
            'mitm_adv_delay',
        )
        self._spin_adv_delay_timer_lag_ms = _mk_timer_lag_spin(
            'mitm_adv_delay_timer_lag_ms', 1000, 'mitm_adv_delay'
        )
        self._spin_adv_delay_timer_pause_ms = _mk_timer_pause_spin(
            'mitm_adv_delay_timer_pause_ms', 1000, 'mitm_adv_delay'
        )
        self._chk_adv_delay_timer_repeat_forever = _mk_timer_repeat_chk(
            'mitm_adv_delay_timer_repeat_forever',
            True,
            'Lag→Pause cycles for this row only. Off = one Lag window then this row’s effect stops cycling.',
            'mitm_adv_delay',
        )
        self._spin_adv_delay_timer_runs = _mk_timer_runs_spin(
            'mitm_adv_delay_timer_runs', -1, 'mitm_adv_delay'
        )
        self._add_impairment_row(
            grid,
            r,
            title='Lag / delay',
            chk_on=self._chk_adv_delay_on,
            chk_in=self._chk_adv_delay_in,
            chk_out=self._chk_adv_delay_out,
            tail_widgets=[self._spin_adv_delay_ms],
            chk_timer_on=self._chk_adv_delay_timer_on,
            spin_timer_lag_ms=self._spin_adv_delay_timer_lag_ms,
            spin_timer_pause_ms=self._spin_adv_delay_timer_pause_ms,
            chk_timer_repeat=self._chk_adv_delay_timer_repeat_forever,
            spin_timer_runs=self._spin_adv_delay_timer_runs,
        )
        r += 1

        self._chk_adv_jitter_on = _mk_chk_on('mitm_adv_jitter_on', False)
        self._chk_adv_jitter_in = _mk_chk_dir('mitm_adv_jitter_in', True)
        self._chk_adv_jitter_out = _mk_chk_dir('mitm_adv_jitter_out', True)
        self._spin_adv_jitter_ms = _mk_effect_ms_spin(box, 'mitm_adv_jitter_ms', 0, effect_name='jitter')
        self._spin_adv_jitter_ms.setToolTip(
            '0 (∞) = no added jitter. Otherwise random extra delay 0…N ms on top of fixed delay (per packet).'
        )
        self._spin_adv_jitter_ms.valueChanged.connect(self._on_mitm_field_changed)
        self._chk_adv_jitter_timer_on = _mk_timer_on_chk(
            'mitm_adv_jitter_timer_on', False, 'Schedule this jitter row.', 'mitm_adv_jitter'
        )
        self._spin_adv_jitter_timer_lag_ms = _mk_timer_lag_spin(
            'mitm_adv_jitter_timer_lag_ms', 1000, 'mitm_adv_jitter'
        )
        self._spin_adv_jitter_timer_pause_ms = _mk_timer_pause_spin(
            'mitm_adv_jitter_timer_pause_ms', 1000, 'mitm_adv_jitter'
        )
        self._chk_adv_jitter_timer_repeat_forever = _mk_timer_repeat_chk(
            'mitm_adv_jitter_timer_repeat_forever',
            True,
            'Lag→Pause cycles for this row only. Off = one Lag window then this row’s effect stops cycling.',
            'mitm_adv_jitter',
        )
        self._spin_adv_jitter_timer_runs = _mk_timer_runs_spin(
            'mitm_adv_jitter_timer_runs', -1, 'mitm_adv_jitter'
        )
        self._add_impairment_row(
            grid,
            r,
            title='Jitter',
            chk_on=self._chk_adv_jitter_on,
            chk_in=self._chk_adv_jitter_in,
            chk_out=self._chk_adv_jitter_out,
            tail_widgets=[self._spin_adv_jitter_ms],
            chk_timer_on=self._chk_adv_jitter_timer_on,
            spin_timer_lag_ms=self._spin_adv_jitter_timer_lag_ms,
            spin_timer_pause_ms=self._spin_adv_jitter_timer_pause_ms,
            chk_timer_repeat=self._chk_adv_jitter_timer_repeat_forever,
            spin_timer_runs=self._spin_adv_jitter_timer_runs,
        )
        r += 1

        self._chk_adv_cap_on = _mk_chk_on('mitm_adv_cap_on', False)
        self._chk_adv_cap_in = _mk_chk_dir('mitm_adv_cap_in', True)
        self._chk_adv_cap_out = _mk_chk_dir('mitm_adv_cap_out', True)
        lbl_cap_in = QLabel('In:')
        self._spin_adv_cap_in_mbps = _mk_cap_mbps_spin(box, 'mitm_adv_cap_in_mbps', 0.0)
        self._spin_adv_cap_in_mbps.valueChanged.connect(self._on_mitm_field_changed)
        lbl_cap_out = QLabel('Out:')
        self._spin_adv_cap_out_mbps = _mk_cap_mbps_spin(box, 'mitm_adv_cap_out_mbps', 0.0)
        self._spin_adv_cap_out_mbps.valueChanged.connect(self._on_mitm_field_changed)
        self._chk_adv_cap_timer_on = _mk_timer_on_chk(
            'mitm_adv_cap_timer_on', False, 'Schedule this cap row.', 'mitm_adv_cap'
        )
        self._spin_adv_cap_timer_lag_ms = _mk_timer_lag_spin(
            'mitm_adv_cap_timer_lag_ms', 1000, 'mitm_adv_cap'
        )
        self._spin_adv_cap_timer_pause_ms = _mk_timer_pause_spin(
            'mitm_adv_cap_timer_pause_ms', 1000, 'mitm_adv_cap'
        )
        self._chk_adv_cap_timer_repeat_forever = _mk_timer_repeat_chk(
            'mitm_adv_cap_timer_repeat_forever',
            True,
            'Lag→Pause cycles for this row only. Off = one Lag window then this row’s effect stops cycling.',
            'mitm_adv_cap',
        )
        self._spin_adv_cap_timer_runs = _mk_timer_runs_spin(
            'mitm_adv_cap_timer_runs', -1, 'mitm_adv_cap'
        )
        self._add_impairment_row(
            grid,
            r,
            title='Bandwidth cap',
            chk_on=self._chk_adv_cap_on,
            chk_in=self._chk_adv_cap_in,
            chk_out=self._chk_adv_cap_out,
            tail_widgets=[
                lbl_cap_in,
                self._spin_adv_cap_in_mbps,
                lbl_cap_out,
                self._spin_adv_cap_out_mbps,
            ],
            chk_timer_on=self._chk_adv_cap_timer_on,
            spin_timer_lag_ms=self._spin_adv_cap_timer_lag_ms,
            spin_timer_pause_ms=self._spin_adv_cap_timer_pause_ms,
            chk_timer_repeat=self._chk_adv_cap_timer_repeat_forever,
            spin_timer_runs=self._spin_adv_cap_timer_runs,
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
        self._chk_adv_loss_timer_on = _mk_timer_on_chk(
            'mitm_adv_loss_timer_on', False, 'Schedule this loss row.', 'mitm_adv_loss'
        )
        self._spin_adv_loss_timer_lag_ms = _mk_timer_lag_spin(
            'mitm_adv_loss_timer_lag_ms', 1000, 'mitm_adv_loss'
        )
        self._spin_adv_loss_timer_pause_ms = _mk_timer_pause_spin(
            'mitm_adv_loss_timer_pause_ms', 1000, 'mitm_adv_loss'
        )
        self._chk_adv_loss_timer_repeat_forever = _mk_timer_repeat_chk(
            'mitm_adv_loss_timer_repeat_forever',
            True,
            'Lag→Pause cycles for this row only. Off = one Lag window then this row’s effect stops cycling.',
            'mitm_adv_loss',
        )
        self._spin_adv_loss_timer_runs = _mk_timer_runs_spin(
            'mitm_adv_loss_timer_runs', -1, 'mitm_adv_loss'
        )
        self._add_impairment_row(
            grid,
            r,
            title='% loss',
            chk_on=self._chk_adv_loss_on,
            chk_in=self._chk_adv_loss_in,
            chk_out=self._chk_adv_loss_out,
            tail_widgets=[lp, self._spin_adv_loss_pct],
            chk_timer_on=self._chk_adv_loss_timer_on,
            spin_timer_lag_ms=self._spin_adv_loss_timer_lag_ms,
            spin_timer_pause_ms=self._spin_adv_loss_timer_pause_ms,
            chk_timer_repeat=self._chk_adv_loss_timer_repeat_forever,
            spin_timer_runs=self._spin_adv_loss_timer_runs,
        )

        inner.addLayout(grid)
        intro = QLabel(
            'Enable a row, tick In and/or Out, set values. 0 or −1 where shown as ∞ means unlimited (no cap, no added delay/jitter, '
            'or infinite timer cycles). Timer: Lag (ms) applies that row, Pause (ms) clears that row’s effect, then Repeat '
            'controls whether the cycle continues. A positive Cycles value counts Lag→Pause cycles for that row only—when one row '
            'finishes, the others continue. Nothing applies until the victim toggle is on.',
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
            self._lbl_clumsy_status.setText('Clumzy Mode is only available on Windows.')
            self._lbl_clumsy_status.setStyleSheet('color: #9a9a9a; font-size: 11px; background-color: #000000;')
            return
        try:
            from tools.clumsy_inline import (
                clumsy_bundle_offered,
                clumsy_mode_enabled,
                clumsy_runtime_ready,
                windivert_driver_installed,
            )
        except Exception:
            self._lbl_clumsy_status.setText('Could not read Clumzy Mode status.')
            self._lbl_clumsy_status.setStyleSheet('color: #c9a227; font-size: 11px; background-color: #000000;')
            return
        mode = clumsy_mode_enabled()
        bundle = clumsy_bundle_offered()
        driver = windivert_driver_installed()
        ready = clumsy_runtime_ready()
        lines = [
            f'Clumzy Mode (Settings): {"on" if mode else "off"}',
            f'WinDivert driver: {"present" if driver else "missing"}',
        ]
        if getattr(self.app, 'clumzy_mode_shell', False):
            lines.append('Clumzy engine: Kill / Lag Switch / Dupe use Freeze on all forwarded hotspot packets.')
            lines.append('Advanced Lag maps delay/loss/cap/jitter onto Clumzy modules (not ARP MITM).')
        else:
            if getattr(sys, 'frozen', False):
                lines.append(f'Portable Clumzy bundle flag: {"yes" if bundle else "no"}')
            lines.append(f'Ready for inline ICS row: {"yes" if ready and mode else "no"}')
        self._lbl_clumsy_status.setText('\n'.join(lines))
        if mode and ready:
            self._lbl_clumsy_status.setStyleSheet('color: #8fbcbb; font-size: 11px; background-color: #000000;')
        elif mode and not ready:
            self._lbl_clumsy_status.setStyleSheet('color: #c9a227; font-size: 11px; background-color: #000000;')
        else:
            self._lbl_clumsy_status.setStyleSheet('color: #9a9a9a; font-size: 11px; background-color: #000000;')
