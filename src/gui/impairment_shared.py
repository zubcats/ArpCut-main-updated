"""Shared helpers/constants for impairment mixins (extracted from MainWindow module)."""
from __future__ import annotations

import threading

from PyQt5.QtWidgets import QAbstractSpinBox, QLineEdit, QPlainTextEdit, QTextEdit

from tools.crash_feedback import safe_daemon_target
from tools.pfctl import block_ip, unblock_ip

import constants as _zcut_constants

ADMIN_DEVICE_TABLE_ROW_BG = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_BG', '#5D706E')
ADMIN_DEVICE_TABLE_ROW_FG = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_FG', '#eef1f0')
UI_LOG_VICTIM_BLOCK_FG = getattr(_zcut_constants, 'UI_LOG_VICTIM_BLOCK_FG', '#32716D')
UI_LOG_RESTORE_FG = getattr(_zcut_constants, 'UI_LOG_RESTORE_FG', ADMIN_DEVICE_TABLE_ROW_BG)

# Killed device row: dark red matched to experimental admin row darkness.
_DEVICE_ROW_KILL_BG = '#3d1a1a'
_DEVICE_ROW_KILL_FG = '#e8d0d0'
_DEVICE_ROW_KILL_HOVER_BG = '#502626'
_DEVICE_ROW_KILL_HOVER_FG = '#f5e6e6'
_DEVICE_ROW_KILL_SELECTED_BG = '#4a2828'
_DEVICE_ROW_KILL_SELECTED_FG = '#f5e8e8'
_DEVICE_ROW_KILL_SEL_HOVER_BG = '#5c3232'
_DEVICE_ROW_KILL_SEL_HOVER_FG = '#fff8f8'


def format_countdown_ms(left_ms):
    """Human-readable countdown (matches Dupe / Lag Switch inline labels)."""
    left_ms = max(0, int(left_ms))
    sec = left_ms / 1000.0
    if sec >= 60:
        whole = int(sec)
        m, s = divmod(whole, 60)
        return f'Time left: {m}:{s:02d}'
    return f'Time left: {sec:.2f}s'


def _dupe_net_run_unblock(ip: str) -> None:
    try:
        unblock_ip(ip)
    except Exception:
        pass


def _dupe_net_run_block(iface: str, ip: str, direction: str):
    try:
        block_ip(iface, ip, direction)
        return None
    except Exception as exc:
        return exc


def _bg_unblock_ip(ip: str | None) -> None:
    """Fire-and-forget unblock_ip on a background thread."""
    if not ip:
        return
    ip_s = str(ip).strip()
    if not ip_s:
        return
    try:
        threading.Thread(
            target=safe_daemon_target(_dupe_net_run_unblock, ip_s),
            name='zubcut-unblockip-bg',
            daemon=True,
        ).start()
    except Exception:
        pass


def _bg_block_ip(iface: str | None, ip: str | None, direction: str = 'both') -> None:
    """Fire-and-forget block_ip on a background thread (see _bg_unblock_ip)."""
    if not ip:
        return
    ip_s = str(ip).strip()
    if not ip_s:
        return
    iface_s = str(iface or 'en0').strip() or 'en0'
    direction_s = str(direction or 'both').strip() or 'both'
    try:
        threading.Thread(
            target=safe_daemon_target(_dupe_net_run_block, iface_s, ip_s, direction_s),
            name='zubcut-blockip-bg',
            daemon=True,
        ).start()
    except Exception:
        pass


def _focus_widget_absorbs_letter_key(widget):
    """Avoid stealing letter shortcuts only while typing in text-entry fields."""
    if widget is None:
        return False
    if isinstance(widget, QLineEdit):
        try:
            if isinstance(widget.parent(), QAbstractSpinBox):
                return False
        except Exception:
            pass
        return True
    return isinstance(widget, (QTextEdit, QPlainTextEdit))
