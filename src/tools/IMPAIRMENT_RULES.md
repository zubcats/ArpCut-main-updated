# ICS / Clumsy impairment — do not repeat these mistakes

This file records failures seen across multiple fix commits. Check here before
changing `main.py`, `ics_windivert_shaper.py`, or `clumsy_inline.py`.

## Home LAN ARP

- **Wrong:** Unicast ARP *reply* (`op=2`) only — some stacks ignore unsolicited replies,
  so Kill logs ON but never cuts.
- **Wrong:** Dropping victim-targeted Wi‑Fi broadcast poison on this mesh
  (`pdst=victim` on `ff:ff:ff`) because of a guess that the operator PC
  lost internet. The ethernet PS5 never sees STA unicast; DURING captures
  only showed a cut while those copies existed. The operator PC staying
  online is not a reason to remove them.
- **Right:** Unicast request+reply to victim MAC and router MAC, plus
  Wi‑Fi victim-targeted broadcast copies so isolation still delivers the
  cut. Do not broadcast ``psrc=victim_ip`` (that GARP re-poisons the router).
- **Mesh Wi‑Fi PC + ethernet PS5 (Starlink router / mesh node):** ON and
  OFF are the same ARP stack. Instant OFF worked when both were on the
  same AP because unicast restore landed. On this split, only the flooded
  broadcast reaches the console. One short honest broadcast, then
  silence so the Starlink router can answer on ethernet. Do not stop the
  100% pass-through while leftover MITM may still be in use.

## Clumsy enable must not break a working hotspot

- **Wrong:** Start `RemoteAccess`, set `IPEnableRouter=1`, rewrite ICS firewall rules, or
  disable kernel forwarding on the Clumsy restart when SoftAP is already up.
  Hotspot and Sharing stay "on" but the PS5 loses internet.
- **Wrong:** Heal/ARP as `192.168.137.1` using the uplink Wi‑Fi MAC (Settings iface).
- **Right:** If Mobile Hotspot is already ready, only write Clumsy state. Bind heal/ARP
  to the SoftAP adapter. Skip startup `ensure_home_lan_mitm_forwarding_off` while
  Clumsy is on.

## Home LAN IP forwarding

- **Wrong:** `netsh interface ipv4 set global forwarding=…` — invalid; does nothing.
- **Wrong:** Re-enable kernel forwarding after startup clean / Killer idle — Windows then
  relays MITM'd frames and Kill becomes a **partial** cut while Lag still “works a bit”.
- **Wrong:** Synchronous PowerShell / netsh on the Kill click **before** poison — delay.
- **Right:** Instant path = poison + forwarder cut first; then
  `disable_ip_forwarding(priority_iface=…)` (registry sync + background netsh). Startup
  may use `blocking=True`. Clumsy/ICS turns forwarding on when that path needs it.

## Home LAN Kill OFF

- **Wrong:** Stop the Npcap forwarder (or leave hard-drop) while the
  victim/router still have poisoned ARP and kernel forwarding is off.
  Frames still arrive here and die. Analysis AFTER then false-passes on
  LAN ping + "forwarder cleared".
- **Right:** On OFF: flip the live forwarder to 100% pass
  (`pass_all_live`), send honest restore ARP (including the same
  victim-targeted broadcast poison used), and keep that pass-through
  until leftover MITM is unused: hold at least a few minutes (idle
  console has no WAN), and never drop a still-busy relay. A fixed
  short stop is the “came back then died again” hole. `_seal_hard_drop`
  must no-op when the MAC is not in `killed`. Idle reconcile must not
  kill a still-busy pass-through.
- **Wrong:** Finish a poison burst after unkill, or queue `block_ip`
  while the Npcap dropper is already live. Early Dupe/Kill OFF then
  looks restored and dies again when the trailing frames/firewall land.

## Home LAN Kill — instant cut first

- **Wrong:** Blocking probes, forwarding netsh, or “reinforce” work **before** the first
  poison burst / 0% cut — Kill feels slow.
- **Wrong:** Calling `kill()` again from ON reinforce timers — bumps `_op_seq` and cancels
  the ARP worker (MITM dies).
- **Right:** Hot path = `_poison_arp_now` → `_kill_arp_worker` → `_apply_traffic_cut_sync`
  → async `disable_ip_forwarding`. After arm only: `_reinforce_full_cut_async` /
  `reinforce_full_cut` (re-poison via `reassert_poison`, reseal hard-drop, retry forwarder,
  re-disable forwarding). Never put reinforce before the instant cut.

## One stack per path (from `ics_impairment_policy.py`)

| Device path | Use | Do not use |
|-------------|-----|------------|
| Hotspot / ethernet-console client (downstream subnet) | WinDivert gate | ARP MITM, `block_ip`, MITM forwarder, `stack_arp` |
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
