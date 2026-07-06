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
