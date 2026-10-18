#!/usr/bin/env python3
"""ZubLock desktop toggle. Standalone — not part of ZubCut."""
from __future__ import annotations

import ctypes
import ipaddress
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

from zublock_engine import (
    DivertDrop,
    discover_hotspot_clients,
    discover_hotspot_console,
    is_hotspot_console_ip,
)
from zublock_rules import load_ranges

ROOT = Path(__file__).resolve().parent
BG = '#141414'
BTN = '#2b2b2b'
BORDER = '#3d3d3d'
ACCENT = '#316E69'
TEXT = '#e8eaed'
MUTED = '#9a9a9a'
ICO = ROOT / 'zublock.ico'
TASKBAR_ICO = ROOT / 'zublock_taskbar.ico'
APP_USER_MODEL_ID = 'ZubOnTop.ZubLock'


def _admin() -> bool:
    if not sys.platform.startswith('win'):
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_admin() -> bool:
    if _admin():
        return True
    script = str(Path(__file__).resolve())
    params = f'"{script}"'
    rc = ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable, params, None, 1)
    return int(rc) > 32


def _set_app_user_model_id() -> None:
    if not sys.platform.startswith('win'):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def _apply_taskbar_icon(root: tk.Tk) -> None:
    """White ZC mark on the Windows taskbar (same as other Zub apps). pythonw defaults to a snake."""
    if not sys.platform.startswith('win'):
        return
    ico = TASKBAR_ICO if TASKBAR_ICO.is_file() else ICO
    if not ico.is_file():
        return
    try:
        from ctypes import wintypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        GCL_HICON = -14
        GCL_HICONSM = -34
        user32.LoadImageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.LoadImageW.restype = ctypes.c_void_p
        path = str(ico.resolve())
        h_sm = int(user32.LoadImageW(None, path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE) or 0)
        h_lg = int(user32.LoadImageW(None, path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE) or 0)
        if not h_sm and not h_lg:
            return
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        if h_sm:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_sm)
        if h_lg:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_lg)
        try:
            set_cls = user32.SetClassLongPtrW
            set_cls.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_size_t]
            set_cls.restype = ctypes.c_size_t
        except AttributeError:
            set_cls = user32.SetClassLongW
        if h_lg:
            set_cls(hwnd, GCL_HICON, h_lg)
        if h_sm:
            set_cls(hwnd, GCL_HICONSM, h_sm)
    except Exception:
        pass


