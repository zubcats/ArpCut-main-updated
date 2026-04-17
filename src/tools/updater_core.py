"""
Shared update check + installer download for ZubCut (Windows frozen builds).
Uses Last-Modified on the channel installer URL vs APP_BUILD_TIME_ISO from CI.
"""

import os
import shutil
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


def spawn_installer_update(url):
    """
    Download the installer from url, verify it looks like an EXE, spawn Inno silent install.
    Caller should exit the app immediately after this returns.
    Raises RuntimeError on failure.
    """
    if not url:
        raise RuntimeError('Update URL is not configured.')
    if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
        raise RuntimeError('Update URL must start with http:// or https://')

    url_path = urlparse(url).path or ''
    fname = os.path.basename(url_path) or f'{APP_BUNDLE_NAME}-Setup-latest.exe'
    if not fname.lower().endswith('.exe'):
        fname = f'{APP_BUNDLE_NAME}-Setup-latest.exe'
    stem, ext = os.path.splitext(fname)
    tmp_fname = f'{stem}-{int(time.time())}{ext or ".exe"}'
    tmp_path = os.path.join(tempfile.gettempdir(), tmp_fname)
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_items.append(('cb', str(int(time.time()))))
    download_url = urlunparse(parsed._replace(query=urlencode(query_items)))
    req = urllib.request.Request(
        download_url,
        headers={
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'User-Agent': f'{APP_BUNDLE_NAME}-updater',
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_path, 'wb') as fp:
        shutil.copyfileobj(resp, fp)
    if not os.path.exists(tmp_path):
        raise RuntimeError('Downloaded file missing.')
    if os.path.getsize(tmp_path) < 1024:
        raise RuntimeError('Downloaded file is too small to be a valid installer.')
    with open(tmp_path, 'rb') as fp:
        if fp.read(2) != b'MZ':
            raise RuntimeError('Downloaded file is not a Windows installer executable.')

    install_log = os.path.join(
        tempfile.gettempdir(), f'{APP_BUNDLE_NAME.lower()}-update-install.log'
    )
    installer_args = [
        tmp_path,
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        f'/LOG={install_log}',
    ]
    subprocess.Popen(installer_args, close_fds=True)
