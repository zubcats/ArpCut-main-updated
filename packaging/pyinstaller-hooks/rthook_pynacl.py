"""PyInstaller runtime hook: ensure PyNaCl/libsodium load in frozen onedir builds (Windows)."""

import os
import sys


def _bootstrap_pynacl_path() -> None:
    if not getattr(sys, 'frozen', False):
        return
    bases: list[str] = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass and os.path.isdir(meipass):
        bases.append(meipass)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    internal = os.path.join(exe_dir, '_internal')
    for candidate in (internal, exe_dir):
        if candidate and os.path.isdir(candidate) and candidate not in bases:
            bases.append(candidate)
    for base in bases:
        if base not in sys.path:
            sys.path.insert(0, base)
    if sys.platform.startswith('win'):
        for base in bases:
            try:
                os.add_dll_directory(base)
            except (AttributeError, OSError):
                pass
            nacl_dir = os.path.join(base, 'nacl')
            if os.path.isdir(nacl_dir):
                try:
                    os.add_dll_directory(nacl_dir)
                except (AttributeError, OSError):
                    pass


_bootstrap_pynacl_path()
