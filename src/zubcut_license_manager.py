from sys import argv
import sys as _sys
import os as _os
import traceback
from datetime import datetime

_sys.path.append(_os.path.dirname(__file__))


def _lm_log_paths(basename: str):
    """Match packaging/pyinstaller-hooks/rthook_qt_license_manager.py — several writable locations."""
    out = []
    temp = (_os.environ.get('TEMP') or _os.environ.get('TMP') or '').strip()
    if temp:
        out.append(_os.path.join(temp, basename))
    if _sys.platform.startswith('win'):
        ad = _os.environ.get('APPDATA', '')
        if ad:
            zd = _os.path.join(ad, 'ZubCut')
            try:
                _os.makedirs(zd, exist_ok=True)
            except Exception:
                pass
            out.append(_os.path.join(zd, basename))
    if getattr(_sys, 'frozen', False):
        out.append(_os.path.join(_os.path.dirname(_sys.executable), basename))
    seen = set()
    uniq = []
    for p in out:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _lm_boot(line: str) -> None:
    stamp = datetime.now().isoformat(timespec='seconds')
    body = f'{stamp} {line}\n'
    for path in _lm_log_paths('zubcut_license_manager_boot.txt'):
        try:
            with open(path, 'a', encoding='utf-8', errors='replace') as fh:
                fh.write(body)
        except Exception:
            pass


_lm_boot('zubcut_license_manager.py: after path append (interpreter reached script)')


def _fatal(title: str, msg: str) -> None:
    paths = _lm_log_paths('zubcut_license_manager_error.txt')
    for log in paths:
        try:
            with open(log, 'w', encoding='utf-8', errors='replace') as fh:
                fh.write(msg + '\n')
        except Exception:
            pass
    listed = '\n'.join(paths)
    full = f'{msg}\n\nDetails saved to:\n{listed}'
    if _sys.platform.startswith('win'):
        try:
            import ctypes

            shown = full if len(full) < 900 else (full[:850] + '\n\n…(truncated; see log files above)')
            ctypes.windll.user32.MessageBoxW(0, shown, title, 0x10)
            return
        except Exception:
            pass
    print(full, file=_sys.stderr)


if __name__ == '__main__':
    _lm_boot('__main__: start')
    try:
        from tools.qt_frozen_bootstrap import configure_qt_environment

        configure_qt_environment()
        _lm_boot('configure_qt_environment() done')
    except Exception:
        _lm_boot('configure_qt_environment() raised: ' + traceback.format_exc().replace('\n', ' | '))
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

        _lm_boot('imports OK')

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
        _lm_boot('QApplication created')
        _fusion = QStyleFactory.create('Fusion')
        if _fusion is not None:
            app.setStyle(_fusion)
        app.setStyleSheet(load_stylesheet())
        makedirs(DOCUMENTS_PATH, exist_ok=True)
        icon = _load_window_icon()
        app.setWindowIcon(icon)
        _lm_boot('before LicenseManagerWindow()')
        win = LicenseManagerWindow(icon)
        _lm_boot('after LicenseManagerWindow(); calling show()')
        win.show()
        raise SystemExit(app.exec_())
    except Exception:
        _fatal('ZubCut License Manager', traceback.format_exc())
        raise SystemExit(1)
