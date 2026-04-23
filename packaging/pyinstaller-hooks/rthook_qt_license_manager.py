# PyInstaller runtime hook: set Qt paths before any PyQt import (stdlib only).
import os
import sys

if getattr(sys, 'frozen', False):
    _roots = []
    _meipass = getattr(sys, '_MEIPASS', None)
    if _meipass:
        _roots.append(_meipass)
    _exe_dir = os.path.dirname(sys.executable)
    _roots.append(os.path.join(_exe_dir, '_internal'))
    _roots.append(_exe_dir)
    _seen = set()
    for _root in _roots:
        if not _root or _root in _seen:
            continue
        _seen.add(_root)
        _hit = False
        for _parts in (('PyQt5', 'Qt5', 'plugins'), ('PyQt5', 'Qt', 'plugins')):
            _plugins = os.path.join(_root, *_parts)
            _qwin = os.path.join(_plugins, 'platforms', 'qwindows.dll')
            if os.path.isfile(_qwin):
                os.environ['QT_PLUGIN_PATH'] = _plugins
                os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(_plugins, 'platforms')
                _hit = True
                break
        if _hit:
            break
