#!/usr/bin/env python3
"""List and inspect ZubCut crash reports stored on the license worker (developer PC)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from constants import CRASH_REPORT_URL, LICENSE_SIGNIN_URL  # noqa: E402


def _base_url() -> str:
    return (
        os.environ.get('ZUBCUT_CRASH_REPORT_URL')
        or os.environ.get('ZUBCUT_LICENSE_SIGNIN_URL')
        or os.environ.get('ZUBCUT_PAID_SIGNIN_URL')
        or CRASH_REPORT_URL
        or LICENSE_SIGNIN_URL
        or ''
    ).strip().rstrip('/')


def _admin_secret() -> str:
    return (
        os.environ.get('ZUBCUT_ADMIN_SECRET')
        or os.environ.get('ZUBCUT_LICENSE_ADMIN_SECRET')
        or ''
    ).strip()


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = _base_url()
    if not base:
        raise SystemExit('Set ZUBCUT_LICENSE_SIGNIN_URL or CRASH_REPORT_URL in constants.')
    url = f'{base}{path}'
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        err = exc.read().decode('utf-8', errors='replace')
        try:
            data = json.loads(err)
            msg = data.get('error') or err
        except Exception:
            msg = err or str(exc)
        raise SystemExit(f'HTTP {exc.code}: {msg}') from exc


def cmd_list(args: argparse.Namespace) -> int:
    secret = _admin_secret()
    if not secret:
        raise SystemExit('Set ZUBCUT_ADMIN_SECRET to your worker ADMIN_SECRET.')
    data = _post('/admin/crashes/list', {'secret': secret, 'limit': args.limit})
    crashes = data.get('crashes') or []
    print(f'worker={_base_url()} total={data.get("total", len(crashes))} showing={len(crashes)}')
    for row in crashes:
        ref = row.get('ref', '?')
        when = row.get('received_at') or row.get('time_utc') or ''
        acct = row.get('account_hint') or ''
        exc = row.get('exc_type') or ''
        msg = (row.get('exc_message') or '')[:80]
        print(f'{ref}\t{when}\t{acct}\t{exc}\t{msg}')
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    secret = _admin_secret()
    if not secret:
        raise SystemExit('Set ZUBCUT_ADMIN_SECRET to your worker ADMIN_SECRET.')
    ref = str(args.ref or '').strip().upper()
    data = _post('/admin/crash/get', {'secret': secret, 'ref': ref})
    report = data.get('report') or {}
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f'ref={report.get("ref")}')
    print(f'received_at={report.get("received_at")}')
    print(f'account_hint={report.get("account_hint")}')
    print(f'build={report.get("build_channel")} {report.get("build_commit")} {report.get("app_version")}')
    print(f'exc={report.get("exc_type")}: {report.get("exc_message")}')
    print('--- body ---')
    print(report.get('body') or '')
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(report.get('body') or '')
        print(f'wrote {args.out}')
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    secret = _admin_secret()
    if not secret:
        raise SystemExit('Set ZUBCUT_ADMIN_SECRET to your worker ADMIN_SECRET.')
    ref = str(args.ref or '').strip().upper()
    _post('/admin/crash/delete', {'secret': secret, 'ref': ref})
    print(f'deleted {ref}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='ZubCut crash reports admin CLI')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='List recent crash reports')
    p_list.add_argument('--limit', type=int, default=50)
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser('get', help='Fetch one crash report by ref (e.g. ZC-ABC123)')
    p_get.add_argument('ref')
    p_get.add_argument('--json', action='store_true')
    p_get.add_argument('--out', help='Write crash body to this file')
    p_get.set_defaults(func=cmd_get)

    p_del = sub.add_parser('delete', help='Delete a crash report from KV')
    p_del.add_argument('ref')
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == '__main__':
    raise SystemExit(main())
