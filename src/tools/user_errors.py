"""Sanitize text shown in error dialogs (ZC- codes, updater, sign-in)."""
from __future__ import annotations

import re

_GITHUB_URL_RE = re.compile(
    r'https?://(?:www\.)?(?:api\.)?github(?:usercontent)?\.com\S*',
    re.IGNORECASE,
)


def scrub_user_error_text(text: str) -> str:
    """Remove GitHub URLs and branding from user-visible error strings."""
    s = str(text or '')
    s = _GITHUB_URL_RE.sub('the update server', s)
    s = re.sub(r'\bGitHub Releases\b', 'the official release', s, flags=re.IGNORECASE)
    s = re.sub(r'\bGitHub\b', 'the official update server', s, flags=re.IGNORECASE)
    return s


def safe_text_lines(text) -> list[str]:
    """Like str.splitlines() but never raises when text is None."""
    if text is None:
        return []
    return str(text).splitlines()


def format_build_version_hint() -> str:
    """Short build stamp for support dialogs (empty when running from source)."""
    try:
        from constants import APP_BUILD_COMMIT

        commit = str(APP_BUILD_COMMIT or '').strip()[:12]
    except Exception:
        commit = ''
    return f'\n\nBuild: {commit}' if commit else ''
