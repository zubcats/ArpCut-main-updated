"""
Download the Windows installer for in-app updates.

Runs urllib on the main GUI thread (no QThread, no nested dialog exec). The window
will not respond until the download finishes; that avoids Qt threading / modality
crashes seen on Windows with QThread + QDialog around the same flow.
"""

from PyQt5.QtWidgets import QMessageBox

from constants import APP_DISPLAY_NAME
from tools.updater_core import download_installer
from tools.updater_debug import begin_updater_debug_session, updater_log


def download_update_with_progress_dialog(parent, url, *, show_progress=True):
    """
    Download the channel installer to a temp path and return it.

    Blocks the UI until complete (urllib on the main thread). Optional notice
    before starting when show_progress is True.
    """
    begin_updater_debug_session('download_update_with_progress_dialog')
    updater_log('sync urllib download: start url=%r', url)

    if not url:
        raise RuntimeError('Update URL is not configured.')
    if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
        raise RuntimeError('Update URL must start with http:// or https://')

    if show_progress:
        QMessageBox.information(
            None,
            APP_DISPLAY_NAME,
            (
                'The installer will download now.\n\n'
                'This window will not respond until the download finishes '
                '(often one to three minutes). Do not close the app.'
            ),
        )

    path = download_installer(url, progress_callback=None, should_cancel=None)
    updater_log('sync urllib download: done path=%s', path)
    return path
