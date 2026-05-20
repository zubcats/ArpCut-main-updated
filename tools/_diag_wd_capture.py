"""Live WinDivert capture diagnostic for ICS hotspot."""
from __future__ import annotations

import ctypes
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(_ROOT, 'src'))

from tools import ics_windivert_shaper as wd
from tools.clumsy_inline import (
    clumsy_ics_downstream_ifidx,
    clumsy_ics_downstream_prefix,
    read_clumsy_ics_state,
)
from tools.utils import terminal

VIP = '192.168.137.194'


def main() -> None:
    state = read_clumsy_ics_state()
    name = state.get('downstream_name')
    guid = state.get('downstream_guid')
    print('downstream_name', repr(name))
    print('downstream_guid', guid)
    if guid:
        out = terminal(
            f'powershell -NoProfile -Command '
            f'"(Get-NetAdapter -InterfaceGuid \'{guid}\' -ErrorAction SilentlyContinue).ifIndex"'
        )
        print('ifidx via guid', repr(out))
    print('ifidx helper', clumsy_ics_downstream_ifidx())

    dll_path, sys_path = wd._windivert_materialize_paths()
    if not dll_path:
        print('no windivert dll')
        return
    repaired, note = wd._windivert_repair_stale_service(sys_path)
    print('repair', repaired, note)
    dll = wd._windivert_load_dll(dll_path, sys_path)
    wd._bind_windivert_api(dll)
    prefix = clumsy_ics_downstream_prefix()

    extra = [
        ('true', 'true', (0, 1)),
        ('ip_or_ipv6', 'ip or ipv6', (0, 1)),
    ]
    for filt, desc, layers in extra:
        for layer in layers:
            h = wd._open_windivert_handle(dll, filt, layer)
            seen = ipv4 = victim = 0
            if h >= 0:
                buf = (ctypes.c_ubyte * 65535)()
                addr = (ctypes.c_ubyte * 64)()
                rl = ctypes.c_uint(0)
                al = ctypes.c_uint(64)
                t0 = time.time()
                while time.time() - t0 < 2.0:
                    rl.value = 0
                    al.value = 64
                    ok = dll.WinDivertRecvEx(
                        h,
                        ctypes.cast(buf, ctypes.c_void_p),
                        65535,
                        ctypes.byref(rl),
                        0,
                        ctypes.cast(addr, ctypes.c_void_p),
                        ctypes.byref(al),
                        None,
                    )
                    if ok and rl.value > 0:
                        seen += 1
                        pkt = bytes(ctypes.string_at(ctypes.addressof(buf), rl.value))
                        p = wd._parse_ipv4_src_dst(pkt)
                        if p:
                            ipv4 += 1
                            src, dst = p
                            if src == VIP or dst == VIP:
                                victim += 1
                dll.WinDivertClose(h)
            print(f'{desc:12} L{layer} h={h:3} seen={seen:4} ipv4={ipv4:4} victim={victim:4}')

    for filt, desc in wd._ics_windivert_open_candidates(VIP, prefix):
        if desc == 'victim':
            layers = (0, 1)
        elif desc == 'forward':
            layers = (1,)
        else:
            layers = (1, 0)
        for layer in layers:
            h = wd._open_windivert_handle(dll, filt, layer)
            seen = ipv4 = victim = 0
            if h >= 0:
                buf = (ctypes.c_ubyte * 65535)()
                addr = (ctypes.c_ubyte * 64)()
                rl = ctypes.c_uint(0)
                al = ctypes.c_uint(64)
                t0 = time.time()
                while time.time() - t0 < 2.0:
                    rl.value = 0
                    al.value = 64
                    ok = dll.WinDivertRecvEx(
                        h,
                        ctypes.cast(buf, ctypes.c_void_p),
                        65535,
                        ctypes.byref(rl),
                        0,
                        ctypes.cast(addr, ctypes.c_void_p),
                        ctypes.byref(al),
                        None,
                    )
                    if ok and rl.value > 0:
                        seen += 1
                        pkt = bytes(ctypes.string_at(ctypes.addressof(buf), rl.value))
                        p = wd._parse_ipv4_src_dst(pkt)
                        if p:
                            ipv4 += 1
                            src, dst = p
                            if src == VIP or dst == VIP:
                                victim += 1
                dll.WinDivertClose(h)
            print(
                f'{desc:12} L{layer} h={h:3} seen={seen:4} ipv4={ipv4:4} '
                f'victim={victim:4} filt={filt[:70]!r}'
            )


if __name__ == '__main__':
    main()
