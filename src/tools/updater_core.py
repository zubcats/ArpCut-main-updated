"""
Shared update check + installer download for ZubCut (Windows frozen builds).

Compares APP_BUILD_TIME_ISO / APP_BUILD_COMMIT (stamped in CI) to the rolling
GitHub release. Downloads use the GitHub Releases *asset API* URL (unique per
upload) so ``stable-latest`` CDN caches cannot serve an older installer.
"""

from __future__ import annotations

import http.client
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
    INSTALLER_PUBLISHER_CERT_THUMBPRINTS,
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


def _parse_build_info_dict(raw) -> dict:
    if isinstance(raw, dict) and (
        raw.get('commit') or raw.get('built_at') or raw.get('channel')
    ):
        return raw
    return {}


def _build_info_from_release_payload(payload: dict) -> dict:
    """Prefer release-body JSON so the public download is the installer only."""
    body = str((payload or {}).get('body') or '').strip()
    if body.startswith('{'):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
        info = _parse_build_info_dict(parsed)
        if info:
            return info
    return {}


def _fetch_build_info_for_release(channel: str) -> dict:
    try:
        payload = _api_release_json(channel)
    except Exception:
        return {}
    from_body = _build_info_from_release_payload(payload)
    if from_body:
        return from_body
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
    # Do not cache misses: rolling-release republish deletes assets for a few
    # seconds; caching None would falsely clear the green update hint.
    if info is not None:
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


def _is_incomplete_download_error(exc: BaseException) -> bool:
    """True when the HTTP body was cut short (common AV/proxy flakiness)."""
    low = str(exc).lower()
    return (
        'size mismatch' in low
        or 'incomplete download' in low
        or ('truncated' in low and 'download' in low)
        or 'incomplete read' in low
    )


