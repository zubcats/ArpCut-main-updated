"""
Qt progress UI for downloading the Windows installer before launching Inno Setup.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QProgressDialog

from constants import APP_DISPLAY_NAME
from tools.updater_core import download_installer


def download_update_with_progress_dialog(parent, url):
    """
    Modal progress while downloading. Returns path to temp installer, or None if cancelled.
    Raises RuntimeError / other exceptions on failure (not cancel).
    """
    dlg = QProgressDialog(parent)
    dlg.setAttribute(Qt.WA_DeleteOnClose, True)
    dlg.setWindowTitle(APP_DISPLAY_NAME)
    dlg.setLabelText('Connecting…')
    dlg.setCancelButtonText('Cancel')
    dlg.setRange(0, 100)
    dlg.setMinimumDuration(0)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setValue(0)
    dlg.show()
    QApplication.processEvents()

    def on_progress(received, total):
        if dlg.wasCanceled():
            return
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
        QApplication.processEvents()

    try:
        path = download_installer(
            url,
            progress_callback=on_progress,
            should_cancel=dlg.wasCanceled,
        )
    except RuntimeError as e:
        if 'cancel' in str(e).lower():
            dlg.reset()
            dlg.close()
            QApplication.processEvents()
            return None
        dlg.reset()
        dlg.close()
        QApplication.processEvents()
        raise
    except Exception:
        dlg.reset()
        dlg.close()
        QApplication.processEvents()
        raise

    if dlg.wasCanceled():
        dlg.reset()
        dlg.close()
        QApplication.processEvents()
        return None

    dlg.setRange(0, 100)
    dlg.setValue(100)
    dlg.setLabelText('Download finished. Starting installer…')
    QApplication.processEvents()
    dlg.reset()
    dlg.close()
    QApplication.processEvents()
    return path
