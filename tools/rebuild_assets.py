"""
One-off / maintainer: trim assets.py to ZubCut logo loader + toolbar icons only.
Run from repo root: python tools/rebuild_assets.py
"""
from pathlib import Path
import os
import sys

KEEP_ORDER = [
    'kill_icon',
    'killall_icon',
    'scan_easy_icon',
    'scan_hard_icon',
    'settings_icon',
    'unkillall_icon',
]

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / 'src' / 'assets.py'


def main():
    lines = OLD.read_text(encoding='utf-8').splitlines()
    found = {}
    for ln in lines:
        for name in KEEP_ORDER:
            if ln.startswith(f'{name} = '):
                found[name] = ln
                break
    missing = [k for k in KEEP_ORDER if k not in found]
    if missing:
        raise SystemExit(f'Missing assignments: {missing}')

    header = '''"""
UI assets: the app logo is loaded from ``exe/zubcut_icon.png`` (also bundled
next to the frozen exe). Toolbar glyphs remain embedded bytes below; swap PNGs
and re-run this script if you add files under ``exe/actions/``.
"""
import os
import sys


def _zubcut_logo_bytes():
    candidates = []
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidates.append(os.path.join(meipass, 'zubcut_icon.png'))
        candidates.append(os.path.join(os.path.dirname(sys.executable), 'zubcut_icon.png'))
    _here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.normpath(os.path.join(_here, '..', 'exe', 'zubcut_icon.png')))
    for path in candidates:
        if path and os.path.isfile(path):
            with open(path, 'rb') as fp:
                return fp.read()
    return b''


app_icon = _zubcut_logo_bytes()

'''

    body = '\n\n'.join(found[k] for k in KEEP_ORDER) + '\n'
    OLD.write_text(header + body, encoding='utf-8')
    print(f'Wrote {OLD} ({len(header + body)} chars)')


if __name__ == '__main__':
    main()