def is_retryable_network_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.URLError):
        return True
    if _is_incomplete_download_error(exc):
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
                '• If Wi‑Fi is broken after an old build: restart ZubCut as Administrator (WLAN AutoConfig is restored on launch)',
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

    ``update_available`` is True/False when the check succeeds, or None when the
    remote release cannot be read (network/API/republish race). Callers must not
    treat None as "up to date" — that would clear the green Settings hint.
    """
    channel = _normalized_update_channel()
    url = selected_update_url()
    if not url:
        return False, ''

    remote_info = _cached_remote_installer_info(channel)
    remote_dt = _remote_compare_datetime(remote_info, channel, url)
    if remote_dt is None and remote_info is None:
        return None, ''

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
    return bool(available)


_READ_CHUNK = 256 * 1024
# Truncated GitHub asset downloads (often ~10 MiB then stall) are common on Windows
# with AV HTTPS scanning — retry the same URL, then try the static release fallback.
_DOWNLOAD_ATTEMPTS_PER_URL = 3


def _normalize_thumbprint(value: str) -> str:
    return ''.join(ch for ch in str(value or '').upper() if ch.isalnum())


def _configured_publisher_thumbprints() -> tuple[str, ...]:
    """Allowlist from constants + optional env override (comma-separated)."""
    out: list[str] = []
    try:
        baked = tuple(INSTALLER_PUBLISHER_CERT_THUMBPRINTS or ())
    except Exception:
        baked = ()
    for item in baked:
        norm = _normalize_thumbprint(item)
        if norm and norm not in out:
            out.append(norm)
    env = (os.environ.get('ZUBCUT_INSTALLER_PUBLISHER_THUMBPRINT') or '').strip()
    if env:
        for part in env.split(','):
            norm = _normalize_thumbprint(part)
            if norm and norm not in out:
                out.append(norm)
    return tuple(out)


def _authenticode_signature_info(tmp_path: str) -> dict:
    """
    Return Authenticode Status + Thumbprint via PowerShell, or {} if skipped/unavailable.
    Keys: status (str), thumbprint (str, normalized).

    Skips the PowerShell probe when no publisher pin is configured (unsigned builds
    are allowed) so updates do not flash a console window.
    """
    if not sys.platform.startswith('win'):
        return {}
    skip = (os.environ.get('ZUBCUT_SKIP_AUTHENTICODE') or '').strip().lower()
    if skip in ('1', 'true', 'yes', 'on'):
        return {}
    # No pin → no need to spawn powershell.exe (NotSigned is allowed).
    if not _configured_publisher_thumbprints():
        return {}
    try:
        import subprocess

        from tools.utils import _windows_subprocess_no_window_kwargs, subprocess_text_kwargs

        safe = tmp_path.replace("'", "''")
        ps = (
            f"$s = Get-AuthenticodeSignature -FilePath '{safe}'; "
            "$tp = ''; if ($null -ne $s.SignerCertificate) { $tp = $s.SignerCertificate.Thumbprint }; "
            "Write-Output ($s.Status.ToString() + '|' + $tp)"
        )
        system_root = os.environ.get('SystemRoot', r'C:\Windows')
        ps_exe = os.path.join(system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        if not os.path.isfile(ps_exe):
            ps_exe = 'powershell.exe'
        proc = subprocess.run(
            [
                ps_exe,
                '-NoProfile',
                '-NonInteractive',
                '-WindowStyle',
                'Hidden',
                '-Command',
                ps,
            ],
            capture_output=True,
            timeout=30,
            check=False,
            **subprocess_text_kwargs(),
            **_windows_subprocess_no_window_kwargs(),
        )
        line = (proc.stdout or '').strip().splitlines()
        raw = (line[-1] if line else '').strip()
        if not raw:
            return {}
        if '|' in raw:
            status, thumb = raw.split('|', 1)
        else:
            status, thumb = raw, ''
        return {
            'status': str(status or '').strip(),
            'thumbprint': _normalize_thumbprint(thumb),
        }
    except Exception:
        return {}


def _authenticode_status(tmp_path: str) -> str:
    """Return Authenticode Status string, or '' if unavailable / skipped."""
    info = _authenticode_signature_info(tmp_path)
    return str(info.get('status') or '')


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
            'The download was truncated — retrying with another link if available.'
        )
    info = _authenticode_signature_info(tmp_path)
    status = str(info.get('status') or '').strip()
    thumb = str(info.get('thumbprint') or '').strip()
    allow = _configured_publisher_thumbprints()
    if allow:
        if not status:
            raise RuntimeError(
                'Could not read Authenticode signature for the downloaded installer. '
                'Refusing update while publisher certificate pinning is enabled.'
            )
        if status.lower() != 'valid':
            raise RuntimeError(
                f'Downloaded installer failed Authenticode check (Status={status}). '
                'Refusing to launch an untrusted update.'
            )
        if thumb not in allow:
            raise RuntimeError(
                'Downloaded installer is signed, but not by the expected ZubCut publisher certificate. '
                'Refusing to launch an untrusted update.'
            )
        return
    # No publisher pin: allow unsigned builds (no paid Authenticode cert yet).
    # Authenticode PowerShell is skipped in that case, so HashMismatch is not probed here.


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
        last_err: BaseException | None = None
        for attempt in range(1, _DOWNLOAD_ATTEMPTS_PER_URL + 1):
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
                last_err = e
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
                        last_err = None
                        break
                if (
                    is_retryable_network_error(e)
                    and attempt < _DOWNLOAD_ATTEMPTS_PER_URL
                ):
                    try:
                        from tools.updater_debug import updater_log

                        updater_log(
                            'download_installer: retry %s/%s after %s',
                            attempt + 1,
                            _DOWNLOAD_ATTEMPTS_PER_URL,
                            e,
                        )
                    except Exception:
                        pass
                    time.sleep(min(1.5 * attempt, 5.0))
                    continue
                break
            except Exception as e:
                last_err = e
                if (
                    is_retryable_network_error(e)
                    and attempt < _DOWNLOAD_ATTEMPTS_PER_URL
                ):
                    time.sleep(min(1.5 * attempt, 5.0))
                    continue
                break
        if last_err is None:
            # Candidate list was refreshed after asset 404 — restart loop.
            continue
        errors.append((candidate, last_err))
        idx += 1
        if not is_retryable_network_error(last_err):
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
    try:
        with resp_cm as resp:
            cl = resp.headers.get('Content-Length')
            if cl:
                try:
                    total = int(cl)
                except ValueError:
                    total = None
            # Prefer GitHub API size when the redirect omits Content-Length.
            if (total is None or total <= 0) and expected_size > 0:
                total = int(expected_size)
            received = 0
            cancelled = False
            with open(tmp_path, 'wb') as fp:
                while True:
                    if should_cancel and should_cancel():
                        cancelled = True
                        break
                    try:
                        chunk = resp.read(_READ_CHUNK)
                    except (http.client.IncompleteRead, TimeoutError, ConnectionError) as e:
                        raise RuntimeError(
                            f'Incomplete download (got {received} bytes'
                            + (f', expected {total}' if total else '')
                            + f'): {e}'
                        ) from e
                    if not chunk:
                        break
                    fp.write(chunk)
                    received += len(chunk)
                    if progress_callback:
                        progress_callback(received, total)
    except RuntimeError:
        raise
    except Exception as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        if _is_incomplete_download_error(e) or isinstance(
            e, (TimeoutError, ConnectionError, http.client.IncompleteRead)
        ):
            raise RuntimeError(
                f'Incomplete download while fetching installer: {e}'
            ) from e
        raise RuntimeError(format_updater_error_message(e)) from e

    if cancelled:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise RuntimeError('Download cancelled.')

    if total is not None and total > 0 and received != total:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise RuntimeError(
            f'Incomplete download (got {received} bytes, Content-Length {total}). '
            'The connection closed early — retrying.'
        )

    _validate_installer_exe(tmp_path, expected_size=expected_size)
    return tmp_path


def _installed_app_dir() -> str:
    """Directory that contains ZubCut.exe after install (frozen) or Program Files default."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    pf = os.environ.get('ProgramFiles') or r'C:\Program Files'
    return os.path.join(pf, APP_BUNDLE_NAME)


