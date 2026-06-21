# ZubCut product architecture

**ZubCut** is a Windows desktop network control app for game-console testing over **PC Mobile Hotspot** and home LAN.

**Author / product:** ZubOnTop  
**Supported platform:** Windows 10/11, elevated (Administrator)

---

## What you use it for

| Goal | How |
|------|-----|
| PS5/console on PC hotspot | Clumsy mode → ICS setup (`clumsy_ics.py`) → scan → Kill/Lag/Dupe/Cut/Advanced |
| Console on home router LAN | Clumsy off → ARP MITM + firewall (`killer.py`, `pfctl.py`) |
| Ethernet console → PC | Clumsy topology `ethernet` → WinDivert path as hotspot |
| Licensed distribution | `license_offline` + Cloudflare sign-in worker |

---

## Core modules

| Module | Responsibility |
|--------|----------------|
| `networking/device_table.py` | Device list: MAC-centric on hotspot, ICS ARP merge on scan |
| `tools/ics_impairment_policy.py` | **One stack per victim:** WinDivert vs ARP MITM |
| `tools/ics_windivert_shaper.py` | Packet gate (Kill/Lag/Dupe/Cut/Advanced on ICS) |
| `tools/clumsy_inline.py` | ICS ARP, topology, ifIdx, heal, victim IP resolve |
| `tools/clumsy_ics.py` | Hotspot/ICS PowerShell setup |
| `networking/killer.py` | **LAN only:** ARP spoof + MITM forwarder |
| `networking/scanner.py` | Discovery (ARP/ping + ICS ARP enrichment) |
| `gui/main.py` (`ZubCutApp`) | UI, `_apply_victim_block` / `_clear_victim_block` |
| `tools/IMPAIRMENT_RULES.md` | Regression guardrails |

---

## Impairment routing

```
classify_device_impairment(device) → plan
  plan.use_windivert     → IcsWinDivertLagGate
  plan.use_arp_mitm      → Killer + block_ip
```

Use `_impairment_plan_for`, `_victim_row`, `device_row_for_impairment` — not ad-hoc subnet checks in new code.

---

## User-visible features

- Scan table, Kill, Lag, Dupe, Percent Cut, Advanced Lag  
- Clumsy mode + hotspot vs ethernet topology  
- Settings, traffic monitor, nicknames, remember kill (LAN ARP MACs)  
- Updater (stable / experimental), optional license sign-in  
