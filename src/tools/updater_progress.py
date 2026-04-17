"""
Qt progress UI for downloading the Windows installer before launching Inno Setup.

Uses QNetworkAccessManager so the download runs on Qt's event loop (same thread as the UI).
Avoids QThread + urllib + nested QEventLoop, which was unstable on Windows.
"""

import os

from PyQt5.QtCore import QEventLoop, Qt, QUrl
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt5.QtWidgets import QProgressDialog

from constants import APP_BUNDLE_NAME, APP_DISPLAY_NAME
from tools.updater_core import (
    _download_request_url,
    _temp_installer_path,
    _validate_installer_exe,
)
from tools.updater_debug import begin_updater_debug_session, updater_log


def download_update_with_progress_dialog(parent, url):
    """
    Modal progress while downloading. Returns path to temp installer, or None if cancelled.
    Raises RuntimeError on failure (not cancel).
    """
    begin_updater_debug_session('download_update_with_progress_dialog')
    updater_log(
        'progress UI (Qt network): start url=%r parent_type=%s',
        url,
        type(parent).__name__ if parent is not None else None,
    )

    if not url:
        raise RuntimeError('Update URL is not configured.')
    if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
        raise RuntimeError('Update URL must start with http:// or https://')

    tmp_path = _temp_installer_path(url)
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    download_url = _download_request_url(url)
    updater_log('progress UI: GET %r', download_url)

    qurl = QUrl(download_url)
    if not qurl.isValid():
        raise RuntimeError('Invalid download URL.')

    dlg = QProgressDialog()
    dlg.setWindowTitle(APP_DISPLAY_NAME)
    dlg.setAttribute(Qt.WA_DeleteOnClose, False)
    dlg.setLabelText('Connecting…')
    dlg.setCancelButtonText('Cancel')
    dlg.setRange(0, 100)
    dlg.setMinimumDuration(0)
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setValue(0)
    if parent is not None:
        icon = parent.windowIcon()
        if icon is not None and not icon.isNull():
            dlg.setWindowIcon(icon)

    manager = QNetworkAccessManager()
    req = QNetworkRequest(qurl)
    req.setHeader(QNetworkRequest.UserAgentHeader, f'{APP_BUNDLE_NAME}-updater')
    req.setRawHeader(b'Cache-Control', b'no-cache')
    req.setRawHeader(b'Pragma', b'no-cache')

    reply = manager.get(req)
    out = open(tmp_path, 'wb')
    out_closed = False

    loop = QEventLoop()
    state = {'cancelled': False, 'http_error': None}

    def _close_out():
        nonlocal out_closed
        if out_closed:
            return
        try:
            out.flush()
            out.close()
        except Exception as e:
            updater_log('_close_out: %s', e, exc_info=True)
        out_closed = True

    def on_ready_read():
        try:
            if reply.error() == QNetworkReply.NoError:
                chunk = reply.readAll()
                if chunk:
                    out.write(bytes(chunk))
        except Exception as e:
            updater_log('readyRead: %s', e, exc_info=True)

    def on_progress(rx, total):
        try:
            if dlg.wasCanceled():
                state['cancelled'] = True
                reply.abort()
                return
        except Exception:
            return
        rx = int(rx)
        if total > 0:
            dlg.setRange(0, 100)
            dlg.setValue(min(99, int(rx * 100 / total)))
            dlg.setLabelText(
                f'Downloading update… {rx / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB'
            )
        else:
            dlg.setRange(0, 0)
            dlg.setLabelText(f'Downloading update… {rx / (1024 * 1024):.1f} MB')

    def on_finished():
        try:
            if reply.error() == QNetworkReply.NoError:
                rest = reply.readAll()
                if rest:
                    out.write(bytes(rest))
        except Exception as e:
            updater_log('on_finished read: %s', e, exc_info=True)
        _close_out()

        err = reply.error()
        if err != QNetworkReply.NoError:
            if err == QNetworkReply.OperationCanceledError:
                state['cancelled'] = True
                state['http_error'] = None
            else:
                state['http_error'] = reply.errorString()
        else:
            state['http_error'] = None

        reply.deleteLater()
        loop.quit()

    reply.readyRead.connect(on_ready_read)
    reply.downloadProgress.connect(on_progress)
    reply.finished.connect(on_finished)
    dlg.canceled.connect(reply.abort)

    dlg.show()
    if parent is not None and parent.isVisible():
        try:
            fg = dlg.frameGeometry()
            fg.moveCenter(parent.frameGeometry().center())
            dlg.move(fg.topLeft())
        except Exception as e:
            updater_log('center dialog: %s', e, exc_info=True)
    dlg.raise_()
    dlg.activateWindow()

    updater_log('progress UI: entering event loop (Qt network)')
    try:
        loop.exec_()
    finally:
        _close_out()

    try:
        dlg_was_canceled = dlg.wasCanceled()
    except Exception:
        dlg_was_canceled = False

    updater_log(
        'progress UI: loop done cancelled=%s dlg_cancel=%s err=%r',
        state['cancelled'],
        dlg_was_canceled,
        state['http_error'],
    )

    try:
        dlg.reset()
        dlg.close()
    except Exception as e:
        updater_log('close progress dlg: %s', e, exc_info=True)

    if state['cancelled'] or dlg_was_canceled:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return None

    if state['http_error']:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise RuntimeError(state['http_error'])

    try:
        _validate_installer_exe(tmp_path)
    except RuntimeError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    return tmp_path