def _python_runtime_dll_path(app_dir: str | None = None) -> str:
    root = app_dir or _installed_app_dir()
    return os.path.join(root, '_internal', 'python311.dll')


def install_payload_ok(app_dir: str | None = None) -> bool:
    """True when the onedir Python runtime DLL is present (post-update sanity check)."""
    dll = _python_runtime_dll_path(app_dir)
    try:
        return os.path.isfile(dll) and os.path.getsize(dll) >= 100_000
    except OSError:
        return False


def _windows_job_breakaway_creationflags() -> int:
    """
    Flags so Setup/verifier survive ``quit_all``.

    ZubCut is often in a Windows job that kills children on close. Starting
    Setup *without* breakaway meant: download finishes → app exits → Inno dies
    after creating its temp directory (see %TEMP%\\zubcut-update-install.log).
    """
    creationflags = 0
    if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP'):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
    if hasattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB'):
        creationflags |= subprocess.CREATE_BREAKAWAY_FROM_JOB
    return creationflags


def _write_update_verify_ps1(*, installer_path: str, app_dir: str) -> str:
    """
    Post-update verifier only — does not start Setup.

    Starting Inno from a detached/non-elevated PowerShell broke UAC after quit_all
    (download finished → app closed → setup never installed). Setup must be launched
    directly from the elevated ZubCut process so admin rights inherit.
    """
    ps1 = os.path.join(
        tempfile.gettempdir(), f'{APP_BUNDLE_NAME.lower()}-update-waiter.ps1'
    )

    def _sq(s: str) -> str:
        return "'" + str(s).replace("'", "''") + "'"

    dll = _python_runtime_dll_path(app_dir)
    setup_name = os.path.basename(installer_path)
    script = f"""$ErrorActionPreference = 'Continue'
$dll = {_sq(dll)}
$setupName = {_sq(setup_name)}
$setupProc = [IO.Path]::GetFileNameWithoutExtension($setupName)
function Get-SetupProcesses {{
  $found = @()
  try {{
    $found += @(Get-Process -Name $setupProc -ErrorAction SilentlyContinue)
  }} catch {{}}
  try {{
    $found += @(Get-Process -ErrorAction SilentlyContinue | Where-Object {{
      try {{
        $n = [string]$_.ProcessName
        ($n -like 'ZubCut-Setup*') -or ($n -like 'is-*')
      }} catch {{ $false }}
    }})
  }} catch {{}}
  return @($found | Where-Object {{ $_ }} | Sort-Object Id -Unique)
}}
# Wait until Setup has been seen AND has exited (or 10 minutes).
# Do not treat "not visible yet" as finished — Get-Process .Path is often empty
# on the elevated installer, which used to pop a false "runtime missing" dialog
# while _internal was only renamed aside.
$deadline = (Get-Date).AddMinutes(10)
$sawSetup = $false
while ((Get-Date) -lt $deadline) {{
  $alive = @(Get-SetupProcesses)
  if ($alive.Count -gt 0) {{ $sawSetup = $true }}
  if ($sawSetup -and $alive.Count -eq 0) {{ break }}
  Start-Sleep -Milliseconds 500
}}
$ok = $false
$dllDeadline = (Get-Date).AddMinutes(2)
while ((Get-Date) -lt $dllDeadline) {{
  if (Test-Path -LiteralPath $dll) {{
    try {{ $ok = ((Get-Item -LiteralPath $dll).Length -ge 100000) }} catch {{ $ok = $false }}
    if ($ok) {{ break }}
  }}
  Start-Sleep -Milliseconds 500
}}
if (-not $ok) {{
  Add-Type -AssemblyName System.Windows.Forms
  [void][System.Windows.Forms.MessageBox]::Show(
    "ZubCut update did not finish correctly (Python runtime missing under _internal).`n`n" +
    "Uninstall ZubCut, then reinstall the full setup from the experimental (or stable) download.`n`n" +
    "Expected: $dll",
    "ZubCut Update Failed",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Error
  )
  exit 1
}}
exit 0
"""
    with open(ps1, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(script)
    return ps1


def launch_installer(tmp_path, *, no_ui=False):
    """
    Run the downloaded Inno Setup. no_ui=True uses /VERYSILENT (nothing on screen).
    Default uses /SILENT so a small setup progress window is visible after the app exits.

    Setup is started directly from this process so elevation inherits from ZubCut
    (RUNASADMIN), then broken away from the GUI job so ``quit_all`` cannot kill it.
    A separate verifier only watches for a missing ``python311.dll``.
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
        flags = [
            '/VERYSILENT',
            '/SUPPRESSMSGBOXES',
            '/NORESTART',
            '/FORCECLOSEAPPLICATIONS',
            f'/LOG={install_log}',
        ]
    else:
        flags = [
            '/SILENT',
            '/SUPPRESSMSGBOXES',
            '/NORESTART',
            '/FORCECLOSEAPPLICATIONS',
            f'/LOG={install_log}',
        ]
    if sys.platform.startswith('win'):
        try:
            from tools.clumsy_inline import clumsy_bundle_offered

            if clumsy_bundle_offered():
                flags.append('/MERGETASKS=clumsymode')
        except Exception:
            pass

    installer_abs = os.path.abspath(tmp_path)
    # Direct child so the admin token is inherited — but break away from the
    # GUI job. Without breakaway, quit_all killed Setup in the same job.
    popen_kwargs = {'close_fds': True}
    if sys.platform.startswith('win'):
        popen_kwargs['creationflags'] = _windows_job_breakaway_creationflags()
    subprocess.Popen([installer_abs] + flags, **popen_kwargs)
    try:
        from tools.updater_debug import updater_log

        updater_log('launch_installer: started setup directly path=%r', installer_abs)
    except Exception:
        pass

    if sys.platform.startswith('win'):
        try:
            app_dir = _installed_app_dir()
            ps1 = _write_update_verify_ps1(
                installer_path=installer_abs,
                app_dir=app_dir,
            )
            try:
                from tools.updater_debug import updater_log

                updater_log('launch_installer: verify_waiter=%r app_dir=%r', ps1, app_dir)
            except Exception:
                pass
            # Same breakaway as Setup. Do NOT start Setup from this script
            # (a non-elevated PowerShell would drop UAC).
            subprocess.Popen(
                [
                    'powershell.exe',
                    '-NoProfile',
                    '-ExecutionPolicy',
                    'Bypass',
                    '-WindowStyle',
                    'Hidden',
                    '-File',
                    ps1,
                ],
                close_fds=True,
                creationflags=_windows_job_breakaway_creationflags(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            try:
                from tools.updater_debug import updater_log

                updater_log('launch_installer: verify waiter failed', exc_info=True)
            except Exception:
                pass


def spawn_installer_update(url):
    """
    Download without progress UI, then start Inno with a visible setup progress window.
    Caller should exit the app immediately after this returns.
    """
    path = download_installer(url)
    launch_installer(path, no_ui=False)
