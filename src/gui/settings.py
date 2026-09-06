from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLineEdit,
    QLabel,
    QPushButton,
    QKeySequenceEdit,
    QCheckBox,
    QComboBox,
    QVBoxLayout,
    QGridLayout,
    QScrollArea,
    QWidget,
    QSizePolicy,
    QProgressDialog,
    QGraphicsOpacityEffect,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
)
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtCore import Qt, QTimer, QEvent, QObject, QThread, pyqtSignal
import os
import sys

from tools.utils_gui import import_settings, export_settings, get_settings, \
                      is_admin, add_to_startup, remove_from_startup, set_settings, \
                      set_settings_many, \
                      zubcut_dark_stylesheet, \
                      sync_translucent_chrome, register_window_surface_effects, \
                      repair_settings
from tools.frameless_chrome import FramelessResizableMixin, setup_frameless_main_window
from tools.qtools import MsgType, Buttons
from tools.utils import (
    goto,
    get_ifaces,
    get_ifaces_cached,
    get_iface_by_name,
    terminal,
    format_iface_settings_label,
    ifaces_for_settings_combo,
)

from ui.ui_settings import Ui_MainWindow

from networking.nicknames import Nicknames

from tools.keybinds import keyseq_from_setting
from tools.updater_core import (
    get_update_status,
    launch_installer,
    remote_installer_info,
    format_updater_error_message,
    installer_download_candidates,
    resolve_installer_download_url,
    selected_update_url,
)
from tools.updater_progress import download_update_with_progress_dialog
from tools.updater_debug import (
    begin_updater_debug_session,
    updater_log,
    updater_log_paths_hint,
)

from constants import *
import constants as _zcut_constants

from tools.clumsy_inline import (
    clumsy_bundle_incomplete,
    clumsy_bundle_offered,
    windivert_driver_installed,
)
from tools.clumsy_ics import (
    format_clumsy_ics_error,
    mark_clumsy_settings_restart_pending,
    read_clumsy_topology,
    repair_clumsy_network_sharing,
    rollback_clumsy_ics,
)
from tools.utils_gui import restart_zubcut

_UPDATE_BTN_QSS_FALLBACK = (
    'QPushButton#btnUpdate { background-color: #1a3d28; color: #d8f0e4; font-weight: bold; '
    'border: 1px solid #2d5738; border-radius: 4px; }'
)


def _coerce_scan_counts(s: dict) -> dict:
    """count/threads must be ints in range; bad JSON or types would break range() / ThreadPool."""
    out = dict(s) if s else {}
    for key, default, lo, hi in (
        ('count', 25, 25, 255),
        ('threads', 12, 5, 255),
    ):
        try:
            v = int(out.get(key, default))
            out[key] = max(lo, min(hi, v))
        except (TypeError, ValueError):
            out[key] = default
    return out


def _capped_settings_window_height(
    content_h: int,
    avail_h: int,
    *,
    margin: int = 48,
    min_h: int = 420,
) -> int:
    """Clamp Settings height so short / high-DPI screens keep Update reachable."""
    try:
        content_h = int(content_h)
        avail_h = int(avail_h)
    except (TypeError, ValueError):
        content_h, avail_h = 620, 900
    hard_floor = 280
    preferred = max(hard_floor, int(min_h), content_h)
    cap = max(hard_floor, int(avail_h) - int(margin))
    return max(hard_floor, min(preferred, cap))


def _settings_keybind_mono_font() -> QFont:
    """Match main #tableScan: readable monospace, normal weight (Fusion/qdark often bolds shortcuts)."""
    mono = 'Menlo' if sys.platform == 'darwin' else 'Consolas'
    f = QFont(mono, 11)
    f.setStyleHint(QFont.Monospace)
    f.setFixedPitch(True)
    f.setBold(False)
    return f


class _UpdateBannerPollThread(QThread):
    """Fetch update availability off the GUI thread (showEvent must not block on HEAD)."""

    done = pyqtSignal(bool, str)

    def run(self):
        from tools.updater_core import get_update_status

        try:
            avail, label = get_update_status(force_refresh=True)
        except Exception:
            return
        # None = indeterminate (API/republish race); keep existing green hint.
        if avail is None:
            return
        self.done.emit(bool(avail), str(label or ''))


class _ClumsyIcsPrepThread(QThread):
    """Run Clumsy ICS PowerShell off the Settings GUI thread (can take 30–60s)."""

    finished = pyqtSignal(bool, str)

    def __init__(self, enable: bool):
        super().__init__()
        self._enable = bool(enable)

    def run(self):
        try:
            if self._enable:
                from tools.clumsy_ics import ensure_clumsy_ics_enabled

                ok, detail = ensure_clumsy_ics_enabled()
            else:
                from tools.clumsy_ics import repair_clumsy_network_sharing

                ok, detail = repair_clumsy_network_sharing()
            self.finished.emit(bool(ok), str(detail or ''))
        except Exception as e:
            self.finished.emit(False, str(e))


