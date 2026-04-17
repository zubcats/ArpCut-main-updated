"""
Qt progress UI for downloading the Windows installer before launching Inno Setup.
"""

from PyQt5.QtCore import QEventLoop, Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QProgressDialog

from constants import APP_DISPLAY_NAME
from tools.updater_core import download_installer
from tools.updater_debug import begin_updater_debug_session, updater_log


class _InstallerDownloadThread(QThread):
    """Runs urllib download off the GUI thread; progress is queued to the main thread."""

    progress = pyqtSignal(object, object)  # received, total (total may be None)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)
    aborted = pyqtSignal()

    def __init__(self, url):
        super().__init__()
        self._url = url
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        try:
            updater_log('worker thread: download_installer start url=%s', self._url)
            path = download_installer(
                self._url,
                progress_callback=lambda r, t: self.progress.emit(r, t),
                should_cancel=lambda: self._cancel,
            )
            updater_log('worker thread: download_installer ok path=%s', path)
            self.succeeded.emit(path)
        except RuntimeError as e:
            updater_log('worker thread: RuntimeError %s', e)
            if 'cancel' in str(e).lower():
                self.aborted.emit()
            else:
                self.failed.emit(str(e))
        except Exception as e:
            updater_log('worker thread: Exception %s', e, exc_info=True)
            self.failed.emit(str(e))


def download_update_with_progress_dialog(parent, url):
    """
    Modal progress while downloading. Returns path to temp installer, or None if cancelled.
    Raises RuntimeError / other exceptions on failure (not cancel).
    """
    begin_updater_debug_session('download_update_with_progress_dialog')
    updater_log(
        'progress UI: start url=%r parent_type=%s',
        url,
        type(parent).__name__ if parent is not None else None,
    )
    # No parent + application modal: avoids native crashes with frameless parent windows
    # on Windows. Download runs in a worker thread so we never nest processEvents() during
    # urllib I/O (that re-entrancy also crashed after the Yes/No dialog).
    dlg = QProgressDialog()
    dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    dlg.setWindowTitle(APP_DISPLAY_NAME)
    if parent is not None:
        icon = parent.windowIcon()
        if icon is not None and not icon.isNull():
            dlg.setWindowIcon(icon)
    dlg.setLabelText('Connecting…')
    dlg.setCancelButtonText('Cancel')
    dlg.setRange(0, 100)
    dlg.setMinimumDuration(0)
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setValue(0)

    thread = _InstallerDownloadThread(url)
    loop = QEventLoop()
    result = {'path': None, 'error': None, 'aborted': False}

    def on_progress(received, total):
        try:
            if dlg.wasCanceled():
                return
        except Exception as e:
            updater_log('on_progress: wasCanceled failed %s', e, exc_info=True)
            return
        received = int(received)
        if total is not None:
            total = int(total)
        if total and total > 0:
            dlg.setRange(0, 100)
            pct = min(99, int(received * 100 / total))
            dlg.setValue(pct)
            dlg.setLabelText(
                f'Downloading update… {received / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB'
            )
        else:
            dlg.setRange(0, 0)
            dlg.setLabelText(f'Downloading update… {received / (1024 * 1024):.1f} MB')

    def on_ok(path):
        result['path'] = path
        loop.quit()

    def on_fail(msg):
        result['error'] = RuntimeError(msg)
        loop.quit()

    def on_abort():
        result['aborted'] = True
        loop.quit()

    thread.progress.connect(on_progress)
    thread.succeeded.connect(on_ok)
    thread.failed.connect(on_fail)
    thread.aborted.connect(on_abort)
    dlg.canceled.connect(thread.request_cancel)

    updater_log('progress UI: starting worker thread')
    thread.start()
    updater_log('progress UI: showing dialog')
    dlg.show()
    if parent is not None and parent.isVisible():
        try:
            fg = dlg.frameGeometry()
            fg.moveCenter(parent.frameGeometry().center())
            dlg.move(fg.topLeft())
        except Exception as e:
            updater_log('progress UI: center on parent failed %s', e, exc_info=True)
    dlg.raise_()
    dlg.activateWindow()

    updater_log('progress UI: entering local event loop')
    loop.exec_()
    updater_log(
        'progress UI: loop quit aborted=%s err=%s path_set=%s',
        result['aborted'],
        result['error'] is not None,
        result['path'] is not None,
    )
    thread.wait()
    updater_log('progress UI: thread.wait done')

    was_canceled = False
    try:
        was_canceled = dlg.wasCanceled()
    except Exception as e:
        updater_log('progress UI: dlg.wasCanceled() failed %s', e, exc_info=True)

    def _close_dlg():
        try:
            dlg.reset()
            dlg.close()
            QApplication.processEvents()
        except Exception as e:
            updater_log('_close_dlg failed %s', e, exc_info=True)

    if result['aborted'] or was_canceled:
        updater_log('progress UI: cancel path')
        _close_dlg()
        return None
    if result['error'] is not None:
        updater_log('progress UI: error path %s', result['error'])
        _close_dlg()
        raise result['error']

    path = result['path']
    updater_log('progress UI: success path=%s, closing', path)
    try:
        dlg.setRange(0, 100)
        dlg.setValue(100)
        dlg.setLabelText('Download finished. Starting installer…')
        QApplication.processEvents()
    except Exception as e:
        updater_log('progress UI: final label failed %s', e, exc_info=True)
    _close_dlg()
    return path
