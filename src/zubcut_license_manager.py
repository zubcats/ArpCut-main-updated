from sys import argv
import sys as _sys
import os as _os
import traceback

_sys.path.append(_os.path.dirname(__file__))


def _frozen_qt_plugin_path():
    """PyInstaller onedir: Qt sometimes fails to find platforms/qwindows.dll → instant exit, no window."""
    if not getattr(_sys, 'frozen', False):
        return
    base = _os.path.dirname(_sys.executable)
    for rel in (
        _os.path.join('PyQt5', 'Qt5', 'plugins'),
        _os.path.join('_internal', 'PyQt5', 'Qt5', 'plugins'),
    ):
        p = _os.path.join(base, rel)
        if _os.path.isdir(p):
            _os.environ['QT_PLUGIN_PATH'] = p
            return


def _fatal(title: str, msg: str) -> None:
    try:
        log = _os.path.join(_os.environ.get('TEMP', '.'), 'zubcut_license_manager_error.txt')
        with open(log, 'w', encoding='utf-8', errors='replace') as fh:
            fh.write(msg + '\n')
        full = f'{msg}\n\nDetails saved to:\n{log}'
    except Exception:
        full = msg
    if _sys.platform.startswith('win'):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, full, title, 0x10)
            return
        except Exception:
            pass
    print(full, file=_sys.stderr)


if __name__ == '__main__':
    _frozen_qt_plugin_path()
    try:
        from os import makedirs

        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QIcon, QPixmap
        from PyQt5.QtWidgets import QApplication, QStyleFactory
        from qdarkstyle import load_stylesheet

        from constants import DOCUMENTS_PATH
        from gui.license_manager import LicenseManagerWindow
        from tools.branding import load_application_qicon, qicon_is_empty
        from assets import app_icon

        def _load_window_icon():
            icon = load_application_qicon()
            if qicon_is_empty(icon):
                pix = QPixmap()
                pix.loadFromData(app_icon)
                if pix.isNull():
                    return QIcon()
                return QIcon(pix)
            return icon

        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        _ss_prop = getattr(Qt, 'AA_UseStyleSheetPropagationInWidgetStyles', None)
        if _ss_prop is not None:
            QApplication.setAttribute(_ss_prop, True)
        app = QApplication(argv)
        _fusion = QStyleFactory.create('Fusion')
        if _fusion is not None:
            app.setStyle(_fusion)
        app.setStyleSheet(load_stylesheet())
        makedirs(DOCUMENTS_PATH, exist_ok=True)
        icon = _load_window_icon()
        app.setWindowIcon(icon)
        win = LicenseManagerWindow(icon)
        win.show()
        raise SystemExit(app.exec_())
    except Exception:
        _fatal('ZubCut License Manager', traceback.format_exc())
        raise SystemExit(1)

