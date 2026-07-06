"""
Shared update check + installer download for ZubCut (Windows frozen builds).

Compares APP_BUILD_TIME_ISO / APP_BUILD_COMMIT (stamped in CI) to the rolling
GitHub release. Downloads use the GitHub Releases *asset API* URL (unique per
upload) so ``stable-latest`` CDN caches cannot serve an older installer.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from constants import (
    APP_BUNDLE_NAME,
    APP_BUILD_COMMIT,
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

_BUILD_INFO_ASSET = 'build-info.json'

_REMOTE_CACHE_TTL_SEC = 45.0


@dataclass(frozen=True)
class RemoteInstallerInfo:
    updated_at: datetime | None
    download_url: str
    asset_id: int
    size: int
    remote_commit: str
    remote_built_at: str


_remote_cache: tuple[float, RemoteInstallerInfo | None] | None = None
_ssl_context: ssl.SSLContext | None = None


def _urllib_ssl_context() -> ssl.SSLContext:
    """CA bundle for frozen Windows builds (PyInstaller often lacks system trust store)."""
    global _ssl_context
    if _ssl_context is not None:
        return _ssl_context
    try:
        import certifi

        _ssl_context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        _ssl_context = ssl.create_default_context()
    return _ssl_context


def _urllib_urlopen(req: urllib.request.Request, *, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout, context=_urllib_ssl_context())


def invalidate_remote_installer_cache() -> None:
    """Drop cached GitHub release metadata (e.g. after asset 404 when a release is re-published)."""
    global _remote_cache
    _remote_cache = None


def _is_github_release_asset_api_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or '').lower()
    return 'api.github.com' in host and '/releases/assets/' in (parsed.path or '')


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


def local_build_commit() -> str:
    return str(APP_BUILD_COMMIT or '').strip().lower()


def local_build_label() -> str:
    label = _format_dt_label(local_build_datetime())
    commit = local_build_commit()
    if commit and len(commit) > 12:
        commit = commit[:12]
    if label and commit:
        return f'{label} ({commit})'
    return label or commit


def _github_repo() -> str:
    try:
        from constants import GITHUB_REPO_SLUG

        slug = str(GITHUB_REPO_SLUG or '').strip()
        if slug:
            return slug
    except Exception:
        pass
    url = selected_update_url()
    if url:
        parts = urlparse(url).path.strip('/').split('/')
        if len(parts) >= 2:
            return f'{parts[0]}/{parts[1]}'
    return 'zubcats/ArpCut-main-updated'


def _release_tag_for_channel(channel: str) -> str:
    return 'experimental-latest' if channel == 'experimental' else 'stable-latest'


def _installer_asset_name(channel: str) -> str:
    return (
        'ZubCut-Setup-experimental.exe'
        if channel == 'experimental'
        else 'ZubCut-Setup.exe'
    )


def _api_release_json(channel: str) -> dict:
    tag = _release_tag_for_channel(channel)
    api_url = f'https://api.github.com/repos/{_github_repo()}/releases/tags/{tag}'
    req = urllib.request.Request(
        api_url,
        headers={
            **_NO_CACHE_HEADERS,
            'Accept': 'application/vnd.github+json',
            'User-Agent': f'{APP_BUNDLE_NAME}-update-check',
        },
    )
    with _urllib_urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _api_asset_download_url(asset_id: int) -> str:
    """Per-asset URL; redirects to a unique objects.githubusercontent.com object."""
    repo = _github_repo()
    return f'https://api.github.com/repos/{repo}/releases/assets/{int(asset_id)}'


def _fetch_build_info_for_release(channel: str) -> dict:
    try:
        payload = _api_release_json(channel)
    except Exception:
        return {}
    for asset in payload.get('assets') or []:
        if str(asset.get('name') or '') != _BUILD_INFO_ASSET:
            continue
        asset_id = asset.get('id')
        if not asset_id:
            return {}
        req = urllib.request.Request(
            _api_asset_download_url(int(asset_id)),
            headers={
                **_NO_CACHE_HEADERS,
                'Accept': 'application/octet-stream',
                'User-Agent': f'{APP_BUNDLE_NAME}-update-check',
            },
        )
        with _urllib_urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data if isinstance(data, dict) else {}
    return {}


def _fetch_remote_installer_info(channel: str) -> RemoteInstallerInfo | None:
    """Release installer asset from GitHub API (authoritative; avoids stale tag CDN)."""
    asset_name = _installer_asset_name(channel)
    try:
        payload = _api_release_json(channel)
    except Exception:
        return None

    installer_asset = None
    for asset in payload.get('assets') or []:
        if str(asset.get('name') or '') == asset_name:
            installer_asset = asset
            break
    if not installer_asset:
        return None

    asset_id = int(installer_asset.get('id') or 0)
    if asset_id <= 0:
        return None

    updated_at = _parse_build_time_iso(installer_asset.get('updated_at') or '')
    if updated_at is not None:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        updated_at = updated_at.astimezone(timezone.utc)

    build_info = _fetch_build_info_for_release(channel)
    remote_commit = str(build_info.get('commit') or '').strip().lower()
    remote_built_at = str(build_info.get('built_at') or '').strip()
    if not remote_built_at and build_info:
        remote_built_at = str(build_info.get('build_time_iso') or '').strip()

    if updated_at is None and remote_built_at:
        updated_at = _parse_build_time_iso(remote_built_at)
        if updated_at is not None:
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            updated_at = updated_at.astimezone(timezone.utc)

    try:
        size = int(installer_asset.get('size') or 0)
    except (TypeError, ValueError):
        size = 0

    return RemoteInstallerInfo(
        updated_at=updated_at,
        download_url=_api_asset_download_url(asset_id),
        asset_id=asset_id,
        size=max(0, size),
        remote_commit=remote_commit,
        remote_built_at=remote_built_at,
    )


def _cached_remote_installer_info(channel: str, *, force: bool = False) -> RemoteInstallerInfo | None:
    global _remote_cache
    now = time.time()
    if (
        not force
        and _remote_cache is not None
        and (now - _remote_cache[0]) < _REMOTE_CACHE_TTL_SEC
    ):
        return _remote_cache[1]
    info = _fetch_remote_installer_info(channel)
    _remote_cache = (now, info)
    return info


def remote_installer_info(*, force_refresh: bool = False) -> RemoteInstallerInfo | None:
    return _cached_remote_installer_info(_normalized_update_channel(), force=force_refresh)


def resolve_installer_download_url(*, force_refresh: bool = False) -> str:
    """
    URL to pass to download_installer. Prefer GitHub asset API (fresh object) over
    the static releases/download/<tag>/… link baked into constants.
    """
    candidates = installer_download_candidates(force_refresh=force_refresh)
    return candidates[0] if candidates else ''


def installer_download_candidates(*, force_refresh: bool = False) -> list[str]:
    """Ordered URLs to try (API asset first, then static release link)."""
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str) -> None:
        u = (raw or '').strip()
        if not u or not u.lower().startswith(('http://', 'https://')):
            return
        if u in seen:
            return
        seen.add(u)
        out.append(u)

    channel = _normalized_update_channel()
    info = _cached_remote_installer_info(channel, force=force_refresh)
    if info and info.download_url:
        add(info.download_url)
    add(selected_update_url())
    return out


def refresh_installer_download_plan() -> tuple[str, list[str], int]:
    """
    Fresh GitHub release metadata (blocking). Call from a worker thread only —
    used after the user confirms install so the confirm dialog stays instant.
    """
    candidates = installer_download_candidates(force_refresh=True)
    url = candidates[0] if candidates else ''
    fallbacks = candidates[1:] if len(candidates) > 1 else []
    info = remote_installer_info(force_refresh=True)
    expected_size = int(info.size) if info and info.size > 0 else 0
    return url, fallbacks, expected_size


def release_page_url() -> str:
    channel = _normalized_update_channel()
    return f'https://github.com/{_github_repo()}/releases/tag/{_release_tag_for_channel(channel)}'


_NETWORK_WINERRORS = frozenset({10051, 10060, 10061, 10065, 11001})


def _network_error_reason(exc: BaseException) -> BaseException | None:
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return reason if isinstance(reason, BaseException) else None
    return exc if isinstance(exc, OSError) else None


def is_retryable_network_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.URLError):
        return True
    reason = _network_error_reason(exc)
    if isinstance(reason, OSError):
        if getattr(reason, 'winerror', None) in _NETWORK_WINERRORS:
            return True
        if reason.errno in (101, 113):
            return True
    low = str(exc).lower()
    return 'unreachable' in low or 'nicht erreichbar' in low or 'timed out' in low


def format_updater_error_message(exc: BaseException) -> str:
    """User-facing updater failure text (network / Clumsy hotspot hints)."""
    from tools.user_errors import scrub_user_error_text

    base = scrub_user_error_text(str(exc).strip() or repr(exc))
    lines = [base]
    if isinstance(exc, urllib.error.HTTPError) and int(getattr(exc, 'code', 0) or 0) == 404:
        lines.extend(
            [
                '',
                'The download link was stale.',
                'Click Install Latest Build again to fetch a fresh link.',
            ]
        )
        return scrub_user_error_text('\n'.join(lines))
    reason = _network_error_reason(exc)
    winerr = getattr(reason, 'winerror', None) if reason else None
    low = base.lower()
    host_unreachable = (
        winerr == 10065
        or '10065' in base
        or 'unreachable' in low
        or 'nicht erreichbar' in low
        or 'no route to host' in low
    )
    if host_unreachable:
        lines.extend(
            [
                '',
                'Your PC could not reach the update server (network unreachable).',
                'This often happens after Clumsy mode or Mobile Hotspot / sharing changes.',
                '',
                'Fix your connection first:',
                '• Windows Settings → Wi‑Fi → your adapter → Sharing → allow internet sharing',
                '• If Wi‑Fi is broken after an old build: tools\\Restore-Wlan-AutoConfig.cmd (admin)',
                '• Windows Settings → Mobile hotspot OFF, wait 10 seconds, ON again',
                '• Open any website in your browser to confirm internet works',
                '',
                'Then retry Install Latest Build in Settings.',
            ]
        )
    elif 'certificate verify failed' in low or 'certIFICATE_VERIFY_FAILED' in base:
        lines.extend(
            [
                '',
                'Windows could not verify the update server HTTPS certificate.',
                '• Check PC date/time and antivirus HTTPS scanning',
                '• Retry Install Latest Build in Settings',
            ]
        )
    elif is_retryable_network_error(exc):
        lines.extend(
            [
                '',
                'Check your internet connection and try again.',
                'Use Settings → Install Latest Build when your connection is working.',
            ]
        )
    return scrub_user_error_text('\n'.join(lines))


def _fetch_remote_head_dt(url: str) -> datetime | None:
    """HEAD fallback when the Releases API is unavailable."""
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
    with _urllib_urlopen(req, timeout=12) as resp:
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
    info = _cached_remote_installer_info(channel)
    if info and info.updated_at is not None:
        return info.updated_at
    try:
        return _fetch_remote_head_dt(download_url)
    except Exception:
        return None


def _remote_compare_datetime(
    remote_info: RemoteInstallerInfo | None,
    channel: str,
    download_url: str,
) -> datetime | None:
    """Prefer build-info built_at (matches PyInstaller stamp) over asset upload time."""
    if remote_info is not None and remote_info.remote_built_at:
        dt = _parse_build_time_iso(remote_info.remote_built_at)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    return _remote_installer_datetime(channel, download_url)


def _update_available_by_commit(remote: RemoteInstallerInfo | None) -> bool | None:
    """True/False when both sides have a commit; None if commit compare not possible."""
    if remote is None:
        return None
    remote_commit = str(remote.remote_commit or '').strip().lower()
    local_commit = local_build_commit()
    if not remote_commit or not local_commit:
        return None
    return remote_commit != local_commit


def get_update_status():
    """
    Compare local CI build metadata to the latest channel installer online.

    Returns (update_available, status_label_for_ui).
    """
    channel = _normalized_update_channel()
    url = selected_update_url()
    if not url:
        return False, ''

    remote_info = _cached_remote_installer_info(channel)
    remote_dt = _remote_compare_datetime(remote_info, channel, url)
    if remote_dt is None and remote_info is None:
        return False, ''

    local_dt = local_build_datetime()
    remote_label = _format_dt_label(remote_dt)
    local_label = local_build_label()
    local_commit = local_build_commit()
    remote_commit = (
        str(remote_info.remote_commit or '').strip().lower() if remote_info else ''
    )

    commit_cmp = _update_available_by_commit(remote_info)
    if commit_cmp is True:
        if local_label and remote_label:
            return True, f'New build online: {remote_label} · yours: {local_label}'
        return True, 'New build online (newer commit)'

    if commit_cmp is False:
        if local_label and remote_label:
            return False, f'Up to date · built {local_label} · online: {remote_label}'
        return False, f'Up to date · online: {remote_label or "unknown"}'

    # Remote release lacks build-info commit metadata — do not treat installer
    # upload time (~10–20 min after PyInstaller) as proof of a newer build.
    if local_commit and not remote_commit:
        if local_label:
            return False, f'Up to date · built {local_label}'
        return False, 'Up to date'

    if not local_commit and remote_commit:
        if local_label and remote_label:
            return True, f'New build online: {remote_label} · yours: {local_label}'
        return True, 'New build online (newer commit)'

    if local_dt is None:
        return False, 'Up to date (build stamp unavailable)'

    available = (remote_dt - local_dt) > _MIN_REMOTE_AHEAD_OF_BUILD if remote_dt else False

    if available:
        if local_label and remote_label:
            return True, f'New version online: {remote_label} · yours: {local_label}'
        return True, f'New version online: {remote_label}'

    if local_label and remote_label:
        return False, f'Up to date · built {local_label} · online: {remote_label}'
    return False, f'Up to date · online: {remote_label or "unknown"}'


def update_is_available():
    available, _ = get_update_status()
    return available


_READ_CHUNK = 256 * 1024


def _validate_installer_exe(tmp_path, *, expected_size: int = 0):
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
    if expected_size > 0 and sz != expected_size:
        raise RuntimeError(
            f'Downloaded installer size mismatch (got {sz} bytes, expected {expected_size}). '
            'Try again in a minute or use Install Latest Build in Settings.'
        )


def _temp_installer_path(url):
    url_path = urlparse(url).path or ''
    fname = os.path.basename(url_path) or f'{APP_BUNDLE_NAME}-Setup-latest.exe'
    if not fname.lower().endswith('.exe'):
        channel = _normalized_update_channel()
        fname = _installer_asset_name(channel)
    stem, ext = os.path.splitext(fname)
    tmp_fname = f'{stem}-{int(time.time())}{ext or ".exe"}'
    return os.path.join(tempfile.gettempdir(), tmp_fname)


def _download_request_url(url):
    """Cache-bust static release URLs only — GitHub asset API URLs must stay exact."""
    if _is_github_release_asset_api_url(url):
        return url
    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_items.append(('cb', str(int(time.time()))))
    return urlunparse(parsed._replace(query=urlencode(query_items)))


def download_installer(
    url,
    progress_callback=None,
    should_cancel=None,
    *,
    expected_size: int = 0,
    fallback_urls=None,
):
    """
    Download the installer to a temp path. Optional progress_callback(received, total)
    where total is None if Content-Length was not sent. should_cancel() returns True to abort.
    Raises RuntimeError on failure or cancel.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        u = (raw or '').strip()
        if u and u not in seen and u.lower().startswith(('http://', 'https://')):
            seen.add(u)
            candidates.append(u)

    if isinstance(url, (list, tuple)):
        for item in url:
            add(str(item))
    else:
        add(str(url or ''))
    for item in fallback_urls or ():
        add(str(item))

    if not candidates:
        raise RuntimeError('Update URL is not configured.')

    errors: list[tuple[str, BaseException]] = []
    refreshed_after_asset_404 = False
    idx = 0
    while idx < len(candidates):
        candidate = candidates[idx]
        try:
            return _download_installer_once(
                candidate,
                progress_callback=progress_callback,
                should_cancel=should_cancel,
                expected_size=expected_size,
            )
        except RuntimeError as e:
            if 'cancel' in str(e).lower():
                raise
            cause = e.__cause__
            if (
                isinstance(cause, urllib.error.HTTPError)
                and int(getattr(cause, 'code', 0) or 0) == 404
                and _is_github_release_asset_api_url(candidate)
                and not refreshed_after_asset_404
            ):
                invalidate_remote_installer_cache()
                refreshed_after_asset_404 = True
                seen_retry: set[str] = set()
                fresh: list[str] = []
                for raw in installer_download_candidates(force_refresh=True):
                    u = (raw or '').strip()
                    if u and u not in seen_retry:
                        seen_retry.add(u)
                        fresh.append(u)
                if fresh:
                    candidates = fresh
                    errors.clear()
                    idx = 0
                    continue
            errors.append((candidate, e))
            idx += 1
            if not is_retryable_network_error(e):
                break
        except Exception as e:
            errors.append((candidate, e))
            idx += 1
            if not is_retryable_network_error(e):
                break

    if len(errors) == 1:
        raise RuntimeError(format_updater_error_message(errors[0][1])) from errors[0][1]
    parts = ['All download URLs failed.']
    for u, err in errors:
        parts.append(f'• {u}: {err}')
    parts.append('')
    parts.append(format_updater_error_message(errors[-1][1]).split('\n', 1)[-1])
    raise RuntimeError('\n'.join(parts))


