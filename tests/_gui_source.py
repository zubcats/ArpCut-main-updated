"""Load combined GUI source for string-contract tests after MainWindow split."""
from __future__ import annotations

import os
import re

_SRC = os.path.join(os.path.dirname(__file__), '..', 'src')
_GUI = os.path.join(_SRC, 'gui')

_IMPAIRMENT_MODULES = (
    'main.py',
    'impairment_shared.py',
    'impairment_controller.py',
    'impairment_plan.py',
    'impairment_prep.py',
    'impairment_ics_gate.py',
    'impairment_blocks.py',
    'impairment_lag.py',
    'impairment_dupe.py',
    'impairment_kill.py',
    'impairment_pctcut.py',
    'impairment_mitm.py',
    'impairment_flow_net.py',
)


def gui_src_root() -> str:
    return _SRC


def _read(name: str) -> str:
    path = os.path.join(_GUI, name)
    with open(path, encoding='utf-8') as f:
        return f.read()


def load_main_window_source() -> str:
    """Concatenated source of MainWindow + extracted impairment mixins."""
    parts = []
    for name in _IMPAIRMENT_MODULES:
        path = os.path.join(_GUI, name)
        if os.path.isfile(path):
            parts.append(_read(name))
    return '\n'.join(parts)


def load_gui_file(relative: str) -> str:
    return _read(relative)


def _method_span_in_text(text: str, name: str):
    """Return (start, end) of `def name` including leading decorators, or None."""
    pat = re.compile(
        r'(?:^[ \t]*@[^\n]*\n)*^[ \t]*def ' + re.escape(name) + r'\(',
        re.M,
    )
    m = pat.search(text)
    if not m:
        return None
    start = m.start()
    rest = text[m.end():]
    nxt = re.search(r'\n    (?:@[^\n]*\n    )*def [A-Za-z_]', rest)
    if nxt:
        end = m.end() + nxt.start()
    else:
        nxt2 = re.search(r'\n(?:def |class |"""|[a-zA-Z])', rest)
        end = m.end() + nxt2.start() if nxt2 else len(text)
    return start, end


def method_src(name: str) -> str:
    """Return one method (with decorators) from whichever impairment module defines it."""
    for mod in _IMPAIRMENT_MODULES:
        path = os.path.join(_GUI, mod)
        if not os.path.isfile(path):
            continue
        text = _read(mod)
        span = _method_span_in_text(text, name)
        if span:
            return text[span[0]:span[1]]
    raise KeyError(f'method {name!r} not found in impairment modules')


def methods_through(start_name: str, end_name: str) -> str:
    """
    Source from start_name through the method before end_name.

    If both live in the same file and end follows start, return that slice.
    Otherwise return only start_name (end was the historical next-method sentinel).
    """
    for mod in _IMPAIRMENT_MODULES:
        path = os.path.join(_GUI, mod)
        if not os.path.isfile(path):
            continue
        text = _read(mod)
        a = _method_span_in_text(text, start_name)
        if not a:
            continue
        b = _method_span_in_text(text, end_name)
        if b and b[0] > a[0]:
            return text[a[0]:b[0]]
        return text[a[0]:a[1]]
    raise KeyError(f'method {start_name!r} not found')
