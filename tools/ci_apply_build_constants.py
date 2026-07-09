#!/usr/bin/env python3
"""
Patch src/constants.py after CI copies .github/ci-blessed/constants.py.

Git branch ``main`` is the stable / production line. UPDATE_CHANNEL in binaries
stays ``main``; workflow_dispatch may pass ``stable`` as an alias for ``main``.

Secrets: LICENSE_PUBLIC_KEY_B64 (or PAID_LICENSE_PUBLIC_KEY_B64), LICENSE_SIGNIN_URL,
optional CRASH_INGEST_TOKEN (baked into experimental/main builds for POST /crash).
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
    crash_ingest = os.getenv("CRASH_INGEST_TOKEN", "").strip()

    def _sub_assign(name: str, value: str, body: str) -> str:
        """Replace NAME = ... including parenthesized multi-line values."""
        pat = rf"^{re.escape(name)}\s*=(?:\s*\([^)]*\)|\s*[^\n]*)"
        repl = f"{name} = {value}"
        new_body, n = re.subn(pat, repl, body, count=1, flags=re.M | re.S)
        if n != 1:
            raise SystemExit(f"Could not find assignment for {name} in constants.py")
        return new_body

    txt = _sub_assign("UPDATE_CHANNEL", repr(channel), txt)
    if main_url:
        txt = _sub_assign("UPDATE_DOWNLOAD_URL_MAIN", repr(main_url), txt)
    if experimental_url:
        txt = _sub_assign("UPDATE_DOWNLOAD_URL_EXPERIMENTAL", repr(experimental_url), txt)

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
    elif channel in ("main", "experimental") and lic_pubkey and not signin_url:
        print(
            "NOTE: LICENSE_SIGNIN_URL secret not set; using default from constants.py",
            file=sys.stderr,
        )

    if crash_ingest:
        if "CRASH_INGEST_TOKEN" not in txt:
            raise SystemExit(
                "constants.py is missing CRASH_INGEST_TOKEN; cannot inject crash ingest secret."
            )
        txt = re.sub(
            r"^CRASH_INGEST_TOKEN\s*=.*$",
            f"CRASH_INGEST_TOKEN = {crash_ingest!r}",
            txt,
            flags=re.M,
        )
    elif channel in ("main", "experimental"):
        print(
            "NOTE: CRASH_INGEST_TOKEN secret not set; POST /crash stays open unless Worker secret is unset too.",
            file=sys.stderr,
        )

    build_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    txt = re.sub(r"^APP_BUILD_TIME_ISO\s*=.*$", f"APP_BUILD_TIME_ISO = {build_iso!r}", txt, flags=re.M)
    commit = os.getenv("GITHUB_SHA", "").strip()
    txt = re.sub(
        r"^APP_BUILD_COMMIT\s*=.*$",
        f"APP_BUILD_COMMIT = {commit!r}",
        txt,
        flags=re.M,
    )
    p.write_text(txt, encoding="utf-8")
    print(f"Applied UPDATE_CHANNEL={channel} for ref={os.getenv('REF_NAME')}")


if __name__ == "__main__":
    main()
