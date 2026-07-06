from sys import argv, exit
import sys as _sys, os as _os

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))


def _run_license_crypto_self_test_and_exit() -> None:
    """CI / support: verify Ed25519 in frozen builds without loading PyQt or Scapy."""
    import tempfile

    from tools.license_offline import license_crypto_self_test

    ok, report = license_crypto_self_test()
    out = _os.path.join(tempfile.gettempdir(), 'zubcut-license-crypto-verify.txt')
    try:
        with open(out, 'w', encoding='utf-8') as fh:
            fh.write(report)
            fh.write('\n')
    except OSError:
        pass
    print(report)
    _sys.exit(0 if ok else 1)


if __name__ == '__main__' and '--verify-license-crypto' in argv:
    _run_license_crypto_self_test_and_exit()

from PyQt5.QtWidgets import QApplication, QStyleFactory
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal

from tools.utils import goto
from tools.crash_feedback import install_crash_feedback
from tools.utils_gui import (
    npcap_exists,
    duplicate_zubcut,
    repair_settings,
    migrate_settings_file,
    ensure_windows_elevated,
    import_settings,
)
from tools.license_offline import load_and_validate_installed_license
from tools.license_remote_signin import effective_signin_url, license_transient_reason
from tools.branding import load_shell_window_icon, qicon_is_empty
from tools.qtools import msg_box, Buttons, MsgIcon

from zubcut_platform import require_supported_platform

require_supported_platform()

from gui.main import ZubCutApp

from assets import app_icon
from constants import *
import constants as _zcut_constants

_UI_LOG_VICTIM_BLOCK_FG = getattr(_zcut_constants, 'UI_LOG_VICTIM_BLOCK_FG', '#32716D')
_UI_LOG_RESTORE_FG = getattr(
    _zcut_constants,
    'UI_LOG_RESTORE_FG',
    getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_BG', '#5D706E'),
)


def _load_window_icon():
    icon = load_shell_window_icon()
    if qicon_is_empty(icon):
        return ZubCutApp.processIcon(app_icon, crop_margins=True)
    return icon


class _LicenseRuntimeSessionThread(QThread):
    """POST /validate off the UI thread so slow TLS/DNS does not freeze Qt."""

    done = pyqtSignal(object, str)

    def __init__(self, url: str, account: str, license_id: str, *, timeout_sec: float = 12.0):
        super().__init__()
        self._url = url
        self._account = account
        self._license_id = license_id
        self._timeout = timeout_sec

    def run(self) -> None:
        try:
            from tools.license_remote_signin import validate_active_license_session

            ok, reason = validate_active_license_session(
                self._url,
                self._account,
                self._license_id,
                timeout_sec=self._timeout,
            )
            self.done.emit(ok, reason)
        except Exception as e:
            try:
                self.done.emit(None, str(e))
            except Exception:
                pass


def _license_gated_build() -> bool:
    c = str(UPDATE_CHANNEL or '').strip().lower()
    if c in ('stable', 'paid'):
        c = 'main'
    return c in ('main', 'experimental')


def _validate_license_or_exit(icon) -> None:
    """
    Main and experimental builds are gated: no app access without a valid license.
    If missing/invalid, user must sign in successfully before main UI launches.
    """
    if not _license_gated_build():
        return
    res = load_and_validate_installed_license()
    if res.ok:
        return

    from gui.license_signin import get_last_signin_error, run_license_signin

    if run_license_signin(None, icon):
        res = load_and_validate_installed_license()
        if res.ok:
            return
        reason = get_last_signin_error() or res.reason or 'Unknown sign-in failure'
        msg_box(
            APP_DISPLAY_NAME,
            f'Incorrect sign in.\n\nReason: {reason}',
            MsgIcon.CRITICAL,
            icon,
        )
        exit(1)
    reason = get_last_signin_error() or 'Unknown sign-in failure'
    msg_box(
        APP_DISPLAY_NAME,
        f'Incorrect sign in.\n\nReason: {reason}',
        MsgIcon.CRITICAL,
        icon,
    )
    exit(1)


