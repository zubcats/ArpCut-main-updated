from sys import argv, exit
import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from PyQt5.QtWidgets import QApplication, QStyleFactory
from PyQt5.QtCore import Qt

from tools.utils import goto
from tools.crash_feedback import install_crash_feedback
from tools.utils_gui import npcap_exists, duplicate_zubcut, repair_settings, migrate_settings_file
from tools.license_offline import load_and_validate_installed_license
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
    if str(UPDATE_CHANNEL or '').strip().lower() != 'paid':
        return
    res = load_and_validate_installed_license()
    if res.ok:
        return

    from gui.paid_license_signin import run_paid_license_signin

    if run_paid_license_signin(None, icon):
        res = load_and_validate_installed_license()
        if res.ok:
            return
        msg_box(
            APP_DISPLAY_NAME,
            'Incorrect sign in.',
            MsgIcon.CRITICAL,
            icon,
        )
        exit(1)
    msg_box(
        APP_DISPLAY_NAME,
        'Incorrect sign in.',
        MsgIcon.CRITICAL,
        icon,
    )
    exit(1)


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
