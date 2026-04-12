from sys import argv, exit
import sys as _sys, os as _os
_sys.path.append(_os.path.dirname(__file__))
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from tools.utils import goto
from tools.utils_gui import npcap_exists, duplicate_zubcut, repair_settings, migrate_settings_file
from tools.branding import load_application_qicon, qicon_is_empty
from tools.qtools import msg_box, Buttons, MsgIcon

from gui.main import ElmoCut

from assets import app_icon
from constants import *


def _load_window_icon():
    icon = load_application_qicon()
    if qicon_is_empty(icon):
        return ElmoCut.processIcon(app_icon)
    return icon


# import debug.test

if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
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
        GUI.log(f'Warning: Could not initialize local devices: {e}', 'orange')
    
    GUI.scanner.flush_arp()

    # On macOS/Linux when not root, avoid ARP scan (requires /dev/bpf) and use Ping scan
    try:
        import os
        is_posix = (os.name == 'posix')
        is_root = (getattr(os, 'geteuid', lambda: 0)() == 0)
    except Exception:
        is_posix, is_root = False, True

    if is_posix and not is_root:
        GUI.log('Running without root: using Ping Scan', 'orange')
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