def _start_license_runtime_validation(gui, icon) -> None:
    """Re-check account validity against server every 10 minutes on license-gated builds."""
    if not _license_gated_build():
        return

    def _force_lockout_and_exit(reason: str) -> None:
        if bool(getattr(gui, '_license_lockout_in_progress', False)):
            return
        gui._license_lockout_in_progress = True
        try:
            gui.log('License expired or invalid. Stopping protection and closing app.', 'red')
        except Exception:
            pass

        # Stop active attack loops first, then aggressively send unkill a few times.
        try:
            gui.stopLagSwitch()
        except Exception:
            pass
        try:
            gui.stopDupe(log=False)
            gui._flush_pending_dupe_clear_sync()
        except Exception:
            pass

        def _unkill_pass() -> None:
            try:
                from tools.pfctl import unblock_ip

                for v in list(getattr(gui.killer, 'killed', {}).values()):
                    _ip = v.get('ip') if isinstance(v, dict) else None
                    if _ip:
                        try:
                            unblock_ip(_ip)
                        except Exception:
                            pass
            except Exception:
                pass
            try:
                gui.killer.unkill_all(getattr(gui, 'scanner', None))
            except Exception:
                pass
            try:
                gui._sync_killed_devices()
            except Exception:
                pass

        _unkill_pass()
        QTimer.singleShot(250, _unkill_pass)
        QTimer.singleShot(800, _unkill_pass)
        QTimer.singleShot(1800, _unkill_pass)
        QTimer.singleShot(2200, gui.quit_all)

        # Keep visible reason for operator while shutdown proceeds.
        msg_box(
            APP_DISPLAY_NAME,
            f'License expired.\n\nReason: {reason}',
            MsgIcon.CRITICAL,
            icon,
        )

    gui._license_runtime_last_deferred_reason = ''

    def _log_runtime_deferred(reason: str) -> None:
        short = license_transient_reason(reason)
        if short == getattr(gui, '_license_runtime_last_deferred_reason', ''):
            return
        gui._license_runtime_last_deferred_reason = short
        gui.log(f'License check deferred: {short}', _UI_LOG_RESTORE_FG)

    def _on_session_validated(ok, reason: str) -> None:
        if ok is True:
            gui._license_runtime_last_deferred_reason = ''
            return
        if ok is None:
            _log_runtime_deferred(reason)
            return
        _force_lockout_and_exit(reason)

    def _enforce_runtime_license() -> None:
        prev = getattr(gui, '_license_runtime_validate_thread', None)
        if prev is not None and prev.isRunning():
            return
        res = load_and_validate_installed_license()
        if not res.ok:
            _force_lockout_and_exit(res.reason)
            return
        payload = res.payload or {}
        account = str(res.signin_account or '').strip()
        license_id = str(payload.get('license_id') or '').strip()
        url = effective_signin_url()
        th = _LicenseRuntimeSessionThread(url, account, license_id, timeout_sec=12.0)
        gui._license_runtime_validate_thread = th
        th.done.connect(_on_session_validated, Qt.QueuedConnection)

        def _clear_thread_ref() -> None:
            if getattr(gui, '_license_runtime_validate_thread', None) is th:
                gui._license_runtime_validate_thread = None

        th.finished.connect(_clear_thread_ref)
        th.finished.connect(th.deleteLater)
        th.start()

    gui._license_runtime_validation_timer = QTimer(gui)
    gui._license_runtime_validation_timer.setInterval(10 * 60 * 1000)
    gui._license_runtime_validation_timer.timeout.connect(_enforce_runtime_license)
    gui._license_runtime_validation_timer.start()
    QTimer.singleShot(30 * 1000, _enforce_runtime_license)


# import debug.test

