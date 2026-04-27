from sys import argv, exit
import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from PyQt5.QtWidgets import QApplication, QStyleFactory
from PyQt5.QtCore import Qt, QTimer

from tools.utils import goto
from tools.crash_feedback import install_crash_feedback
from tools.utils_gui import npcap_exists, duplicate_zubcut, repair_settings, migrate_settings_file
from tools.license_offline import load_and_validate_installed_license
from tools.license_remote_signin import effective_signin_url, validate_active_license_session
from tools.branding import load_application_qicon, qicon_is_empty
from tools.qtools import msg_box, Buttons, MsgIcon

from gui.main import ElmoCut

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
    icon = load_application_qicon()
    if qicon_is_empty(icon):
        return ElmoCut.processIcon(app_icon, crop_margins=True)
    return icon


def _validate_paid_license_or_exit(icon) -> None:
    """
    Paid branch is always gated: no app access without a valid paid license.
    If missing/invalid, user must sign in successfully before main UI launches.
    """
    if str(UPDATE_CHANNEL or '').strip().lower() not in ('paid', 'experimental'):
        return
    res = load_and_validate_installed_license()
    if res.ok:
        return

    from gui.paid_license_signin import get_last_signin_error, run_paid_license_signin

    if run_paid_license_signin(None, icon):
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


def _start_paid_runtime_validation(gui, icon) -> None:
    """On paid builds, re-check account validity against server every 10 minutes."""
    if str(UPDATE_CHANNEL or '').strip().lower() not in ('paid', 'experimental'):
        return

    def _force_lockout_and_exit(reason: str) -> None:
        if bool(getattr(gui, '_paid_lockout_in_progress', False)):
            return
        gui._paid_lockout_in_progress = True
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
        except Exception:
            pass

        def _unkill_pass() -> None:
            try:
                gui.killer.unkill_all()
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

    def _enforce_runtime_license() -> None:
        res = load_and_validate_installed_license()
        if not res.ok:
            _force_lockout_and_exit(res.reason)
            return
        payload = res.payload or {}
        account = str(payload.get('user_name') or '').strip()
        license_id = str(payload.get('license_id') or '').strip()
        url = effective_signin_url()
        ok, reason = validate_active_license_session(url, account, license_id, timeout_sec=12.0)
        if ok is True:
            return
        if ok is None:
            # Transient outage/network failure; retry on next interval.
            gui.log(f'License check deferred: {reason}', UI_LOG_RESTORE_FG)
            return
        _force_lockout_and_exit(reason)

    gui._paid_runtime_validation_timer = QTimer(gui)
    gui._paid_runtime_validation_timer.setInterval(10 * 60 * 1000)
    gui._paid_runtime_validation_timer.timeout.connect(_enforce_runtime_license)
    gui._paid_runtime_validation_timer.start()
    QTimer.singleShot(30 * 1000, _enforce_runtime_license)


# import debug.test

if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setAttribute(Qt.AA_UseStyleSheetPropagationInWidgetStyles, True)
    app = QApplication(argv)
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
    repair_settings()
    _validate_paid_license_or_exit(icon)
    GUI = ElmoCut(window_icon=icon)
    _start_paid_runtime_validation(GUI, icon)
    GUI.show()
    GUI.resizeEvent()

    # Initialize scanner and ensure interface is valid
    GUI.scanner.init()
    if GUI.scanner.iface.name == 'NULL':
        # Try to get a valid interface
        from tools.utils import get_default_iface
        GUI.scanner.iface = get_default_iface()
        GUI.scanner.init()

    # Ensure "Me" and "Router" are added immediately
    try:
        GUI.scanner.add_me()
        GUI.scanner.add_router()
        GUI.showDevices()  # Show at least "Me" and "Router" on startup
    except Exception as e:
        GUI.log(f'Warning: Could not initialize local devices: {e}', _UI_LOG_VICTIM_BLOCK_FG)

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
