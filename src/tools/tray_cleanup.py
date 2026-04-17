"""Tell the Windows shell to remove tray icons before the process goes away."""

from __future__ import annotations


def hide_all_system_tray_icons() -> None:
    try:
        from PyQt5.QtWidgets import QApplication, QSystemTrayIcon

        app = QApplication.instance()
        if app is None:
            return
        for ti in app.findChildren(QSystemTrayIcon):
            try:
                ti.hide()
            except Exception:
                pass
        try:
            app.processEvents()
        except Exception:
            pass
    except Exception:
        pass
