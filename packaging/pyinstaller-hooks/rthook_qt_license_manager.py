# PyInstaller runtime hook (stdlib only): diagnostic file + Qt plugin paths before PyQt import.
import os
import sys
from datetime import datetime


def _license_manager_log_targets(basename: str):
    """Several paths so logs survive TEMP cleaners / Program Files / missing error handler."""
    out = []
    temp = (os.environ.get('TEMP') or os.environ.get('TMP') or '').strip()
    if temp:
        out.append(os.path.join(temp, basename))
    if sys.platform.startswith('win'):
        ad = os.environ.get('APPDATA', '')
        if ad:
            zd = os.path.join(ad, 'ZubCut')
            try:
                os.makedirs(zd, exist_ok=True)
            except Exception:
                pass
            out.append(os.path.join(zd, basename))
    if getattr(sys, 'frozen', False):
        out.append(os.path.join(os.path.dirname(sys.executable), basename))
    # de-dupe, preserve order
    seen = set()
    uniq = []
    for p in out:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _write_license_manager_boot_chunk(extra_lines):
    stamp = datetime.now().isoformat(timespec='seconds')
    lines = [
        stamp + ' rthook_qt_license_manager (PyInstaller, pre-PyQt)',
        'frozen=' + repr(getattr(sys, 'frozen', False)),
        '_MEIPASS=' + repr(getattr(sys, '_MEIPASS', None)),
        'executable=' + repr(sys.executable),
        'cwd=' + repr(os.getcwd()),
    ]
    lines.extend(extra_lines)
    body = '\n'.join(lines) + '\n\n'
    for path in _license_manager_log_targets('zubcut_license_manager_boot.txt'):
        try:
            with open(path, 'a', encoding='utf-8', errors='replace') as fh:
                fh.write(body)
        except Exception:
            pass


_write_license_manager_boot_chunk(['(before Qt plugin search)'])

if getattr(sys, 'frozen', False):
    _roots = []
    _meipass = getattr(sys, '_MEIPASS', None)
    if _meipass:
        _roots.append(_meipass)
    _exe_dir = os.path.dirname(sys.executable)
    _roots.append(os.path.join(_exe_dir, '_internal'))
    _roots.append(_exe_dir)
    _seen = set()
    _found = None
    for _root in _roots:
        if not _root or _root in _seen:
            continue
        _seen.add(_root)
        for _parts in (('PyQt5', 'Qt5', 'plugins'), ('PyQt5', 'Qt', 'plugins')):
            _plugins = os.path.join(_root, *_parts)
            _qwin = os.path.join(_plugins, 'platforms', 'qwindows.dll')
            if os.path.isfile(_qwin):
                os.environ['QT_PLUGIN_PATH'] = _plugins
                os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(_plugins, 'platforms')
                _found = _qwin
                break
        if _found:
            break
    _write_license_manager_boot_chunk(
        [
            'qwindows.dll=' + repr(_found),
            'QT_PLUGIN_PATH=' + repr(os.environ.get('QT_PLUGIN_PATH')),
            'QT_QPA_PLATFORM_PLUGIN_PATH=' + repr(os.environ.get('QT_QPA_PLATFORM_PLUGIN_PATH')),
        ]
    )
else:
    _write_license_manager_boot_chunk(['(non-frozen: skipped Qt path override)'])
