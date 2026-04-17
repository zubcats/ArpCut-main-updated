"""
Qt-based download of the Windows installer before launching Inno Setup.

Uses QNetworkAccessManager on the GUI thread. Startup auto-update uses **no**
progress dialog (no QProgressDialog / modality) to avoid Windows/Qt crashes;
Settings → Install Latest Build still shows a progress bar.
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


def download_update_with_progress_dialog(parent, url, *, show_progress=True):
    """
    Download the channel installer to a temp path.

    show_progress=False: no dialog (for startup auto-update — safest on Windows).
    show_progress=True: modal QProgressDialog (Settings → update).

    Returns path, or None if cancelled (only when show_progress).
    Raises RuntimeError on failure.
    """
    begin_updater_debug_session('download_update_with_progress_dialog')
    updater_log(
        'progress UI (Qt network): start show_progress=%s url=%r parent=%s',
        show_progress,
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

    dlg = None
    if show_progress:
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
    try:
        req.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
    except Exception:
        pass

    reply = manager.get(req)
    out = open(tmp_path, 'wb')
    out_closed = False

    loop = QEventLoop()
    state = {'cancelled': False, 'http_error': None}
    silent_last_pct = [-1]

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
        rx = int(rx)
        if dlg is not None:
            try:
                if dlg.wasCanceled():
                    state['cancelled'] = True
                    reply.abort()
                    return
            except Exception:
                return
            if total > 0:
                dlg.setRange(0, 100)
                dlg.setValue(min(99, int(rx * 100 / total)))
                dlg.setLabelText(
                    f'Downloading update… {rx / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB'
                )
            else:
                dlg.setRange(0, 0)
                dlg.setLabelText(f'Downloading update… {rx / (1024 * 1024):.1f} MB')
        elif total > 0:
            pct = min(99, int(rx * 100 / total))
            if pct >= silent_last_pct[0] + 10:
                silent_last_pct[0] = pct
                updater_log('silent download ~%s%%', pct)

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
    if dlg is not None:
        dlg.canceled.connect(reply.abort)

    if dlg is not None:
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

    dlg_was_canceled = False
    if dlg is not None:
        try:
            dlg_was_canceled = dlg.wasCanceled()
        except Exception:
            dlg_was_canceled = False
        try:
            dlg.reset()
            dlg.close()
        except Exception as e:
            updater_log('close progress dlg: %s', e, exc_info=True)

    updater_log(
        'progress UI: loop done cancelled=%s dlg_cancel=%s err=%r',
        state['cancelled'],
        dlg_was_canceled,
        state['http_error'],
    )

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
