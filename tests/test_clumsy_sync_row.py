"""Tests for sync_clumsy_row (legacy row strip + duplicate IP dedupe)."""

from unittest.mock import patch

from tools.clumsy_inline import sync_clumsy_row, use_windivert_for_advanced_ics_shaping


class _FakeScanner:
    def __init__(self, devices):
        self.devices = devices


def test_sync_clumsy_row_strips_legacy_synthetic_flag():
    devices = [
        {'mac': 'aa:aa:aa:aa:aa:01', 'ip': '10.0.0.1', 'admin': True},
        {'mac': 'bb:bb:bb:bb:bb:02', 'ip': '192.168.137.5', 'admin': False, 'clumsy_inline': True},
    ]
    s = _FakeScanner(list(devices))
    with patch('tools.clumsy_inline.clumsy_mode_enabled', return_value=False):
        sync_clumsy_row(s)
    assert len(s.devices) == 1
    assert s.devices[0]['mac'] == 'aa:aa:aa:aa:aa:01'


def test_sync_clumsy_row_dedupes_same_inline_ip_keeps_first():
    target = '192.168.137.50'
    devices = [
        {'mac': '11:11:11:11:11:01', 'ip': target, 'admin': False},
        {'mac': '22:22:22:22:22:02', 'ip': target, 'admin': False},
        {'mac': '33:33:33:33:33:03', 'ip': '192.168.1.2', 'admin': False},
    ]
    s = _FakeScanner(list(devices))
    with (
        patch('tools.clumsy_inline.clumsy_mode_enabled', return_value=True),
        patch('tools.clumsy_inline.clumsy_runtime_ready', return_value=True),
        patch('tools.clumsy_inline.detect_inline_ip', return_value=target),
    ):
        sync_clumsy_row(s)
    assert [d['mac'] for d in s.devices] == ['11:11:11:11:11:01', '33:33:33:33:33:03']


def test_sync_clumsy_row_single_client_row_unchanged():
    target = '192.168.137.50'
    devices = [
        {'mac': '11:11:11:11:11:01', 'ip': target, 'admin': False},
        {'mac': 'aa:aa:aa:aa:aa:aa', 'ip': '10.0.0.1', 'admin': True},
    ]
    s = _FakeScanner(list(devices))
    with (
        patch('tools.clumsy_inline.clumsy_mode_enabled', return_value=True),
        patch('tools.clumsy_inline.clumsy_runtime_ready', return_value=True),
        patch('tools.clumsy_inline.detect_inline_ip', return_value=target),
    ):
        sync_clumsy_row(s)
    assert len(s.devices) == 2


def test_use_windivert_for_advanced_ics_shaping_matches_lag_switch_eligibility():
    s = _FakeScanner([])
    dev = {'mac': '11:11:11:11:11:01', 'ip': '192.168.137.50', 'admin': False}
    with patch(
        'tools.clumsy_inline.clumsy_ics_lag_can_use_windivert', return_value=True
    ) as lag_wd:
        assert use_windivert_for_advanced_ics_shaping(s, dev) is True
        lag_wd.assert_called_once_with(dev, s)
    with patch('tools.clumsy_inline.clumsy_ics_lag_can_use_windivert', return_value=False):
        assert use_windivert_for_advanced_ics_shaping(s, dev) is False


def test_use_windivert_for_advanced_ics_shaping_false_when_clumsy_off():
    s = _FakeScanner([])
    dev = {'mac': '11:11:11:11:11:01', 'ip': '192.168.137.50', 'admin': False}
    with patch('tools.clumsy_inline.clumsy_ics_lag_can_use_windivert', return_value=False):
        assert use_windivert_for_advanced_ics_shaping(s, dev) is False
