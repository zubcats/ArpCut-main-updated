"""Sync embedded PowerShell diag scripts from src/tools/*.py into tools/*.ps1."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PAIRS = [
    ('src/tools/support_hotspot_path_diag.py', 'tools/ZubCut-Hotspot-Path-Diag.ps1'),
    ('src/tools/support_quick_diag.py', 'tools/ZubCut-Quick-Network-Diag.ps1'),
    ('src/tools/support_lan_path_diag.py', 'tools/ZubCut-Lan-Path-Diag.ps1'),
    ('src/tools/support_wifi_link_diag.py', 'tools/ZubCut-Wifi-Link-Diag.ps1'),
]


def extract_embedded(py_text: str) -> str | None:
    m = re.search(r'_EMBEDDED_\w+_PS1\s*=\s*r"""(.*?)"""', py_text, re.S)
    if m:
        return m.group(1).lstrip('\n')
    m = re.search(r'_EMBEDDED_\w+_PS1\s*=\s*r\'\'\'(.*?)\'\'\'', py_text, re.S)
    if m:
        return m.group(1).lstrip('\n')
    return None


def main() -> None:
    for src_rel, dst_rel in PAIRS:
        src = ROOT / src_rel
        dst = ROOT / dst_rel
        if not src.is_file():
            print('missing', src_rel)
            continue
        body = extract_embedded(src.read_text(encoding='utf-8'))
        if not body:
            print('no embed', src_rel)
            continue
        dst.write_text(body, encoding='utf-8', newline='\n')
        print(f'synced {dst_rel} ({len(body)} chars)')


if __name__ == '__main__':
    main()
