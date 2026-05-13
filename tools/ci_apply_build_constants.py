#!/usr/bin/env python3
"""
Patch src/constants.py after CI copies .github/ci-blessed/constants.py.

Git branch ``main`` is the stable / production line. UPDATE_CHANNEL in binaries
stays ``main``; workflow_dispatch may pass ``stable`` as an alias for ``main``.

Secrets: LICENSE_PUBLIC_KEY_B64 (or PAID_LICENSE_PUBLIC_KEY_B64), LICENSE_SIGNIN_URL.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    p = Path("src/constants.py")
    if not p.is_file():
        print("ERROR: src/constants.py not found", file=sys.stderr)
        sys.exit(1)

    txt = p.read_text(encoding="utf-8")
    if "LICENSE_PUBLIC_KEY_B64" not in txt:
        raise SystemExit(
            "constants.py is missing LICENSE_PUBLIC_KEY_B64 (unexpected layout after ci-blessed copy)."
        )

    ref_name = os.getenv("REF_NAME", "").lower()
    ref_type = os.getenv("REF_TYPE", "").lower()
    requested = os.getenv("REQUESTED_CHANNEL", "").strip().lower()
    if requested in ("stable", "main"):
        channel = "main"
    elif requested == "experimental":
        channel = "experimental"
    elif ref_name == "main" or ref_type == "tag":
        channel = "main"
    else:
        channel = "experimental"

    main_url = os.getenv("UPDATE_URL_MAIN", "")
    experimental_url = os.getenv("UPDATE_URL_EXPERIMENTAL", "")
    lic_pubkey = os.getenv("LICENSE_PUBLIC_KEY_B64", "").strip()
    signin_url = os.getenv("LICENSE_SIGNIN_URL", "").strip()

    txt = re.sub(r"^UPDATE_CHANNEL\s*=.*$", f"UPDATE_CHANNEL = '{channel}'", txt, flags=re.M)
    if main_url:
        txt = re.sub(
            r"^UPDATE_DOWNLOAD_URL_MAIN\s*=.*$",
            f"UPDATE_DOWNLOAD_URL_MAIN = {main_url!r}",
            txt,
            flags=re.M,
        )
    if experimental_url:
        txt = re.sub(
            r"^UPDATE_DOWNLOAD_URL_EXPERIMENTAL\s*=.*$",
            f"UPDATE_DOWNLOAD_URL_EXPERIMENTAL = {experimental_url!r}",
            txt,
            flags=re.M,
        )

    if channel in ("main", "experimental") and not lic_pubkey:
        raise SystemExit(
            "Missing required secret LICENSE_PUBLIC_KEY_B64 (or PAID_LICENSE_PUBLIC_KEY_B64) "
            "for main/experimental builds."
        )
    if channel in ("main", "experimental") and lic_pubkey:
        if "LICENSE_PUBLIC_KEY_B64" not in txt:
            raise SystemExit("constants.py is missing LICENSE_PUBLIC_KEY_B64; cannot inject signing key.")
        txt = re.sub(
            r"^LICENSE_PUBLIC_KEY_B64\s*=.*$",
            f"LICENSE_PUBLIC_KEY_B64 = {lic_pubkey!r}",
            txt,
            flags=re.M,
        )

    if signin_url:
        if "LICENSE_SIGNIN_URL" not in txt:
            raise SystemExit("constants.py is missing LICENSE_SIGNIN_URL; cannot inject sign-in URL.")
        txt = re.sub(
            r"^LICENSE_SIGNIN_URL\s*=.*$",
            f"LICENSE_SIGNIN_URL = {signin_url!r}",
            txt,
            flags=re.M,
        )
    elif channel == "main" and lic_pubkey:
        raise SystemExit(
            "Missing LICENSE_SIGNIN_URL: add repository secret LICENSE_SIGNIN_URL with your "
            "Worker HTTPS URL (same as License Manager 'Cloud sign-in sync'). "
            "Required for stable (main-channel) builds when LICENSE_PUBLIC_KEY_B64 is set."
        )

    build_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    txt = re.sub(r"^APP_BUILD_TIME_ISO\s*=.*$", f"APP_BUILD_TIME_ISO = {build_iso!r}", txt, flags=re.M)
    p.write_text(txt, encoding="utf-8")
    print(f"Applied UPDATE_CHANNEL={channel} for ref={os.getenv('REF_NAME')}")


if __name__ == "__main__":
    main()
