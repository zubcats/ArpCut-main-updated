#!/usr/bin/env python3
"""Remote license sign-in diagnostics (no GUI). Run from repo root."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.license_remote_signin import (  # noqa: E402
    effective_signin_url,
    fetch_remote_verify_key_b64,
    probe_signin_configuration,
)


def main() -> int:
    url = effective_signin_url()
    print('=== ZubCut license sign-in remote diagnose ===')
    print(f'signin_url={url}')
    pk_url = f'{url.rstrip("/")}/public-key' if url else ''
    if pk_url:
        print(f'public_key_url={pk_url}')
        pk = fetch_remote_verify_key_b64(url)
        print(
            f'public_key_fetch={"ok len=" + str(len(pk)) if pk else "not available (optional)"}'
        )
    ok, report = probe_signin_configuration()
    print(report)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
