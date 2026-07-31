# ICS / Clumsy impairment — do not repeat these mistakes

This file records failures seen across multiple fix commits. Check here before
changing `main.py`, `ics_windivert_shaper.py`, or `clumsy_inline.py`.

## Home LAN ARP

- **Wrong:** Broadcast gateway impersonation (`Ether(dst=ff:ff:ff…)` with `psrc=router`)
  on Kill/Lag — every listening client learns “PC = gateway” and can lose internet.
- **Wrong:** Unicast ARP *reply* (`op=2`) only — some stacks ignore unsolicited replies,
  so Kill logs ON but never cuts.
- **Right:** Unicast poison only (`_poison_frames` → victim MAC + router MAC), with both
  ARP *request* (`op=1`) and *reply* (`op=2`) to each.

## Home LAN IP forwarding

- **Wrong:** `netsh interface ipv4 set global forwarding=…` — invalid; does nothing.
- **Wrong:** Re-enable kernel forwarding after startup clean / Killer idle — Windows then
  relays MITM'd frames and Kill becomes a **partial** cut while Lag still “works a bit”.
- **Right:** `Set-NetIPInterface -Forwarding Disabled` (plus `IPEnableRouter=0`) while
  home-LAN MITM is armed or idle. Clumsy/ICS turns forwarding on when that path needs it.

## One stack per path (from `ics_impairment_policy.py`)

| Device path | Use | Do not use |
|-------------|-----|------------|
| Hotspot / ethernet-console client (downstream subnet) | WinDivert gate | ARP MITM, `block_ip`, MITM forwarder |
| Home LAN (regular) | ARP MITM + `block_ip` + forwarder | WinDivert for that victim |

Classify with `classify_device_impairment()` — do not duplicate checks with
`clumsy_ics_use_firewall_only` in new code.

## WinDivert capture (post-NAT)

- **Wrong (reverted in 6108bd2 / fixed in e6074d2, 20f8b6f):** Open `ip.SrcAddr == 137.x` or
  subnet-only filter first → sees zero game traffic → “nothing works”.
- **Right:** `ifIdx` on hotspot NIC first, then forward/broad, **victim IP filter last**.

Kill log should show `ifidx` and `ifIdx=N` (not `victim` + `ifIdx=0`).

## Run loop

- **Wrong:** Bernoulli `random` per packet for % cut → feels like full kill.
- **Right:** Byte budget (`_passes_byte_ratio`), same as MITM forwarder.
- **Wrong:** `continue` (drop) on duplicate sig within 50ms → amplifies loss.
- **Right:** `_send_immediate` pass-through on duplicate capture.
- **Wrong:** Pause mode holds packets in heap then replay → burst / stuck lag.
- **Right:** `IMPAIR_PAUSE` drops in recv loop (`continue`), no heap hold for kill/lag block.
- **Wrong:** Reinject impostor packets → reinject loop until TTL 0.
- **Right:** Drop packets that arrive with impostor flag set.

## Gate lifecycle

- **Wrong:** `_stop_ics_lag_gate()` on every Kill OFF while Lag / % Cut / Advanced still active.
- **Right:** `_ics_teardown_gate_if_idle(mac)` — one shared gate for all WinDivert features.
- **Wrong:** Restart gate on every toggle → race on filter selection.
- **Right:** Keep gate running; toggle `pause_connection` / `apply_percent_cut` / shaping only.

## Kill bookkeeping (hotspot)

- **Wrong:** Mirror WinDivert Kill into `killer.killed` → `release_ics_victim_block` / heal on OFF.
- **Right:** `_ics_kill_profile_macs` + `_killed_profile_on`; UI via `_kill_ui_shows_on`, not
  `mac in killer.killed` alone.
- **Wrong:** `_ics_quiesce` + `release_ics` + `unblock_ip` on every WinDivert start.
- **Right:** `quiesce_legacy_stack()` once; no `unblock_ip` when `use_block_ip` is false.

## Wiring (no new ``clumsy_ics_use_firewall_only`` in GUI)

- **Policy:** ``ics_impairment_policy.classify_device_impairment`` → ``plan.use_windivert`` /
  ``plan.is_ics_downstream``.
- **Victim row:** ``device_row_for_impairment`` / ``MainWindow._victim_row`` — not scattered
  ``clumsy_ics_resolve_victim_ip`` calls.
- **Remember kill:** ``should_restore_remembered_kill`` — LAN ARP only; ICS uses
  ``_apply_victim_block`` + ``killed_devices`` / ``_ics_kill_profile_macs``.
- **Scan:** ``device_table.extra_scan_hits_from_ics_arp`` merged in ``devices_appender``.

## Device table (``networking/device_table.py``)

- **Clumsy hotspot / ethernet-console:** one row per MAC; display IP prefers ICS (`137.x`)
  from scan + ARP refresh (`sync_device_table`).
- **Home LAN (Clumsy off or regular path):** one row per `MAC|subnet` profile.
- **Wrong:** Using the IP column alone for impairment without `clumsy_ics_resolve_victim_ip`.
- **Right:** Refresh table before paint (`sync_clumsy_row`); impairment via
  `classify_device_impairment` + WinDivert on downstream path.

## Clumsy reference

Real Clumsy: one `WinDivertOpen`, one filter, module flags — no ARP, no gate stop per button.
ZubCut adds ICS setup (`clumsy_ics.py`) and device table; impairment should still behave
like Clumsy on the downstream path.