def _dark_titlebar(root: tk.Tk) -> None:
    if not sys.platform.startswith('win'):
        return
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        value = ctypes.c_int(1)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title('ZubLock')
        self.configure(bg=BG)
        self.geometry('440x420')
        self.resizable(False, False)
        if ICO.is_file():
            try:
                self.iconbitmap(str(ICO))
            except Exception:
                pass
        _dark_titlebar(self)
        _apply_taskbar_icon(self)
        self.protocol('WM_DELETE_WINDOW', self._quit)
        self._divert: DivertDrop | None = None
        self._on_since = 0.0
        self._hotspot_ips = discover_hotspot_clients()
        body = tkfont.Font(family='Segoe UI', size=11)
        big = tkfont.Font(family='Segoe UI', size=16, weight='bold')
        small = tkfont.Font(family='Segoe UI', size=9)

        tk.Label(self, text='ZubLock', fg=TEXT, bg=BG, font=big).pack(pady=(18, 4))
        tk.Label(
            self,
            text='Keep a PlayStation session on this PC hotspot. Other devices stay on house Wi-Fi.',
            fg=MUTED,
            bg=BG,
            font=body,
            wraplength=400,
            justify='center',
        ).pack(padx=20)

        ip_row = tk.Frame(self, bg=BG)
        ip_row.pack(pady=(16, 4))
        tk.Label(ip_row, text='Console IP', fg=MUTED, bg=BG, font=small).pack(side='left', padx=(0, 8))
        self.ip_var = tk.StringVar(value=discover_hotspot_console())
        self.ip_entry = tk.Entry(
            ip_row,
            textvariable=self.ip_var,
            width=18,
            bg=BTN,
            fg=TEXT,
            insertbackground=TEXT,
            relief='flat',
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=body,
        )
        self.ip_entry.pack(side='left')
        tk.Button(
            ip_row,
            text='Find',
            command=self._find,
            bg=BTN,
            fg=TEXT,
            activebackground=BORDER,
            activeforeground=TEXT,
            relief='flat',
            padx=10,
            font=small,
        ).pack(side='left', padx=(8, 0))

        self.status = tk.Label(self, text='Lock OFF', fg=TEXT, bg=BG, font=body, justify='left')
        self.status.pack(pady=(14, 8))

        row = tk.Frame(self, bg=BG)
        row.pack(pady=8)
        self.on_btn = tk.Button(
            row,
            text='Lock ON',
            font=big,
            width=12,
            command=self._on,
            bg=ACCENT,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground=TEXT,
            relief='flat',
            padx=8,
            pady=10,
        )
        self.on_btn.pack(side='left', padx=8)
        self.off_btn = tk.Button(
            row,
            text='Lock OFF',
            font=big,
            width=12,
            command=self._off,
            bg=BTN,
            fg=TEXT,
            activebackground=BORDER,
            activeforeground=TEXT,
            relief='flat',
            padx=8,
            pady=10,
        )
        self.off_btn.pack(side='left', padx=8)

        self.hint = tk.Label(
            self,
            text='Put the console on this PC hotspot. Leave this window open while locked.',
            fg=MUTED,
            bg=BG,
            font=small,
            wraplength=400,
            justify='center',
        )
        self.hint.pack(pady=(16, 0), padx=20)
        if not _admin():
            self.hint.config(text='Administrator is required. Close this window and open ZubLock again to approve UAC.')
        self.after(400, self._tick)

    def _find(self) -> None:
        self._hotspot_ips = discover_hotspot_clients()
        self.ip_var.set(self._hotspot_ips[0] if self._hotspot_ips else discover_hotspot_console())

    def _console_ip(self) -> str:
        raw = (self.ip_var.get() or '').strip()
        try:
            raw = str(ipaddress.IPv4Address(raw))
        except Exception:
            raw = discover_hotspot_console()
            self.ip_var.set(raw)
        return raw

    def _on(self) -> None:
        if not _admin():
            self.hint.config(text='Run ZubLock as Administrator (UAC).')
            return
        ip = self._console_ip()
        if not is_hotspot_console_ip(ip):
            self.hint.config(
                text='Console must be on this PC hotspot (192.168.137.x). House Wi-Fi IPs will not lock.'
            )
            return
        try:
            rules = load_ranges()
        except Exception as exc:
            self.hint.config(text=str(exc))
            return
        if self._divert is not None:
            self._divert.stop()
        self._divert = DivertDrop(ip)
        self._divert.set_rules(rules)
        err = self._divert.start()
        if err:
            self.hint.config(text=err)
            self._divert = None
            return
        self._hotspot_ips = discover_hotspot_clients()
        self._on_since = time.monotonic()
        self.hint.config(
            text='Lock ON. Keep this window open. Game UDP stays up; PSN session HTTPS is dropped.'
        )
        self._refresh()

    def _off(self) -> None:
        if self._divert is not None:
            self._divert.stop()
            self._divert = None
        self.hint.config(text='Lock OFF — the other console can take the session again.')
        self._refresh()

    def _refresh(self) -> None:
        locked = self._divert is not None and self._divert.running
        parts = [f'Lock: {"ON" if locked else "OFF"}']
        if self._hotspot_ips:
            parts.append('Hotspot console: ' + self._hotspot_ips[0])
        if locked and self._divert is not None:
            extra = f'Dropped {self._divert.dropped}  ·  forwarded {self._divert.forwarded}'
            if self._divert.send_fail:
                extra += f'  ·  send-fail {self._divert.send_fail}'
            if self._divert.layers:
                extra += f'  ·  {self._divert.layers}'
            parts.append(extra)
            if self._divert.send_fail:
                self.hint.config(
                    text='Packets are not going back on the wire. Lock OFF, close ZubLock, then open it again.'
                )
            idle = (
                self._divert.dropped == 0
                and self._divert.forwarded == 0
                and self._on_since
                and (time.monotonic() - self._on_since) > 6
            )
            if idle and not self._divert.send_fail:
                self.hint.config(
                    text='Still 0 packets. Console must be on this PC hotspot. Close this window, reopen ZubLock, Lock ON again.'
                )
        if not _admin():
            parts.append('Need Administrator')
        self.status.config(text='\n'.join(parts))
        self.on_btn.config(bg=BTN if locked else ACCENT)
        self.off_btn.config(bg=ACCENT if locked else BTN)

    def _tick(self) -> None:
        self._refresh()
        self.after(1000, self._tick)

    def _quit(self) -> None:
        if self._divert is not None:
            self._divert.stop()
            self._divert = None
        self.destroy()


def main() -> int:
    _set_app_user_model_id()
    if sys.platform.startswith('win') and not _admin():
        if _relaunch_admin():
            return 0
        _set_app_user_model_id()
    try:
        App().mainloop()
    except tk.TclError as exc:
        print('Tk failed. Run Install-ZubLock.cmd so Python includes Tcl/Tk.', exc)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