if __name__ == "__main__":
    if _sys.platform == 'win32' and not ensure_windows_elevated():
        exit(1)

    # Before QApplication: real per-monitor DPI so Win32 icon loads + GetDpiForWindow match the display.
    if _sys.platform == 'win32':
        try:
            import ctypes

            _user32 = ctypes.windll.user32
            _ctx_v2 = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            if hasattr(_user32, 'SetProcessDpiAwarenessContext'):
                _user32.SetProcessDpiAwarenessContext(_ctx_v2)
            else:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                import ctypes

                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setAttribute(Qt.AA_UseStyleSheetPropagationInWidgetStyles, True)
    app = QApplication(argv)
    if _sys.platform == 'win32':
        try:
            from PyQt5.QtWinExtras import QtWin

            QtWin.setCurrentProcessExplicitAppUserModelID(f'zubcats.{APP_BUNDLE_NAME}.1.0')
        except Exception:
            pass
    # Windows native style often ignores or mis-paints QPushButton :hover under global QSS; Fusion is reliable.
    _fusion = QStyleFactory.create('Fusion')
    if _fusion is not None:
        app.setStyle(_fusion)
    install_crash_feedback()
    icon = _load_window_icon()
    app.setWindowIcon(icon)

    # Check if Npcap is installed (Windows only)
    if not npcap_exists():
        if msg_box(APP_DISPLAY_NAME, 'Npcap is not installed\n\nClick OK to download',
                    MsgIcon.CRITICAL, icon, Buttons.OK | Buttons.CANCEL) == Buttons.OK:
            goto(NPCAP_URL)
        exit(1)

    # Check if another instance is running
    if duplicate_zubcut():
        msg_box(APP_DISPLAY_NAME, f'{APP_DISPLAY_NAME} is already running!', MsgIcon.WARN, icon)
        exit(1)

    # Run the GUI
    migrate_settings_file()
    if _sys.platform.startswith('win'):
        try:
            from tools.clumsy_ics import (
                maybe_ensure_wlan_autoconfig_on_startup,
                maybe_repair_stale_clumsy_ics_on_startup,
                reset_clumsy_mode_on_startup,
            )

            reset_clumsy_mode_on_startup()
            maybe_ensure_wlan_autoconfig_on_startup()
            maybe_repair_stale_clumsy_ics_on_startup()
        except Exception:
            pass
    repair_settings()
    _validate_license_or_exit(icon)
    GUI = ZubCutApp(window_icon=icon)
    _start_license_runtime_validation(GUI, icon)
    GUI.show()
    GUI._apply_scan_table_column_layout()
    GUI._apply_status_strip_elide()
    try:
        GUI._ensure_clean_network_on_startup()
    except Exception:
        pass

    # Bind scanner/killer to repaired Settings adapter (not get_default_iface guess).
    try:
        from tools.utils import get_iface_by_name

        s = import_settings()
        saved_iface = str(s.get('iface') or '').strip()
        if saved_iface:
            picked = get_iface_by_name(saved_iface)
            if picked and picked.name != 'NULL':
                GUI.scanner.iface = picked
                GUI.killer.iface = picked
    except Exception:
        pass

    # Initialize scanner and ensure interface is valid
        GUI.scanner.init()
    try:
        from networking.killer import enable_ip_forwarding

        enable_ip_forwarding()
        GUI.scanner.refresh_local_topology()
    except Exception:
        pass
    try:
        from tools.utils import reconcile_scanner_with_settings_iface

        hint = reconcile_scanner_with_settings_iface(GUI.scanner, GUI.killer)
        if hint:
            GUI.scanner.add_me()
            GUI.scanner.add_router()
    except Exception:
        pass
    if GUI.scanner.iface.name == 'NULL':
        # Try to get a valid interface
        from tools.utils import get_default_iface
        GUI.scanner.iface = get_default_iface()
        GUI.scanner.init()

    if _sys.platform == 'win32':
        from tools.utils_gui import is_admin as _is_admin

        if _is_admin():
            GUI.log('Running as Administrator (required for Kill / Clumsy hotspot).', _UI_LOG_RESTORE_FG)
        else:
            GUI.log(
                'Not running as Administrator — approve UAC on launch or reinstall from latest build.',
                'red',
            )

    # Ensure "Me" and "Router" are added immediately
    try:
        GUI.scanner.add_me()
        GUI.scanner.add_router()
        GUI.showDevices()  # Show at least "Me" and "Router" on startup
    except Exception as e:
        GUI.log(f'Warning: Could not initialize local devices: {e}', _UI_LOG_VICTIM_BLOCK_FG)

    try:
        from tools.clumsy_inline import hotspot_arp_cache_sensitive

        if not hotspot_arp_cache_sensitive(GUI.scanner):
            GUI.scanner.flush_arp()
    except Exception:
        GUI.scanner.flush_arp()

    # On macOS/Linux when not root, avoid ARP scan (requires /dev/bpf) and use Ping scan
    try:
        import os
        is_posix = (os.name == 'posix')
        is_root = (getattr(os, 'geteuid', lambda: 0)() == 0)
    except Exception:
        is_posix, is_root = False, True

    if is_posix and not is_root:
        GUI.log('Running without root: using Ping Scan', _UI_LOG_RESTORE_FG)
        GUI.ScanThread_Starter(scan_type=1)
    else:
        # Only check connection if interface is valid
        if GUI.scanner.iface.name != 'NULL':
            GUI.scanEasy()
        else:
            GUI.log('No network interface found. Please check your network connection.', 'red')

    GUI.UpdateThread_Starter()
    # Bring window to top on startup
    GUI.activateWindow()
    #GUI.scanner.print_report()
    exit(app.exec_())
