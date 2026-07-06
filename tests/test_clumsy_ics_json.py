"""Tests for ICS helper JSON parsing (regression: success JSON must not be misread as failure)."""

from tools.clumsy_ics import _parse_marker_json


def test_parse_marker_single_line():
    text = 'stderr noise\nZUBCUT_JSON:{"ok": true, "message": "ICS sharing enabled."}\n'
    data = _parse_marker_json(text)
    assert data.get('ok') is True
    assert 'ICS' in (data.get('message') or '')


def test_parse_marker_two_line_powershell_quirk():
    """PowerShell 5.1 may emit the marker and JSON on separate lines."""
    text = 'ZUBCUT_JSON:\n{"ok": true, "message": "ICS sharing enabled."}\n'
    data = _parse_marker_json(text)
    assert data.get('ok') is True


def test_parse_marker_last_wins():
    text = 'ZUBCUT_JSON:{"ok": false}\nmore\nZUBCUT_JSON:{"ok": true}\n'
    data = _parse_marker_json(text)
    assert data.get('ok') is True


def test_parse_marker_none_safe():
    assert _parse_marker_json(None) == {}


def test_parse_marker_bom_ignored():
    text = '\ufeffZUBCUT_JSON:{"ok": true}\n'
    data = _parse_marker_json(text)
    assert data.get('ok') is True
