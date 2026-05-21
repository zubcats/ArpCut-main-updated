import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from tools import ics_windivert_shaper as wd

out = os.path.join(os.path.dirname(__file__), '_probe_wd_result.txt')
lines = [f'admin={bool(ctypes.windll.shell32.IsUserAnAdmin())}', f'cwd={os.getcwd()}']

dll, sys_p = wd._windivert_materialize_paths()
lines.append(f'materialize={dll} | {sys_p}')

inst = wd._windivert_install_paths()
lines.append(f'install={inst}')

def try_open(label, dll_path):
    old = os.getcwd()
    dll_dir = os.path.dirname(dll_path)
    try:
        os.chdir(dll_dir)
        dll = wd._windivert_load_dll(dll_path)
        wd._bind_windivert_api(dll)
        for filt in ('true', 'ip', wd._ics_clumsy_victim_filter('192.168.137.194')):
            for layer in (0, 1):
                h = wd._open_windivert_handle(dll, filt, layer)
                if h >= 0:
                    dll.WinDivertClose(h)
                    lines.append(f'{label} OK filter={filt!r} layer={layer} cwd={os.getcwd()}')
                    return True
                lines.append(
                    f'{label} fail filter={filt!r} layer={layer} err={wd._windivert_last_error_message()}'
                )
    except Exception as exc:
        lines.append(f'{label} exception: {exc}')
    finally:
        try:
            os.chdir(old)
        except OSError:
            pass
    return False

if dll:
    try_open('cache', dll)
if inst[0]:
    try_open('install', inst[0])

ok, msg = wd.probe_windivert_for_victim('192.168.137.194')
lines.append(f'probe={ok} {msg}')

with open(out, 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(lines) + '\n')
print('wrote', out)
