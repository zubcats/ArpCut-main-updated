from sys import argv, exit
import sys as _sys, os as _os

_sys.path.append(_os.path.dirname(__file__))

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


if __name__ == '__main__':
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setAttribute(Qt.AA_UseStyleSheetPropagationInWidgetStyles, True)
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
    exit(app.exec_())

