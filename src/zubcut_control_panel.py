from sys import argv
import sys as _sys
import os as _os
import traceback
from datetime import datetime

_sys.path.append(_os.path.dirname(__file__))


def _cp_log_paths(basename: str):
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


def _cp_boot(line: str) -> None:
    stamp = datetime.now().isoformat(timespec='seconds')
    body = f'{stamp} {line}\n'
    for path in _cp_log_paths('zubcut_control_panel_boot.txt'):
        try:
            with open(path, 'a', encoding='utf-8', errors='replace') as fh:
                fh.write(body)
        except Exception:
            pass


_cp_boot('zubcut_control_panel.py: after path append')


def _maybe_attach_debug_console() -> None:
    if (_os.environ.get('ZUBCUT_CONTROL_PANEL_DEBUG') or '').strip().lower() not in (
        '1',
        'true',
        'yes',
        'on',
    ):
        return
    if not _sys.platform.startswith('win'):
        return
    try:
        import ctypes

        ctypes.windll.kernel32.AllocConsole()
        _sys.stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace')
        _sys.stderr = _sys.stdout
        print('ZubCut Control Panel debug console attached')
    except Exception as exc:
        _cp_boot('AllocConsole failed: ' + repr(exc))


def _fatal(title: str, msg: str) -> None:
    paths = _cp_log_paths('zubcut_control_panel_error.txt')
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


def _install_control_panel_excepthook() -> None:
    """Log Qt slot errors and keep the window open (unlike the main app crash hook)."""

    def _hook(exc_type, exc, tb) -> None:
        if exc_type is not None and issubclass(exc_type, (SystemExit, KeyboardInterrupt)):
            return
        msg = ''.join(traceback.format_exception(exc_type, exc, tb))
        _cp_boot('uncaught: ' + msg.replace('\n', ' | '))
        for path in _cp_log_paths('zubcut_control_panel_error.txt'):
            try:
                with open(path, 'a', encoding='utf-8', errors='replace') as fh:
                    fh.write(msg + '\n')
            except Exception:
                pass
        shown = (
            f'{getattr(exc_type, "__name__", exc_type)}: {exc}\n\n'
            'The Control Panel stayed open. Details were saved to '
            '%APPDATA%\\ZubCut\\zubcut_control_panel_error.txt'
        )
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                QMessageBox.warning(None, 'ZubCut Control Panel', shown)
                return
        except Exception:
            pass
        _fatal('ZubCut Control Panel', msg)

    _sys.excepthook = _hook
    if hasattr(_sys, 'unraisablehook'):

        def _unraisable(args) -> None:
            _hook(args.exc_type, args.exc_value, args.exc_traceback)

        _sys.unraisablehook = _unraisable


if __name__ == '__main__':
    from constants import CONTROL_PANEL_DISPLAY_NAME

    _maybe_attach_debug_console()
    _install_control_panel_excepthook()
    _cp_boot('__main__: start')
    try:
        from tools.qt_frozen_bootstrap import configure_qt_environment

        configure_qt_environment()
        _cp_boot('configure_qt_environment() done')
    except Exception:
        _cp_boot('configure_qt_environment() raised: ' + traceback.format_exc().replace('\n', ' | '))
    try:
        from os import makedirs

        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtGui import QIcon, QPixmap
        from PyQt5.QtWidgets import QApplication, QStyleFactory
        from qdarkstyle import load_stylesheet

        from constants import DOCUMENTS_PATH
        from gui.control_panel import ControlPanelWindow
        from tools.branding import load_application_qicon, qicon_is_empty
        from assets import app_icon

        _cp_boot('imports OK')

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
        if _sys.platform.startswith('win'):
            _sw_gl = getattr(Qt, 'AA_UseSoftwareOpenGL', None)
            if _sw_gl is not None:
                QApplication.setAttribute(_sw_gl, True)
                _cp_boot('AA_UseSoftwareOpenGL enabled')
        _ss_prop = getattr(Qt, 'AA_UseStyleSheetPropagationInWidgetStyles', None)
        if _ss_prop is not None:
            QApplication.setAttribute(_ss_prop, True)
        app = QApplication(argv)
        _cp_boot('QApplication created')
        _fusion = QStyleFactory.create('Fusion')
        if _fusion is not None:
            app.setStyle(_fusion)
        # Charcoal app chrome (avoid raw qdark blue on dialogs / message boxes).
        try:
            from gui.control_panel import control_panel_app_stylesheet

            app.setStyleSheet(control_panel_app_stylesheet())
        except Exception:
            app.setStyleSheet(load_stylesheet())
        makedirs(DOCUMENTS_PATH, exist_ok=True)
        icon = _load_window_icon()
        app.setWindowIcon(icon)
        _cp_boot('before ControlPanelWindow()')
        win = ControlPanelWindow(icon)
        _cp_boot('after ControlPanelWindow(); calling show()')
        _screen = app.primaryScreen()
        if _screen is not None:
            _fg = _screen.availableGeometry()
            win.move(
                _fg.x() + max(0, (_fg.width() - win.width()) // 2),
                _fg.y() + max(0, (_fg.height() - win.height()) // 2),
            )
        win.showNormal()
        win.show()
        win.raise_()
        win.activateWindow()
        if _sys.platform.startswith('win'):
            try:
                import ctypes

                _hwnd = int(win.winId())
                ctypes.windll.user32.ShowWindow(_hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(_hwnd)
                _cp_boot('Win32 ShowWindow/SetForegroundWindow hwnd=%s' % _hwnd)
            except Exception as exc:
                _cp_boot('Win32 foreground failed: ' + repr(exc))

        def _visibility_watchdog() -> None:
            _cp_boot(
                'visibility watchdog visible=%s minimized=%s geom=%sx%s+%s+%s'
                % (
                    win.isVisible(),
                    win.isMinimized(),
                    win.width(),
                    win.height(),
                    win.x(),
                    win.y(),
                )
            )
            if win.isVisible() and not win.isMinimized():
                return
            win.showNormal()
            win.show()
            win.raise_()
            win.activateWindow()
            if not win.isVisible():
                _fatal(
                    CONTROL_PANEL_DISPLAY_NAME,
                    'The window did not become visible after launch.\n'
                    'Try Alt+Tab, or run with ZUBCUT_CONTROL_PANEL_DEBUG=1 and send the boot log.',
                )

        QTimer.singleShot(1500, _visibility_watchdog)
        _cp_boot(
            'show() done visible=%s active=%s geom=%sx%s+%s+%s'
            % (
                win.isVisible(),
                win.isActiveWindow(),
                win.width(),
                win.height(),
                win.x(),
                win.y(),
            )
        )
        raise SystemExit(app.exec_())
    except Exception:
        _fatal(CONTROL_PANEL_DISPLAY_NAME, traceback.format_exc())
        raise SystemExit(1)