def _download_installer_once(
    url: str,
    progress_callback=None,
    should_cancel=None,
    *,
    expected_size: int = 0,
) -> str:
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
    headers = {
        **_NO_CACHE_HEADERS,
        'User-Agent': f'{APP_BUNDLE_NAME}-updater',
    }
    if '/releases/assets/' in download_url:
        headers['Accept'] = 'application/octet-stream'
    req = urllib.request.Request(download_url, headers=headers)
    total = None
    try:
        from tools.updater_debug import updater_log

        resp_cm = _urllib_urlopen(req, timeout=300)
    except Exception as e:
        try:
            from tools.updater_debug import updater_log

            updater_log('download_installer: urlopen failed', exc_info=True)
        except Exception:
            pass
        raise RuntimeError(format_updater_error_message(e)) from e
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

    _validate_installer_exe(tmp_path, expected_size=expected_size)
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
    if sys.platform.startswith('win'):
        try:
            from tools.clumsy_inline import clumsy_bundle_offered

            if clumsy_bundle_offered():
                flags.append('/MERGETASKS=clumsymode')
        except Exception:
            pass
    subprocess.Popen([tmp_path] + flags, close_fds=True)


def spawn_installer_update(url):
    """
    Download without progress UI, then start Inno with a visible setup progress window.
    Caller should exit the app immediately after this returns.
    """
    path = download_installer(url)
    launch_installer(path, no_ui=False)
