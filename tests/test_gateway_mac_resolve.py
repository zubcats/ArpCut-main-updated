"""Unit tests for gateway MAC parsing helpers."""

from constants import GLOBAL_MAC
from tools.utils import (
    _parse_windows_arp_table_for_ip,
    get_gateway_mac,
    is_usable_ether_mac,
)


def test_is_usable_ether_mac_rejects_broadcast_and_zero():
    assert not is_usable_ether_mac(GLOBAL_MAC)
    assert not is_usable_ether_mac('00:00:00:00:00:00')
    assert not is_usable_ether_mac('')
    assert is_usable_ether_mac('AA:BB:CC:DD:EE:FF')


def test_parse_windows_arp_table_for_ip():
    text = """
Interface: 192.168.1.50 --- 0x8
  Internet Address      Physical Address      Type
  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic
  192.168.1.99          11-22-33-44-55-66     dynamic
"""
    assert _parse_windows_arp_table_for_ip(text, '192.168.1.1') == 'AA:BB:CC:DD:EE:FF'
    assert _parse_windows_arp_table_for_ip(text, '10.0.0.1') == GLOBAL_MAC


def test_get_gateway_mac_empty_router_returns_broadcast():
    assert get_gateway_mac('192.168.1.50', '') == GLOBAL_MAC
    assert get_gateway_mac('192.168.1.50', '0.0.0.0') == GLOBAL_MAC