class _WheelSafeComboBox(QComboBox):
    """Ignore mouse wheel unless the user clicked the combo (avoids accidental index changes)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.ClickFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


def _apply_wheel_safe_combo(combo: QComboBox) -> None:
    """Same wheel policy for combos created by the .ui file (e.g. network interface)."""
    combo.setFocusPolicy(Qt.ClickFocus)

    class _WheelGuard(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Wheel and not combo.hasFocus():
                event.ignore()
                return True
            return False

    guard = _WheelGuard(combo)
    combo.installEventFilter(guard)
    combo._wheel_guard = guard  # keep reference


def _normalized_update_channel_setting() -> str:
    c = str(UPDATE_CHANNEL or 'experimental').strip().lower()
    if c in ('stable', 'paid'):
        c = 'main'
    if c not in ('main', 'experimental'):
        c = 'experimental'
    return c


def _channel_kind_label(channel: str) -> str:
    """User-facing build line (avoid internal channel codenames in dialogs)."""
    c = str(channel or '').strip().lower()
    if c == 'experimental':
        return 'Experimental / testing build'
    return 'ZubCut'


class Settings(FramelessResizableMixin, QMainWindow, Ui_MainWindow):
    def __init__(self, app, icon):
        super().__init__()
        self.app = app

        # Setup UI
        self.icon = icon
        self.setWindowIcon(icon)
        self.setupUi(self)
        self.setObjectName('zubcutAuxiliaryWindow')
        _apply_wheel_safe_combo(self.comboInterface)
        self._fix_network_interface_combo()
        self._install_percent_keybind_row()
        self._install_clumsy_controls()
        if _normalized_update_channel_setting() in ('main', 'experimental'):
            self.btnLicenseSignIn = QPushButton('Sign in or change license…', self.centralwidget)
            self.btnLicenseSignIn.setObjectName('btnLicenseSignIn')
            self.btnLicenseSignIn.setMinimumHeight(34)
            self.gridLayout.addWidget(self.btnLicenseSignIn, 7, 0, 1, 4)
            self.btnLicenseSignIn.clicked.connect(self._on_license_sign_in)
        self._install_settings_scroll_shell()
        self.loadInterfaces(use_cache=True)
        QTimer.singleShot(0, self._load_interfaces_background)

        # Apply saved values after first paint (constructor must not block on ipconfig).
        QTimer.singleShot(0, self.currentSettings)

        self.sliderCount.valueChanged.connect(self.spinCount.setValue)
        self.spinCount.valueChanged.connect(self.sliderCount.setValue)
        self.sliderThreads.valueChanged.connect(self.spinThreads.setValue)
        self.spinThreads.valueChanged.connect(self.sliderThreads.setValue)
        self.btnApply.clicked.connect(self.Apply)
        self.btnDefaults.clicked.connect(self.Defaults)
        self.btnUpdate.clicked.connect(self.checkUpdate)
        self._update_channel = _normalized_update_channel_setting()
        self._update_published_label = ''
        self._update_available = False
        self._update_banner_poll_thread = None
        self._clumsy_widgets_sig = None
        self._layout_size_locked = False
        self.btnUpdate.setText(self._update_button_text())
        self._sync_update_button_tooltip()
        # Defer first HEAD check so it does not run synchronously during main window construction.
        QTimer.singleShot(0, self._schedule_update_banner_refresh)
        QTimer.singleShot(0, self._refresh_clumsy_settings_widgets)
        QTimer.singleShot(0, self._apply_clumzy_unavailable_controls)
        self.chkAutoupdate.setToolTip(
            'Automatic startup updates are not used. Use Install Latest Build below when you want to update.'
        )
        # Deprecated/unused: remove from UI to avoid confusion.
        self.chkAutoupdate.hide()
        # Killed-device persistence is deprecated: always off (users can re-kill manually).
        self.chkRemember.hide()
        self.chkRemember.setEnabled(False)

        setup_frameless_main_window(self, self.windowTitle(), self.icon, maximizable=False)
        register_window_surface_effects(self)
        QTimer.singleShot(0, self._finalize_settings_layout)

    def _install_clumsy_controls(self):
        self.chkClumsy = QCheckBox('Clumzy Mode', self.gridLayoutWidget_2)
        self.chkClumsy.setToolTip(
            'Restart ZubCut into Clumzy Mode: the Clumzy packet engine on Mobile Hotspot '
            '(filter true, all forwarded packets). Normal ARP Kill is not used. '
            'Turn Windows Mobile Hotspot ON first. Run ZubCut as Administrator.'
        )
        self.lblClumsyPath = QLabel('Clumzy Mode uses the bundled Clumzy engine', self.gridLayoutWidget_2)
        self.lblClumsyPath.setWordWrap(True)
        self.lblClumsyPath.setToolTip(
            'Clumzy Mode replaces the main window. Kill / Lag Switch / Dupe use Clumzy Freeze '
            'on all hotspot traffic. Turn the checkbox off and restart to return to normal ZubCut.'
        )
        self.btnClumsyInstall = QPushButton('Install Clumzy mode…', self.gridLayoutWidget_2)
        self.btnClumsyInstall.setToolTip(
            'Downloads the latest experimental installer (includes Clumzy / WinDivert).'
        )
        self.gridLayout_3.addWidget(self.chkClumsy, 2, 0, 1, 2)
        self.gridLayout_3.addWidget(self.btnClumsyInstall, 2, 2, 1, 2)
        self.gridLayout_3.addWidget(self.lblClumsyPath, 3, 0, 1, 4)
        self._relayout_misc_group()
        self.groupBox_keys.setMinimumHeight(140)
        self._clumsy_toggle_guard = False
        self.chkClumsy.stateChanged.connect(self._on_clumsy_checkbox_changed)
        self.btnClumsyInstall.clicked.connect(self._on_clumsy_install_clicked)

    def _fix_network_interface_combo(self) -> None:
        """Visible adapter list — combo popups fail in this frameless + scroll window."""
        combo = self.comboInterface
        combo.setMinimumHeight(30)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        combo.hide()
        inner = getattr(self, 'horizontalLayoutWidget_2', None)
        gb = getattr(self, 'groupBox_4', None)
        if inner is not None:
            inner.hide()
        if gb is None:
            return
        if gb.layout() is None:
            lay = QVBoxLayout(gb)
            lay.setContentsMargins(10, 22, 10, 8)
            lay.setSpacing(6)
        else:
            lay = gb.layout()
        hint = QLabel(
            'This PC’s Wi‑Fi or Ethernet. '
            'Leftover Mobile Hotspot adapters stay hidden unless Clumzy Mode is on.',
            gb,
        )
        hint.setObjectName('lblIfaceHint')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #9a9a9a;')
        lst = QListWidget(gb)
        lst.setObjectName('listNetworkInterface')
        lst.setSelectionMode(QAbstractItemView.SingleSelection)
        lst.setMinimumHeight(88)
        lst.setMaximumHeight(148)
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lst.currentItemChanged.connect(self._sync_iface_combo_from_list)
        self.lblIfaceHint = hint
        self.listNetworkInterface = lst
        self._iface_picker_guard = False
        lay.addWidget(hint)
        lay.addWidget(lst)
        gb.setMinimumHeight(max(168, gb.minimumHeight()))

    def _relayout_misc_group(self) -> None:
        """Misc. group was a fixed-size child widget in ui_settings; expand for Clumsy rows."""
        gb = self.groupBox_3
        inner = self.gridLayoutWidget_2
        inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        if gb.layout() is None:
            lay = QVBoxLayout(gb)
            lay.setContentsMargins(10, 22, 10, 8)
            lay.setSpacing(4)
            lay.addWidget(inner)
        gb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay_inner = inner.layout()
        if lay_inner is not None:
            inner_h = lay_inner.minimumSize().height()
            inner.setMinimumHeight(max(200, inner_h))
        else:
            inner.setMinimumHeight(200)
        gb.setMinimumHeight(inner.minimumHeight() + 32)

    def _install_settings_scroll_shell(self) -> None:
        """Scrollable body + fixed footer so Update stays visible on short screens."""
        if getattr(self, '_settings_scroll_installed', False):
            return
        groups = [
            self.groupBox_4,
            self.groupBox_2,
            self.groupBox_3,
            self.groupBox_keys,
        ]
        footer_btns = [self.btnDefaults, self.btnApply, self.btnUpdate]
        license_btn = getattr(self, 'btnLicenseSignIn', None)
        if license_btn is not None:
            footer_btns.append(license_btn)

        for w in list(groups) + list(footer_btns):
            try:
                self.gridLayout.removeWidget(w)
            except Exception:
                pass

        # Detach the designer layout so we can rebuild centralwidget cleanly.
        old = self.centralwidget.layout()
        if old is not None:
            while old.count():
                old.takeAt(0)
            QWidget().setLayout(old)

        root = QVBoxLayout(self.centralwidget)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)
        self._settings_root_layout = root

        scroll = QScrollArea(self.centralwidget)
        scroll.setObjectName('zubcutSettingsScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._settings_scroll = scroll

        inner = QWidget(scroll)
        inner.setObjectName('zubcutSettingsScrollInner')
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 4, 0)
        inner_lay.setSpacing(8)
        for gb in groups:
            gb.setParent(inner)
            gb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            inner_lay.addWidget(gb)
        inner_lay.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        footer = QWidget(self.centralwidget)
        footer.setObjectName('zubcutSettingsFooter')
        footer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        foot = QGridLayout(footer)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(6)
        self.btnDefaults.setParent(footer)
        self.btnApply.setParent(footer)
        self.btnUpdate.setParent(footer)
        foot.addWidget(self.btnDefaults, 0, 0, 1, 2)
        foot.addWidget(self.btnApply, 0, 2, 1, 2)
        foot.addWidget(self.btnUpdate, 1, 0, 1, 4)
        if license_btn is not None:
            license_btn.setParent(footer)
            foot.addWidget(license_btn, 2, 0, 1, 4)
        self._settings_footer = footer
        root.addWidget(footer, 0)
        self._settings_scroll_installed = True

    def _settings_available_height(self) -> int:
        scr = None
        try:
            scr = self.screen()
        except Exception:
            scr = None
        if scr is None:
            try:
                scr = QApplication.primaryScreen()
            except Exception:
                scr = None
        if scr is None:
            return 900
        try:
            return int(scr.availableGeometry().height())
        except Exception:
            return 900

    def _finalize_settings_layout(self, *, force: bool = False) -> None:
        """Size the window after Clumsy rows are in the layout; never taller than the screen."""
        if not force and getattr(self, '_layout_size_locked', False):
            return
        if not getattr(self, '_settings_scroll_installed', False):
            self._install_settings_scroll_shell()
        self._relayout_misc_group()
        self.groupBox_keys.setMinimumHeight(140)
        min_w = 430
        # Content hint includes footer; cap so short / scaled displays keep Update on-screen.
        content_h = max(620, int(self.sizeHint().height()))
        target_h = _capped_settings_window_height(content_h, self._settings_available_height())
        # Allow shrinking via scroll; do not lock a fixed size taller than the screen.
        self.setMinimumSize(min_w, min(420, target_h))
        self.setMaximumSize(16777215, max(target_h, self._settings_available_height()))
        self.resize(max(min_w, self.width() or min_w), target_h)
        self._layout_size_locked = True

    def _refresh_clumsy_settings_widgets(self):
        if not sys.platform.startswith('win'):
            sig = ('hidden',)
            if sig == getattr(self, '_clumsy_widgets_sig', None):
                return
            self._clumsy_widgets_sig = sig
            self.chkClumsy.hide()
            self.btnClumsyInstall.hide()
            self.lblClumsyPath.hide()
            self._layout_size_locked = False
            return
        bundle = clumsy_bundle_offered()
        driver_ok = windivert_driver_installed()
        incomplete = clumsy_bundle_incomplete()
        try:
            clumsy_on = bool(self.chkClumsy.isChecked())
        except Exception:
            clumsy_on = False
        shell = bool(getattr(self.app, 'clumzy_mode_shell', False))
        sig = (bundle, driver_ok, incomplete, clumsy_on, shell)
        if sig == getattr(self, '_clumsy_widgets_sig', None):
            return
        self._clumsy_widgets_sig = sig
        self._layout_size_locked = False
        if bundle and driver_ok:
            self.btnClumsyInstall.hide()
            self.chkClumsy.show()
            self.lblClumsyPath.show()
            self._update_clumsy_path_label()
        elif incomplete:
            self.chkClumsy.hide()
            self.btnClumsyInstall.show()
            self.btnClumsyInstall.setText('Repair Clumzy / WinDivert')
            self.lblClumsyPath.hide()
        else:
            self.chkClumsy.hide()
            self.btnClumsyInstall.show()
            self.btnClumsyInstall.setText('Install Clumzy Mode')
            self.lblClumsyPath.hide()
        self._apply_clumzy_unavailable_controls()

    def _apply_clumzy_unavailable_controls(self) -> None:
        """Grey out Settings pages that have no effect while Clumzy Mode is the shell."""
        if not getattr(self.app, 'clumzy_mode_shell', False):
            return
        tip = 'Not used in Clumzy Mode. Turn Clumzy Mode off to use LAN scan settings.'
        for w in (self.groupBox_4, self.groupBox_2):
            if w is None:
                continue
            w.setEnabled(False)
            w.setToolTip(tip)
            if w.graphicsEffect() is None:
                dim = QGraphicsOpacityEffect(w)
                dim.setOpacity(0.45)
                w.setGraphicsEffect(dim)

    def _update_clumsy_path_label(self) -> None:
        self.lblClumsyPath.setText(
            'Clumzy Mode: Clumzy engine on hotspot (all forwarded packets). '
            'Turn Mobile Hotspot ON in Windows first.'
        )

    def _on_clumsy_checkbox_changed(self, _state):
        if self._clumsy_toggle_guard:
            return
        if not self.chkClumsy.isVisible():
            return
        new_v = self.chkClumsy.isChecked()
        try:
            old_v = bool(get_settings('clumsy_mode'))
        except Exception:
            old_v = False
        if new_v == old_v:
            return
        if MsgType.WARN(
            self,
            'Restart ZubCut',
            'Changing Clumzy Mode requires a full restart.\nRestart now?',
            Buttons.YES | Buttons.NO,
        ) == Buttons.NO:
            self._clumsy_toggle_guard = True
            self.chkClumsy.setChecked(old_v)
            self._clumsy_toggle_guard = False
            return
        try:
            from tools.clumsy_ics import mark_clumsy_settings_restart_pending

            mark_clumsy_settings_restart_pending()
            set_settings_many(
                {
                    'clumsy_persist_across_restart': True,
                    'clumsy_mode': new_v,
                }
            )
            restart_zubcut(self.app)
        except Exception as exc:
            from tools.user_errors import format_build_version_hint

            self._clumsy_toggle_guard = True
            self.chkClumsy.setChecked(old_v)
            self._clumsy_toggle_guard = False
            try:
                set_settings('clumsy_mode', old_v)
            except Exception:
                pass
            MsgType.ERROR(
                self,
                'Clumzy Mode',
                'ZubCut hit an error while changing Clumzy Mode.\n\n'
                f'{exc}\n\n'
                'Turn Mobile Hotspot ON in Windows Settings first, wait for it to start, '
                'then try again. If this keeps happening, send the newest '
                f'%TEMP%\\{APP_BUNDLE_NAME}-crash-ZC-*.log file.'
                f'{format_build_version_hint()}',
                Buttons.OK,
            )

    def _begin_clumsy_mode_toggle(self, new_v: bool, old_v: bool) -> None:
        self._pending_clumsy_new = bool(new_v)
        self._pending_clumsy_old = bool(old_v)
        label = 'Preparing Clumzy Mode…' if new_v else 'Restoring network sharing…'
        dlg = QProgressDialog(label, None, 0, 0, self)
        dlg.setWindowTitle('Clumzy Mode')
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        dlg.show()
        self._clumsy_prep_dialog = dlg
        self.chkClumsy.setEnabled(False)
        th = _ClumsyIcsPrepThread(new_v)
        self._clumsy_prep_thread = th
        th.finished.connect(self._on_clumsy_ics_prep_finished)
        th.start()

    def _on_clumsy_ics_prep_finished(self, prep_ok: bool, prep_detail: str) -> None:
        from tools.user_errors import format_build_version_hint

        dlg = getattr(self, '_clumsy_prep_dialog', None)
        if dlg is not None:
            dlg.close()
            self._clumsy_prep_dialog = None
        self.chkClumsy.setEnabled(True)
        th = getattr(self, '_clumsy_prep_thread', None)
        if th is not None:
            th.wait(200)
            self._clumsy_prep_thread = None
        new_v = bool(getattr(self, '_pending_clumsy_new', False))
        old_v = bool(getattr(self, '_pending_clumsy_old', False))
        try:
            self._apply_clumsy_mode_toggle_after_prep(
                new_v, old_v, bool(prep_ok), str(prep_detail or '')
            )
        except Exception as exc:
            self._clumsy_toggle_guard = True
            self.chkClumsy.setChecked(old_v)
            self._clumsy_toggle_guard = False
            try:
                set_settings('clumsy_mode', old_v)
            except Exception:
                pass
            MsgType.ERROR(
                self,
                'Clumzy Mode',
                'ZubCut hit an error while changing Clumzy Mode.\n\n'
                f'{exc}\n\n'
                'Turn Mobile Hotspot ON in Windows Settings first, wait for it to start, '
                'then try again. If this keeps happening, send the newest '
                f'%TEMP%\\{APP_BUNDLE_NAME}-crash-ZC-*.log file.'
                f'{format_build_version_hint()}',
                Buttons.OK,
            )

    def _apply_clumsy_mode_toggle_after_prep(
        self,
        new_v: bool,
        old_v: bool,
        prep_ok: bool,
        prep_detail: str,
    ) -> None:
        if new_v:
            if not prep_ok:
                detail = format_clumsy_ics_error(
                    prep_detail or 'Unknown error.',
                    topology=read_clumsy_topology(),
                )
                from tools.user_errors import format_build_version_hint

                MsgType.WARN(
                    self,
                    'Clumzy Mode',
                    'Could not enable Clumzy Mode.\n\n' + detail + format_build_version_hint(),
                    Buttons.OK,
                )
                self._clumsy_toggle_guard = True
                self.chkClumsy.setChecked(False)
                self._clumsy_toggle_guard = False
                try:
                    set_settings('clumsy_mode', False)
                except Exception:
                    pass
                return
            self._update_clumsy_path_label()
            try:
                cur = (get_settings('iface') or '').strip()
            except Exception:
                cur = ''
            set_settings('iface_before_clumsy', cur)
        else:
            ok = prep_ok
            detail = prep_detail
            if not ok:
                if (
                    MsgType.WARN(
                        self,
                        'Clumzy Mode',
                        'Could not restore sharing automatically.\n\n'
                        + (detail or 'Unknown error.')
                        + '\n\nRun hotspot / sharing repair now?',
                        Buttons.YES | Buttons.NO,
                    )
                    == Buttons.YES
                ):
                    rok, rdetail = repair_clumsy_network_sharing()
                    if not rok:
                        MsgType.ERROR(
                            self,
                            'Repair failed',
                            rdetail or detail or 'Unknown error.',
                            Buttons.OK,
                        )
                        self._clumsy_toggle_guard = True
                        self.chkClumsy.setChecked(old_v)
                        self._clumsy_toggle_guard = False
                        return
                    detail = rdetail
                else:
                    self._clumsy_toggle_guard = True
                    self.chkClumsy.setChecked(old_v)
                    self._clumsy_toggle_guard = False
                    return
            try:
                prev = (get_settings('iface_before_clumsy') or '').strip()
            except Exception:
                prev = ''
            if prev:
                set_settings('iface', prev)
            set_settings('iface_before_clumsy', '')
        mark_clumsy_settings_restart_pending()
        try:
            set_settings_many(
                {
                    'clumsy_persist_across_restart': True,
                    'clumsy_mode': new_v,
                }
            )
        except Exception:
            try:
                set_settings('clumsy_persist_across_restart', True)
            except Exception:
                pass
            set_settings('clumsy_mode', new_v)
        restart_zubcut(self.app)

    def _on_clumsy_install_clicked(self):
        url = (UPDATE_DOWNLOAD_URL_EXPERIMENTAL or '').strip()
        if not url:
            MsgType.WARN(
                self,
                'Download not configured',
                'No experimental installer URL is configured in this build.',
                Buttons.OK,
            )
            return
        if MsgType.WARN(
            None,
            'Install Clumzy Mode',
            (
                'This downloads the latest experimental ZubCut installer '
                '(with optional WinDivert / Clumzy components).\n'
                'Continue?'
            ),
            Buttons.YES | Buttons.NO,
        ) == Buttons.NO:
            return
        try:
            path = download_update_with_progress_dialog(
                self,
                url,
                expected_size=0,
                refresh_metadata_first=True,
            )
            if path is None:
                return
            launch_installer(path)
            self.app.quit_all()
        except Exception as e:
            MsgType.ERROR(
                None,
                'Download failed',
                f'Could not download installer.\n{e}',
                Buttons.OK,
            )

    def _install_percent_keybind_row(self):
        self.labelKeyPctCut = QLabel('Percent Cut toggle (main window)', self.groupBox_keys)
        self.keySeqPctCut = QKeySequenceEdit(self.groupBox_keys)
        self.keySeqPctCut.setObjectName('keySeqPctCut')
        self.formLayout_keys.addRow(self.labelKeyPctCut, self.keySeqPctCut)

    def _on_license_sign_in(self):
        from gui.license_signin import run_license_signin
        from tools.license_offline import load_and_validate_installed_license

        if not run_license_signin(self, self.icon):
            return
        if load_and_validate_installed_license().ok:
            MsgType.INFO(
                self,
                'License',
                'License saved. Restart ZubCut if the app still shows an old license message.',
            )
        else:
            MsgType.WARN(
                self,
                'License',
                'The file could not be verified. Try again or contact your administrator.',
            )

    def showEvent(self, event):
        super().showEvent(event)
        try:
            if getattr(self, 'app', None) is not None and not getattr(
                self.app, 'clumzy_mode_shell', False
            ):
                self.app._reconcile_network_adapter(log=False)
        except Exception:
            pass
        self._load_interfaces_foreground()
        self.comboInterface.clearFocus()
        self.comboInterface.hidePopup()
        if self._iface_combo_is_placeholder():
            self._load_interfaces_foreground()
        elif self.comboInterface.count() == 0:
            self._load_interfaces_background()
        self._refresh_clumsy_settings_widgets()
        self._apply_clumzy_unavailable_controls()
        self._finalize_settings_layout()
        self._schedule_update_banner_refresh()
        el = getattr(self, 'app', None)
        if el is not None and hasattr(el, '_sync_settings_gear_update_hint'):
            QTimer.singleShot(0, el._sync_settings_gear_update_hint)

    def Apply(self, silent_apply=False):
        nicknames = Nicknames()

        count         =  self.spinCount.value()
        threads       =  self.spinThreads.value()
        is_autostart  =  self.chkAutostart.isChecked()
        is_minimized  =  self.chkMinimized.isChecked()
        # Deprecated feature: never persist killed devices across restarts.
        is_remember   =  False
        is_autoupdate =  self.chkAutoupdate.isChecked()
        iface = self.comboInterface.currentData()
        if iface in (None, ''):
            iface = self.comboInterface.currentText()

        def _portable_key(ks_edit):
            qs = ks_edit.keySequence()
            if qs.isEmpty():
                return None
            return qs.toString(QKeySequence.PortableText)

        k_kill = _portable_key(self.keySeqKill)
        k_lag = _portable_key(self.keySeqLag)
        k_dupe = _portable_key(self.keySeqDupe)
        k_pct = _portable_key(self.keySeqPctCut)
        if not k_kill or not k_lag or not k_dupe or not k_pct:
            MsgType.WARN(
                self,
                'Keyboard shortcuts',
                'Each shortcut must have a key assigned.',
                Buttons.OK,
            )
            return
        if len({k_kill, k_lag, k_dupe, k_pct}) < 4:
            MsgType.WARN(
                self,
                'Keyboard shortcuts',
                'Kill, Lag Switch, Dupe, and Percent Cut shortcuts must all be different.',
                Buttons.OK,
            )
            return

        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.join(os.getcwd(), APP_EXE_NAME)
        if is_autostart:
            add_to_startup(exe_path)
        else:
            remove_from_startup()

        # Persistence removed: keep settings clean; killed devices are session-only.
        killed_all = []

        try:
            show_mac = bool(get_settings('show_scan_mac_column'))
            show_ven = bool(get_settings('show_scan_vendor_column'))
            traffic_pct = int(get_settings('traffic_percent'))
        except Exception:
            try:
                s0 = import_settings()
            except Exception:
                s0 = {}
            show_mac = bool(s0.get('show_scan_mac_column', False))
            show_ven = bool(s0.get('show_scan_vendor_column', False))
            try:
                traffic_pct = int(s0.get('traffic_percent', 50))
            except (TypeError, ValueError):
                traffic_pct = 50

        try:
            clumsy_mode = bool(get_settings('clumsy_mode'))
        except Exception:
            clumsy_mode = False

        try:
            iface_stash = str(get_settings('iface_before_clumsy') or '')
        except Exception:
            iface_stash = ''

        set_settings_many(
            {
                'count': count,
                'autostart': is_autostart,
                'minimized': is_minimized,
                'remember': is_remember,
                'killed': killed_all,
                'autoupdate': is_autoupdate,
                'threads': threads,
                'iface': iface,
                'iface_before_clumsy': iface_stash,
                'nicknames': nicknames.nicknames_database,
                'key_kill': k_kill,
                'key_lag': k_lag,
                'key_dupe': k_dupe,
                'key_pctcut': k_pct,
                'show_scan_mac_column': show_mac,
                'show_scan_vendor_column': show_ven,
                'traffic_percent': traffic_pct,
                'clumsy_mode': clumsy_mode,
            }
        )

        if getattr(self.app, 'clumzy_mode_shell', False):
            if hasattr(self.app, 'refresh_keyboard_shortcuts_from_settings'):
                try:
                    self.app.refresh_keyboard_shortcuts_from_settings()
                except Exception:
                    pass
            if not silent_apply:
                MsgType.INFO(
                    self,
                    'Apply Settings',
                    'New settings have been applied.',
                )
            self.close()
            return

        old_iface = self.app.scanner.iface.name
        
        self.app.iface = get_iface_by_name(iface)
        self.apply_app_settings()
        # Fix horizontal headerfont reverts to normal after applying settings
        mono_font = 'Menlo' if __import__('sys').platform == 'darwin' else 'Consolas'
        self.app.tableScan.horizontalHeader().setFont(QFont(mono_font, 11))

        if not silent_apply:
            MsgType.INFO(
                self,
                'Apply Settings',
                'New settings have been applied.'
            )
        
        if old_iface != iface:
            MsgType.INFO(
                self,
                'Interface Changed',
                f'{APP_DISPLAY_NAME} will restart to apply new interface.'
            )

            restart_zubcut(self.app)
        
        self.close()

    def Defaults(self):
        if MsgType.WARN(
            self,
            'Default settings',
            'All settings will be reset to default.\nAre you sure?',
            Buttons.YES | Buttons.NO
        ) == Buttons.NO:
            return
        
        nickname_prompt = MsgType.WARN(
            self,
            'Default settings',
            'Do you want to reset devices nicknames?',
            Buttons.YES | Buttons.NO
        )
        
        # Check if user wants to keep nicknames or not
        if nickname_prompt == Buttons.NO:
            nicknames = Nicknames()
            vals = SETTINGS_VALS[:]
            ix_n = SETTINGS_KEYS.index('nicknames')
            ix_ip = SETTINGS_KEYS.index('nickname_last_ip')
            vals[ix_n] = nicknames.nicknames_database
            try:
                vals[ix_ip] = dict(get_settings('nickname_last_ip') or {})
            except Exception:
                vals[ix_ip] = {}
            export_settings(vals)
        else:
            export_settings()
        
        self.currentSettings()
        self.Apply()

    def apply_app_settings(self):
        """Push Settings values into the running main window."""
        s = _coerce_scan_counts(import_settings())
        self.currentSettings()
        main = self.app

        main.minimize = s['minimized']
        main.remember = False
        main.autoupdate = s['autoupdate']
        main.scanner.device_count = s['count']
        main.scanner.max_threads = s['threads']

        main.scanner.iface = get_iface_by_name(s['iface'])
        main.killer.iface = get_iface_by_name(s['iface'])
        try:
            # Settings Apply is on the GUI thread — skip getmacbyip (~4s).
            main.scanner.refresh_local_topology(allow_scapy_probe=False)
            main.killer.iface = main.scanner.iface
            main.killer.router = getattr(main.scanner, 'router', None) or main.killer.router
            main.scanner.add_me()
            main.scanner.add_router()
            main.showDevices()
            if hasattr(main, '_schedule_npcap_prewarm'):
                main._schedule_npcap_prewarm('settings')
        except Exception:
            pass

        qt_app = QApplication.instance()
        if qt_app is not None:
            qt_app.setStyleSheet(self.styleSheet())
        main._repolish_chrome_pushbuttons()
        main.setStyleSheet('')
        main.about_window.setStyleSheet('')
        for _dlg in (
            getattr(main, 'lag_switch_dialog', None),
            getattr(main, 'dupe_switch_dialog', None),
            getattr(main, 'advanced_lag_settings_dialog', None),
        ):
            if _dlg is not None:
                _dlg.setStyleSheet('')
        _w = [
            main,
            main.about_window,
            self,
            main.device_window,
            main.traffic_window,
            getattr(main, 'kill_flows_window', None),
        ]
        _w = [w for w in _w if w is not None]
        _w.extend(
            d
            for d in (
                getattr(main, 'lag_switch_dialog', None),
                getattr(main, 'dupe_switch_dialog', None),
                getattr(main, 'advanced_lag_settings_dialog', None),
            )
            if d is not None
        )
        sync_translucent_chrome(_w)
        main.refresh_keyboard_shortcuts_from_settings()
        main._sync_scan_table_column_settings()

    def currentSettings(self):
        s = _coerce_scan_counts(import_settings())
        self.chkAutostart.setChecked(s['autostart'])
        self.chkMinimized.setChecked(s['minimized'])
        self.chkRemember.setChecked(False)
        self.chkAutoupdate.setEnabled(False)
        self.chkAutoupdate.setChecked(False)
        self.spinCount.setValue(s['count'])
        self.spinThreads.setValue(s['threads'])
        self.sliderCount.setValue(s['count'])
        self.sliderThreads.setValue(s['threads'])
        
        if not s['iface']:
            try:
                ifaces = get_ifaces_cached()
            except Exception:
                ifaces = []
            pick = None
            for iface in ifaces:
                lip = (getattr(iface, 'ip', None) or '').strip()
                if lip and lip not in ('127.0.0.1', '0.0.0.0'):
                    pick = iface
                    break
            if pick is None and ifaces:
                pick = ifaces[0]
            if pick is not None:
                set_settings('iface', pick.name)
                s = import_settings()
        
        from tools.utils import resolve_settings_iface_name

        saved = str(s.get('iface') or '').strip()
        display = resolve_settings_iface_name(saved) or saved
        # Prefer the repaired live NIC. findData(saved) would keep a leftover
        # hotspot adapter selected whenever it is still in the list.
        idx = self.comboInterface.findData(display)
        if idx < 0:
            idx = self.comboInterface.findData(saved)
        if idx < 0:
            idx = self.comboInterface.findText(display, Qt.MatchFixedString)
        if idx >= 0:
            self.comboInterface.setCurrentIndex(idx)
            self._select_iface_list_row(idx)
        if display and display != saved:
            try:
                set_settings('iface', display)
            except Exception:
                pass

        self.keySeqKill.setKeySequence(keyseq_from_setting(s.get('key_kill'), Qt.Key_L))
        self.keySeqLag.setKeySequence(keyseq_from_setting(s.get('key_lag'), Qt.Key_M))
        self.keySeqDupe.setKeySequence(keyseq_from_setting(s.get('key_dupe'), Qt.Key_P))
        self.keySeqPctCut.setKeySequence(keyseq_from_setting(s.get('key_pctcut'), Qt.Key_K))

        try:
            clumsy_mode = bool(s.get('clumsy_mode', False))
        except Exception:
            clumsy_mode = False
        self._clumsy_toggle_guard = True
        self.chkClumsy.setChecked(clumsy_mode)
        self._clumsy_toggle_guard = False
        self._refresh_clumsy_settings_widgets()
        self._apply_clumzy_unavailable_controls()

        self._apply_keybind_section_fonts()
        self.setStyleSheet(zubcut_dark_stylesheet())

    def _apply_keybind_section_fonts(self):
        f = _settings_keybind_mono_font()
        for w in (
            self.groupBox_keys,
            self.labelKeyKill,
            self.labelKeyLag,
            self.labelKeyDupe,
            self.labelKeyPctCut,
            self.keySeqKill,
            self.keySeqLag,
            self.keySeqDupe,
            self.keySeqPctCut,
        ):
            w.setFont(f)
        for ks in (self.keySeqKill, self.keySeqLag, self.keySeqDupe, self.keySeqPctCut):
            for le in ks.findChildren(QLineEdit):
                le.setFont(f)
    
    def checkUpdate(self):
        begin_updater_debug_session('settings.checkUpdate')
        updater_log('checkUpdate: entered')
        # Do not force_refresh here — GitHub API on the GUI thread delayed the confirm
        # dialog by seconds. Use cache/constants for instant popup; refresh in the
        # download worker after the user confirms.
        candidates = installer_download_candidates(force_refresh=False)
        url = (candidates[0] if candidates else '') or (selected_update_url() or '')
        fallback_urls = candidates[1:] if len(candidates) > 1 else None
        if not url:
            MsgType.WARN(
                self,
                'Update URL Missing',
                (
                    'This build is not configured with a download link for updates.\n'
                    '(Developers: set the matching UPDATE_DOWNLOAD_URL_* entry in src/constants.py.)'
                ),
                Buttons.OK,
            )
            return
        if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
            MsgType.WARN(
                self,
                'Invalid Update URL',
                (
                    'Update URL must start with http:// or https://\n'
                    f'Build: {_channel_kind_label(self._update_channel)}'
                ),
                Buttons.OK,
            )
            return

        # Parent=None: same frameless-window + modal child crash class as QProgressDialog on Windows.
        confirm = MsgType.WARN(
            None,
            'Install Latest Build',
            (
                f'This will install the latest {self._channel_label()} build.\n'
                'You will see download progress, then a setup window while it installs, '
                'and ZubCut will start again when finished.\n'
                'Continue?'
            ),
            Buttons.YES | Buttons.NO,
        )
        if confirm == Buttons.NO:
            updater_log('checkUpdate: user declined')
            return

        updater_log('checkUpdate: user confirmed, disabling button')
        self.btnUpdate.setEnabled(False)
        self.btnUpdate.setText('Downloading…')
        quit_for_update = False
        try:
            updater_log('checkUpdate: calling download_update_with_progress_dialog')
            path = download_update_with_progress_dialog(
                self,
                url,
                expected_size=0,
                fallback_urls=fallback_urls,
                refresh_metadata_first=True,
            )
            updater_log('checkUpdate: download returned path=%r', path)
            if path is None:
                return
            updater_log('checkUpdate: launch_installer')
            launch_installer(path)
            quit_for_update = True
            updater_log('checkUpdate: quit_all')
            self.app.quit_all()
        except Exception as e:
            updater_log('checkUpdate: exception %s', e, exc_info=True)
            MsgType.ERROR(
                None,
                'Update Failed',
                (
                    f'{format_updater_error_message(e)}\n\n'
                    f'Details were appended to:\n{updater_log_paths_hint()}'
                ),
                Buttons.OK,
            )
        finally:
            # quit_all() destroys this window; touching widgets here crashes.
            if quit_for_update:
                return
            try:
                if self.isVisible():
                    self.btnUpdate.setEnabled(True)
                    self.btnUpdate.setText(self._update_button_text())
                    self._sync_update_button_tooltip()
                    self._apply_update_button_style()
            except RuntimeError:
                pass

    def _channel_label(self):
        return 'experimental' if self._update_channel == 'experimental' else APP_DISPLAY_NAME

    def _schedule_update_banner_refresh(self) -> None:
        """Network update check off the GUI thread (never block Settings open)."""
        prev = getattr(self, '_update_banner_poll_thread', None)
        if prev is not None:
            try:
                if prev.isRunning():
                    return
            except RuntimeError:
                self._update_banner_poll_thread = None
        poll = _UpdateBannerPollThread()
        self._update_banner_poll_thread = poll

        def _apply(avail: bool, label: str) -> None:
            try:
                self.apply_update_banner_state(avail, label)
            except Exception:
                pass
            el = getattr(self, 'app', None)
            if el is not None:
                try:
                    el._update_hint_available = bool(avail)
                except Exception:
                    pass
                if hasattr(el, '_sync_settings_gear_update_hint'):
                    el._sync_settings_gear_update_hint()

        poll.done.connect(_apply)
        poll.finished.connect(poll.deleteLater)
        poll.start()

    def refresh_update_banner(self):
        """Re-fetch server state and refresh the update button (background thread)."""
        self._schedule_update_banner_refresh()

    def apply_update_banner_state(self, available, published_label):
        """Apply a fetch done elsewhere (e.g. background thread) without another HEAD request."""
        try:
            self._update_available = bool(available)
            self._update_published_label = (published_label or '').strip()
            self.btnUpdate.setText(self._update_button_text())
            self._sync_update_button_tooltip()
            self._apply_update_button_style()
        except Exception:
            pass

    def _update_button_text(self):
        if self._update_available:
            return (
                'New build available — Install (Experimental)'
                if self._update_channel == 'experimental'
                else 'New build available — Install'
            )
        if self._update_channel == 'experimental':
            return 'Install Latest (Experimental)'
        return 'Install Latest Build'

    def _sync_update_button_tooltip(self) -> None:
        lines = []
        detail = (self._update_published_label or '').strip()
        if detail:
            lines.append(detail)
        lines.append('Download and install the latest build for this update channel.')
        self.btnUpdate.setToolTip('\n'.join(lines))

    def _apply_update_button_style(self):
        if self._update_available:
            self.btnUpdate.setStyleSheet(
                getattr(_zcut_constants, 'UPDATE_AVAILABLE_PUSHBUTTON_QSS', _UPDATE_BTN_QSS_FALLBACK)
            )
        else:
            self.btnUpdate.setStyleSheet('')
    
    def _iface_combo_is_placeholder(self) -> bool:
        """True when the combo only shows the Npcap error stub (not a real adapter)."""
        if self.comboInterface.count() != 1:
            return False
        try:
            return not str(self.comboInterface.itemData(0) or '').strip()
        except Exception:
            return True

    def _sync_iface_combo_from_list(self, current, _previous=None) -> None:
        if getattr(self, '_iface_picker_guard', False) or current is None:
            return
        try:
            name = str(current.data(Qt.UserRole) or '')
        except Exception:
            name = ''
        if not name:
            return
        idx = self.comboInterface.findData(name)
        if idx >= 0:
            self.comboInterface.setCurrentIndex(idx)

    def _select_iface_list_row(self, idx: int) -> None:
        lst = getattr(self, 'listNetworkInterface', None)
        if lst is None or idx < 0 or idx >= lst.count():
            return
        self._iface_picker_guard = True
        try:
            lst.setCurrentRow(idx)
        finally:
            self._iface_picker_guard = False

    def _apply_combo_ifaces(self, ifaces, *, preserve_selection: bool = True) -> bool:
        """Populate network-interface picker; return True when at least one adapter was added."""
        from tools.utils import resolve_settings_iface_name, settings_iface_picker_hint

        saved = ''
        if preserve_selection:
            try:
                saved = str(self.comboInterface.currentData() or '')
            except Exception:
                pass
        if not saved:
            try:
                saved = str(get_settings('iface') or '')
            except Exception:
                saved = ''
        shown = ifaces_for_settings_combo(ifaces)
        lst = getattr(self, 'listNetworkInterface', None)
        hint = getattr(self, 'lblIfaceHint', None)
        self._iface_picker_guard = True
        try:
            self.comboInterface.clear()
            if lst is not None:
                lst.clear()
            if not shown:
                self.comboInterface.addItem('(no adapters found — check Npcap)', '')
                if lst is not None:
                    lst.addItem('(no adapters found — check Npcap)')
                return False
            for iface in shown:
                label = format_iface_settings_label(iface)
                self.comboInterface.addItem(label, iface.name)
                if lst is not None:
                    item = QListWidgetItem(label)
                    item.setData(Qt.UserRole, iface.name)
                    lst.addItem(item)
            want = resolve_settings_iface_name(saved) or saved
            idx = self.comboInterface.findData(want)
            if idx < 0 and saved:
                idx = self.comboInterface.findData(saved)
            if idx < 0:
                try:
                    from tools.utils import pick_best_live_iface

                    best = pick_best_live_iface()
                    if best is not None:
                        idx = self.comboInterface.findData(best.name)
                except Exception:
                    idx = -1
            if idx >= 0:
                self.comboInterface.setCurrentIndex(idx)
                if lst is not None:
                    lst.setCurrentRow(idx)
            if hint is not None:
                hint.setText(settings_iface_picker_hint(shown))
        finally:
            self._iface_picker_guard = False
        return True

    def loadInterfaces(self, *, use_cache: bool = True):
        from tools.utils import get_ifaces, get_ifaces_cached

        ifaces = get_ifaces_cached() if use_cache else get_ifaces()
        self._apply_combo_ifaces(ifaces)

    def _load_interfaces_foreground(self) -> None:
        """Resync adapter list on the GUI thread (Scapy/Npcap is unreliable from QThread)."""
        from tools.utils import get_ifaces, get_ifaces_cached

        ifaces = list(get_ifaces_cached())
        if not ifaces:
            ifaces = list(get_ifaces())
        self._apply_combo_ifaces(ifaces)

    def _load_interfaces_background(self) -> None:
        """Refresh adapter list off the GUI thread (ipconfig is slow)."""
        from PyQt5.QtCore import QThread, pyqtSignal

        class _IfaceLoader(QThread):
            finished_list = pyqtSignal(list)

            def run(self):
                from tools.utils import get_ifaces

                try:
                    # Do not invalidate cache here — worker-thread Scapy often returns []
                    # and would wipe a good list that loadInterfaces(use_cache=True) just showed.
                    self.finished_list.emit(list(get_ifaces()))
                except Exception:
                    self.finished_list.emit([])

        prev = getattr(self, '_iface_loader', None)
        if prev is not None and prev.isRunning():
            return

        def _apply(ifaces):
            if not ifaces:
                if not self._iface_combo_is_placeholder():
                    return
                QTimer.singleShot(0, self._load_interfaces_foreground)
                return
            self._apply_combo_ifaces(ifaces)

        loader = _IfaceLoader(self)
        loader.finished_list.connect(_apply)
        self._iface_loader = loader
        loader.start()