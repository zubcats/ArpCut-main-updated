from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from license_manager.constants import APP_NAME
from license_manager.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == '__main__':
    raise SystemExit(main())
