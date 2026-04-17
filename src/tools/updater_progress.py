"""
Download the Windows installer with a modal progress dialog while urllib runs in a QThread.

Uses QDialog.exec_() + QueuedConnection signals (standard pattern). Do not hook dialog.finished
to cancel the thread on success — that raced with the worker finishing and caused crashes.
"""

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from constants import APP_DISPLAY_NAME
from tools.updater_core import download_installer
from tools.updater_debug import begin_updater_debug_session, updater_log


class _InstallerDownloadThread(QThread):
    progress = pyqtSignal(object, object)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self._url = url
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        try:
            updater_log('download thread: urllib start url=%s', self._url)
            path = download_installer(
                self._url,
                progress_callback=lambda r, t: self.progress.emit(r, t),
                should_cancel=lambda: self._cancel,
            )
            updater_log('download thread: ok path=%s', path)
            self.succeeded.emit(path)
        except RuntimeError as e:
            updater_log('download thread: RuntimeError %s', e)
            self.failed.emit(str(e))
        except Exception as e:
            updater_log('download thread: Exception %s', e, exc_info=True)
            self.failed.emit(str(e))


def download_update_with_progress_dialog(parent, url, *, show_progress=True):
    """
    Modal download dialog. Returns temp path, None if cancelled, or raises.
    show_progress=False omits the bar (compact text only).
    """
    begin_updater_debug_session('download_update_with_progress_dialog')
    updater_log('download dialog: start show_progress=%s url=%r', show_progress, url)

    if not url:
        raise RuntimeError('Update URL is not configured.')
    if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
        raise RuntimeError('Update URL must start with http:// or https://')

    dlg = QDialog(None)
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setWindowTitle(APP_DISPLAY_NAME)
    dlg.setAttribute(Qt.WA_DeleteOnClose, False)
    if parent is not None:
        icon = parent.windowIcon()
        if icon is not None and not icon.isNull():
            dlg.setWindowIcon(icon)

    lbl = QLabel(
        'Downloading update…'
        if show_progress
        else 'Downloading the installer…'
    )
    lbl.setWordWrap(True)
    bar = QProgressBar()
    bar.setRange(0, 0)
    btn = QPushButton('Cancel')

    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(btn)

    lay = QVBoxLayout(dlg)
    lay.addWidget(lbl)
    if show_progress:
        lay.addWidget(bar)
    lay.addLayout(row)

    thread = _InstallerDownloadThread(url)
    holder = {'path': None, 'err': None}

    def on_prog(received, total):
        if not show_progress:
            return
        received = int(received)
        if total is not None and int(total) > 0:
            total = int(total)
            bar.setRange(0, 100)
            bar.setValue(min(99, int(received * 100 / total)))
            lbl.setText(
                f'Downloading update… {received / (1024 * 1024):.1f} / '
                f'{total / (1024 * 1024):.1f} MB'
            )
        else:
            bar.setRange(0, 0)
            lbl.setText(f'Downloading update… {received / (1024 * 1024):.1f} MB')

    def on_ok(path):
        holder['path'] = path
        dlg.accept()

    def on_fail(msg):
        holder['err'] = msg or 'Download failed.'
        dlg.reject()

    qc = Qt.QueuedConnection
    thread.progress.connect(on_prog, type=qc)
    thread.succeeded.connect(on_ok, type=qc)
    thread.failed.connect(on_fail, type=qc)
    btn.clicked.connect(thread.request_cancel)
    dlg.rejected.connect(thread.request_cancel)

    thread.start()
    dlg.exec_()
    thread.wait(600000)

    if holder['path'] is not None:
        return holder['path']

    err = holder['err'] or ''
    if 'cancel' in err.lower():
        return None
    if err:
        raise RuntimeError(err)
    return None
