"""
Shared update check + installer download for ZubCut (Windows frozen builds).
Uses Last-Modified on the channel installer URL vs APP_BUILD_TIME_ISO from CI.
"""

import os
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from constants import (
    APP_BUNDLE_NAME,
    APP_BUILD_TIME_ISO,
    UPDATE_CHANNEL,
    UPDATE_DOWNLOAD_URL_EXPERIMENTAL,
    UPDATE_DOWNLOAD_URL_STABLE,
)

# GitHub's Last-Modified on the installer is usually later than APP_BUILD_TIME_ISO
# (CI stamps time before packaging/upload). Require this much skew so we do not
# treat the same build as an update or loop reinstall at every startup.
_MIN_REMOTE_AHEAD_OF_BUILD = timedelta(minutes=45)


def _parse_build_time_iso(raw):
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def selected_update_url():
    channel = str(UPDATE_CHANNEL or 'experimental').strip().lower()
    if channel not in ('stable', 'experimental'):
        channel = 'experimental'
    if channel == 'stable':
        return (UPDATE_DOWNLOAD_URL_STABLE or '').strip()
    return (UPDATE_DOWNLOAD_URL_EXPERIMENTAL or '').strip()


def get_update_status():
    """
    HEAD the channel URL; compare Last-Modified to APP_BUILD_TIME_ISO.
    Returns (update_available, published_label_for_ui).
    """
    url = selected_update_url()
    if not url:
        return False, ''
    try:
        req = urllib.request.Request(
            url,
            method='HEAD',
            headers={'User-Agent': f'{APP_BUNDLE_NAME}-update-check'},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            last_modified = resp.headers.get('Last-Modified', '').strip()
        if not last_modified:
            return False, ''
        remote_dt = parsedate_to_datetime(last_modified)
        if remote_dt is None:
            return False, ''
        if remote_dt.tzinfo is None:
            remote_dt = remote_dt.replace(tzinfo=timezone.utc)
        dt_local = remote_dt.astimezone()
        published_label = dt_local.strftime('%b %d, %Y %I:%M %p')
        local_dt = _parse_build_time_iso(APP_BUILD_TIME_ISO)
        if local_dt is None:
            return False, ''
        if local_dt.tzinfo is None:
            local_dt = local_dt.replace(tzinfo=timezone.utc)
        remote_utc = remote_dt.astimezone(timezone.utc)
        local_utc = local_dt.astimezone(timezone.utc)
        available = (remote_utc - local_utc) > _MIN_REMOTE_AHEAD_OF_BUILD
        return available, published_label
    except Exception:
        return False, ''


def update_is_available():
    available, _ = get_update_status()
    return available


_READ_CHUNK = 256 * 1024


def _validate_installer_exe(tmp_path):
    if not os.path.exists(tmp_path):
        raise RuntimeError('Downloaded file missing.')
    sz = os.path.getsize(tmp_path)
    if sz < 1024:
        hint = ''
        try:
            with open(tmp_path, 'rb') as fp:
                head = fp.read(256)
            if head.lstrip().startswith(b'<'):
                hint = (
                    ' The response looks like HTML (wrong URL, private repo, or login page) '
                    'instead of the .exe file.'
                )
        except OSError:
            pass
        raise RuntimeError(
            f'Downloaded file is too small ({sz} bytes) to be a valid installer.{hint}'
        )
    with open(tmp_path, 'rb') as fp:
        if fp.read(2) != b'MZ':
            raise RuntimeError(
                f'Downloaded file is not a Windows installer executable ({sz} bytes).'
            )


def _temp_installer_path(url):
    url_path = urlparse(url).path or ''
    fname = os.path.basename(url_path) or f'{APP_BUNDLE_NAME}-Setup-latest.exe'
    if not fname.lower().endswith('.exe'):
        fname = f'{APP_BUNDLE_NAME}-Setup-latest.exe'
    stem, ext = os.path.splitext(fname)
    tmp_fname = f'{stem}-{int(time.time())}{ext or ".exe"}'
    return os.path.join(tempfile.gettempdir(), tmp_fname)


def _download_request_url(url):
    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_items.append(('cb', str(int(time.time()))))
    return urlunparse(parsed._replace(query=urlencode(query_items)))


def download_installer(
    url,
    progress_callback=None,
    should_cancel=None,
):
    """
    Download the installer to a temp path. Optional progress_callback(received, total)
    where total is None if Content-Length was not sent. should_cancel() returns True to abort.
    Raises RuntimeError on failure or cancel.
    """
    try:
        from tools.updater_debug import begin_updater_debug_session, updater_log

        begin_updater_debug_session('download_installer')
        updater_log('download_installer: tmp prep url=%r', url)
    except Exception:
        pass

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
    try:
        from tools.updater_debug import updater_log

        updater_log('download_installer: GET %r', download_url)
    except Exception:
        pass
    req = urllib.request.Request(
        download_url,
        headers={
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'User-Agent': f'{APP_BUNDLE_NAME}-updater',
        },
    )
    total = None
    try:
        from tools.updater_debug import updater_log

        resp_cm = urllib.request.urlopen(req, timeout=300)
    except Exception:
        try:
            from tools.updater_debug import updater_log

            updater_log('download_installer: urlopen failed', exc_info=True)
        except Exception:
            pass
        raise
    with resp_cm as resp:
        cl = resp.headers.get('Content-Length')
        if cl:
            try:
                total = int(cl)
            except ValueError:
                total = None
        received = 0
        cancelled = False
        with open(tmp_path, 'wb') as fp:
            while True:
                if should_cancel and should_cancel():
                    cancelled = True
                    break
                chunk = resp.read(_READ_CHUNK)
                if not chunk:
                    break
                fp.write(chunk)
                received += len(chunk)
                if progress_callback:
                    progress_callback(received, total)

    if cancelled:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise RuntimeError('Download cancelled.')

    _validate_installer_exe(tmp_path)
    return tmp_path


def launch_installer(tmp_path, *, no_ui=False):
    """
    Run the downloaded Inno Setup. no_ui=True uses /VERYSILENT (nothing on screen).
    Default uses /SILENT so a small setup progress window is visible after the app exits.
    """
    try:
        from tools.updater_debug import updater_log

        updater_log('launch_installer: path=%r no_ui=%s', tmp_path, no_ui)
    except Exception:
        pass
    install_log = os.path.join(
        tempfile.gettempdir(), f'{APP_BUNDLE_NAME.lower()}-update-install.log'
    )
    if no_ui:
        flags = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', f'/LOG={install_log}']
    else:
        flags = ['/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', f'/LOG={install_log}']
    subprocess.Popen([tmp_path] + flags, close_fds=True)


def spawn_installer_update(url):
    """
    Download without progress UI, then start Inno with a visible setup progress window.
    Caller should exit the app immediately after this returns.
    """
    path = download_installer(url)
    launch_installer(path, no_ui=False)
