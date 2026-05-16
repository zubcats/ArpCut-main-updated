"""
Shared update check + installer download for ZubCut (Windows frozen builds).

Compares APP_BUILD_TIME_ISO (stamped in CI) to the rolling GitHub release asset time.
Uses the GitHub Releases API (asset updated_at) as the primary source; HEAD
Last-Modified is a fallback. Both requests disable caching.
"""

from __future__ import annotations

import json
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
    UPDATE_DOWNLOAD_URL_MAIN,
)

# CI stamps APP_BUILD_TIME_ISO before PyInstaller; the uploaded asset is usually
# a few minutes later. Ignore small skew so we do not loop reinstalls.
_MIN_REMOTE_AHEAD_OF_BUILD = timedelta(minutes=5)

_NO_CACHE_HEADERS = {
    'Cache-Control': 'no-cache, no-store',
    'Pragma': 'no-cache',
}

_GITHUB_REPO_FALLBACK = 'zubcats/ArpCut-main-updated'


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


def _format_dt_label(dt: datetime | None) -> str:
    if dt is None:
        return ''
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime('%b %d, %Y %I:%M %p')


def _normalized_update_channel():
    c = str(UPDATE_CHANNEL or 'experimental').strip().lower()
    if c in ('stable', 'paid'):
        c = 'main'
    if c not in ('main', 'experimental'):
        c = 'experimental'
    return c


def is_experimental_build():
    """True when this binary is an experimental-channel build (feature gates)."""
    return _normalized_update_channel() == 'experimental'


def selected_update_url():
    channel = _normalized_update_channel()
    if channel == 'main':
        return (UPDATE_DOWNLOAD_URL_MAIN or '').strip()
    return (UPDATE_DOWNLOAD_URL_EXPERIMENTAL or '').strip()


def local_build_datetime() -> datetime | None:
    """UTC-aware build time baked into this binary (CI)."""
    dt = _parse_build_time_iso(APP_BUILD_TIME_ISO)
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_build_label() -> str:
    return _format_dt_label(local_build_datetime())


def _github_repo() -> str:
    url = selected_update_url()
    if url:
        parts = urlparse(url).path.strip('/').split('/')
        if len(parts) >= 2:
            return f'{parts[0]}/{parts[1]}'
    return _GITHUB_REPO_FALLBACK


def _release_tag_for_channel(channel: str) -> str:
    return 'experimental-latest' if channel == 'experimental' else 'stable-latest'


def _installer_asset_name(channel: str) -> str:
    return (
        'ZubCut-Setup-experimental.exe'
        if channel == 'experimental'
        else 'ZubCut-Setup.exe'
    )


def _fetch_remote_release_dt(channel: str) -> datetime | None:
    """Release asset updated_at from GitHub API (authoritative for rolling tags)."""
    tag = _release_tag_for_channel(channel)
    asset_name = _installer_asset_name(channel)
    api_url = f'https://api.github.com/repos/{_github_repo()}/releases/tags/{tag}'
    req = urllib.request.Request(
        api_url,
        headers={
            **_NO_CACHE_HEADERS,
            'Accept': 'application/vnd.github+json',
            'User-Agent': f'{APP_BUNDLE_NAME}-update-check',
        },
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    for asset in payload.get('assets') or []:
        if str(asset.get('name') or '') == asset_name:
            dt = _parse_build_time_iso(asset.get('updated_at') or '')
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
    dt = _parse_build_time_iso(payload.get('published_at') or '')
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fetch_remote_head_dt(url: str) -> datetime | None:
    """HEAD the installer URL; cache-busted so proxies do not serve stale Last-Modified."""
    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_items.append(('cb', str(int(time.time()))))
    bust_url = urlunparse(parsed._replace(query=urlencode(query_items)))
    req = urllib.request.Request(
        bust_url,
        method='HEAD',
        headers={
            **_NO_CACHE_HEADERS,
            'User-Agent': f'{APP_BUNDLE_NAME}-update-check',
        },
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        last_modified = (resp.headers.get('Last-Modified') or '').strip()
    if not last_modified:
        return None
    dt = parsedate_to_datetime(last_modified)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _remote_installer_datetime(channel: str, download_url: str) -> datetime | None:
    remote = None
    try:
        remote = _fetch_remote_release_dt(channel)
    except Exception:
        pass
    try:
        head_dt = _fetch_remote_head_dt(download_url)
        if head_dt is not None and (remote is None or head_dt > remote):
            remote = head_dt
    except Exception:
        pass
    return remote


def get_update_status():
    """
    Compare local CI build time to the latest channel installer online.

    Returns (update_available, status_label_for_ui).
    """
    channel = _normalized_update_channel()
    url = selected_update_url()
    if not url:
        return False, ''

    remote_dt = _remote_installer_datetime(channel, url)
    if remote_dt is None:
        return False, ''

    local_dt = local_build_datetime()
    remote_label = _format_dt_label(remote_dt)
    local_label = _format_dt_label(local_dt)

    if local_dt is None:
        return True, f'Latest online: {remote_label}'

    available = (remote_dt - local_dt) > _MIN_REMOTE_AHEAD_OF_BUILD
    if available:
        if local_label:
            return True, f'New version online: {remote_label} · yours: {local_label}'
        return True, f'New version online: {remote_label}'

    if local_label:
        return False, f'Up to date · built {local_label} · online: {remote_label}'
    return False, f'Up to date · online: {remote_label}'


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
            **_NO_CACHE_HEADERS,
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
