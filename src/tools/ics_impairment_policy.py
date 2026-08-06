"""
Per-device impairment routing for Clumsy / ICS vs normal LAN.

When a row is selected (or a flow runs), classify the victim and choose exactly one
stack: WinDivert on the PC downstream subnet (hotspot or ethernet-to-console), or
legacy ARP MITM + block_ip + MITM forwarder on the home LAN.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from tools.clumsy_ics import read_clumsy_topology

if TYPE_CHECKING:
    from networking.scanner import Scanner

PATH_REGULAR = 'regular'
PATH_HOTSPOT = 'hotspot_client'
PATH_ETHERNET = 'ethernet_console'


@dataclass(frozen=True)
class DeviceImpairmentPlan:
    """How Kill / Lag / Dupe / Percent Cut / Advanced Lag should affect this device."""

    path: str
    table_ip: str
    resolved_ip: str
    downstream_prefix: str
    clumsy_topology: str
    use_windivert: bool
    use_arp_mitm: bool
    use_block_ip: bool
    use_mitm_forwarder: bool
    windivert_ready: bool

    @property
    def is_ics_downstream(self) -> bool:
        return self.path in (PATH_HOTSPOT, PATH_ETHERNET)


def _regular_plan(table_ip: str, resolved_ip: str) -> DeviceImpairmentPlan:
    return DeviceImpairmentPlan(
        path=PATH_REGULAR,
        table_ip=table_ip,
        resolved_ip=resolved_ip or table_ip,
        downstream_prefix='',
        clumsy_topology='',
        use_windivert=False,
        use_arp_mitm=True,
        use_block_ip=True,
        use_mitm_forwarder=True,
        windivert_ready=False,
    )


def classify_device_impairment(
    device,
    scanner: Optional['Scanner'] = None,
) -> DeviceImpairmentPlan:
    """
    Decide which impairment stack applies to this device right now.

    - hotspot_client: console on PC Mobile Hotspot subnet (e.g. 192.168.137.x)
    - ethernet_console: console on spare Ethernet → PC (downstream ICS subnet from state)
    - regular: home LAN / router path — ARP MITM + firewall + forwarder
    """
    from tools.clumsy_inline import (
        clumsy_ics_arp_ip_for_mac,
        clumsy_ics_downstream_prefix,
        clumsy_ics_resolve_victim_ip,
        clumsy_mode_enabled,
        clumsy_runtime_ready,
        victim_on_clumsy_ics_subnet,
        windivert_bundle_complete,
    )

    table_ip = ''
    if isinstance(device, dict):
        table_ip = str(device.get('ip') or '').strip()

    if not isinstance(device, dict):
        return _regular_plan(table_ip, table_ip)

    import sys

    if not clumsy_mode_enabled() or not sys.platform.startswith('win'):
        return _regular_plan(table_ip, table_ip)

    from tools.clumsy_inline import clumsy_hotspot_session_active

    resolved = clumsy_ics_resolve_victim_ip(device, scanner) or table_ip
    prefix = clumsy_ics_downstream_prefix()
    topo = read_clumsy_topology()
    # Mis-detected spare Ethernet while ICS gateway is still 192.168.137.1 (mobile hotspot).
    if topo == 'ethernet':
        try:
            from tools.clumsy_ics import read_clumsy_ics_state

            gw = str(read_clumsy_ics_state().get('downstream_ipv4') or '').strip()
            # SoftAP ICS (137.x) or Hosted Network DHCP (173.x).
            if gw.startswith('192.168.137.') or gw.startswith('192.168.173.'):
                topo = 'hotspot'
        except Exception:
            pass
    on_downstream = victim_on_clumsy_ics_subnet(resolved)
    # Hotspot session: console may be on PC hotspot while the scan table still shows home LAN IP.
    # Only treat as downstream when the IP is on the ICS subnet or ARP finds an ICS address
    # for this MAC — not when the PS5 has moved to router Wi‑Fi (Ethernet/Wi‑Fi handoff).
    if not on_downstream and clumsy_hotspot_session_active() and not device.get('admin'):
        arp_ip = clumsy_ics_arp_ip_for_mac(scanner, str(device.get('mac') or ''))
        if arp_ip and victim_on_clumsy_ics_subnet(arp_ip):
            on_downstream = True
            resolved = arp_ip
    wd_ready = bool(clumsy_runtime_ready() and windivert_bundle_complete())

    if on_downstream:
        path = PATH_ETHERNET if topo == 'ethernet' else PATH_HOTSPOT
        return DeviceImpairmentPlan(
            path=path,
            table_ip=table_ip,
            resolved_ip=resolved,
            downstream_prefix=prefix,
            clumsy_topology=topo,
            use_windivert=wd_ready,
            use_arp_mitm=False,
            use_block_ip=False,
            use_mitm_forwarder=False,
            windivert_ready=wd_ready,
        )

    return _regular_plan(table_ip, resolved)


def device_row_for_impairment(
    device,
    scanner: Optional['Scanner'] = None,
    plan: Optional[DeviceImpairmentPlan] = None,
) -> dict:
    """
    Device dict with ``ip`` set for impairment (resolved downstream or LAN).

    Use everywhere instead of re-calling ``clumsy_ics_resolve_victim_ip`` in the GUI.
    """
    if not isinstance(device, dict):
        return device if isinstance(device, dict) else {}
    plan = plan or classify_device_impairment(device, scanner)
    row = dict(device)
    ip = (plan.resolved_ip or str(row.get('ip') or '')).strip()
    if ip:
        row['ip'] = ip
    return row


def should_restore_remembered_kill(
    device,
    scanner: Optional['Scanner'] = None,
) -> bool:
    """Remember-kill on rescan: ARP path only — never ``killer.kill`` for WinDivert victims."""
    plan = classify_device_impairment(device, scanner)
    return bool(plan.use_arp_mitm)


def use_windivert_impairment(device, scanner: Optional['Scanner'] = None) -> bool:
    """True when this device should use the shared ICS WinDivert gate (not ARP/MITM)."""
    return classify_device_impairment(device, scanner).use_windivert


def use_legacy_mitm_impairment(device, scanner: Optional['Scanner'] = None) -> bool:
    """True when Kill/Lag/etc. should use ARP MITM + block_ip / forwarder."""
    plan = classify_device_impairment(device, scanner)
    return plan.use_arp_mitm or plan.use_mitm_forwarder


def impairment_path_label(plan: DeviceImpairmentPlan) -> str:
    if plan.path == PATH_HOTSPOT:
        return 'PC Mobile Hotspot'
    if plan.path == PATH_ETHERNET:
        return 'Ethernet to PC'
    return 'Home LAN'


def impairment_stack_label(plan: DeviceImpairmentPlan) -> str:
    if plan.use_windivert:
        return 'WinDivert'
    if plan.use_mitm_forwarder:
        return 'ARP MITM + forwarder'
    return 'ARP MITM'


def impairment_status_line(plan: DeviceImpairmentPlan) -> str:
    """One-line hint after selecting a device (Clumsy mode)."""
    ip = plan.resolved_ip or plan.table_ip or '?'
    path = impairment_path_label(plan)
    stack = impairment_stack_label(plan)
    if plan.path == PATH_REGULAR:
        from tools.clumsy_inline import clumsy_mode_enabled

        if clumsy_mode_enabled():
            return (
                f'Selected {ip}: {path} — Kill/Lag/Dupe/Cut/Advanced use {stack} '
                f'(not on hotspot/console subnet {plan.downstream_prefix or "137."}x yet)'
            )
        return f'Selected {ip}: {path} — Kill/Lag/Dupe/Cut/Advanced use {stack}'
    if plan.use_windivert:
        return (
            f'Selected {ip}: {path} — Kill/Lag/Dupe/Cut/Advanced use {stack} '
            '(ARP/firewall/MITM disabled for this target)'
        )
    return (
        f'Selected {ip}: {path} — needs WinDivert (run as Administrator / reinstall Clumsy bundle); '
        'ARP MITM is not used on this path'
    )


def quiesce_legacy_stack(scanner: 'Scanner', killer, device) -> None:
    """
    Stop ARP MITM / firewall / forwarder paths that conflict with WinDivert on ICS.

    Safe to call when starting any WinDivert impairment on a downstream client.
    """
    from tools.clumsy_inline import release_ics_victim_block
    from tools.pfctl import unblock_ip

    plan = classify_device_impairment(device, scanner)
    if not plan.use_windivert:
        return
    if not isinstance(device, dict):
        return
    mac = str(device.get('mac') or '').strip()
    if not mac:
        return
    victim = dict(device)
    if plan.resolved_ip:
        victim['ip'] = plan.resolved_ip
    try:
        killer.disable_percent_cut(mac)
    except Exception:
        pass
    if mac in killer.killed:
        try:
            if plan.is_ics_downstream:
                release_ics_victim_block(scanner, killer, victim)
            else:
                killer.unkill(victim)
        except Exception:
            pass
    if plan.use_block_ip:
        ip = plan.resolved_ip or str(victim.get('ip') or '').strip()
        if ip:
            try:
                unblock_ip(ip)
            except Exception:
                pass
