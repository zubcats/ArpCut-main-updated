# ZubCut

**ZubCut** is a Windows app for network testing with game consoles and other LAN devices. Scan your network, block or shape traffic per device, and use **PC Mobile Hotspot** mode (Clumsy / ICS) so a PS5 or Xbox on your PC’s hotspot gets real packet-level Kill, Lag Switch, Dupe, Percent Cut, and Advanced Lag—without fighting the wrong network path.

**By [ZubOnTop](https://linktr.ee/zubcastle)** · Windows 10/11 (64-bit) · **Run as Administrator**

<!-- Replace screenshot: commit a new image under docs/ or GitHub user-attachments and update the src URL below -->
<p align="center">
  <img width="880" alt="ZubCut main window" src="https://github.com/user-attachments/assets/5bedfb0d-ee48-42e5-bbb5-1353c71a4ab9" />
</p>

---

## Download

Get the latest installer from **[Releases](https://github.com/zubcats/ZubCut/releases)** (stable and experimental channels).

| Build | Installer | Branch |
|--------|-----------|--------|
| **Stable** | `ZubCut-Setup.exe` (`stable-latest`) | `main` |
| **Experimental** | `ZubCut-Setup-experimental.exe` (`experimental-latest`) | `experimental` |

**Before you run**

- Windows 10 or 11, 64-bit  
- [Npcap](https://npcap.com/) (WinPcap-compatible mode; the installer can bundle Npcap if missing)  
- **Administrator** (required for ARP, firewall, and WinDivert)  
- For **hotspot / Clumsy mode**: enable Clumsy in Settings and install the bundled WinDivert files with the app  

Step-by-step download: see **`HOW-TO-DOWNLOAD-INSTALLER.txt`** in the repo root.

Maintainers: CI workflow **Build Release** / **Build Windows installer only** publishes artifacts. Optional GitHub Actions variable **`UPDATE_DOWNLOAD_URL_MAIN`** overrides the stable installer URL in builds.

---

## What ZubCut does

### Scan

- **ARP Scan** — fast discovery on your LAN  
- **Ping Scan** — slower sweep when ARP misses devices  
- Device table: IP, MAC, vendor, type, nicknames; **Me** and **Router** rows always shown  

### Control (selected device)

| Feature | Description |
|---------|-------------|
| **Kill** | Full block or restore for one device |
| **Kill All / Unkill All** | Mass block or restore (tray menu too) |
| **Lag Switch** | Timed block / allow cycles (direction: in, out, or both) |
| **Dupe** | One timed burst, then full stop |
| **Percent Cut** | Partial packet loss (byte budget on hotspot path) |
| **Advanced Lag** | Delay, jitter, cap, loss (WinDivert on hotspot; MITM forwarder on home LAN) |

### Hotspot / Clumsy mode

For **PS5 → PC Mobile Hotspot** (PC on Ethernet or Wi‑Fi upstream):

1. Turn on **Clumsy mode** in Settings and pick topology (hotspot or Ethernet-to-PC).  
2. Let ZubCut apply ICS / hotspot setup.  
3. Connect the console to the PC hotspot SSID.  
4. **Rescan** — the table should show the console on the hotspot subnet (e.g. `192.168.137.x`).  
5. Use Kill / Lag / Dupe / Cut / Advanced — traffic is handled with **WinDivert** on the hotspot NIC (same idea as the Clumsy lag tool), not home-router ARP spoofing.

On a normal **home LAN** (no hotspot), ZubCut uses **ARP MITM** and Windows firewall rules for the same buttons.

### Other

- Dark UI, system tray, per-subnet nicknames  
- Traffic monitor (bandwidth per device)  
- In-app updater (stable vs experimental channel)  
- Optional account sign-in on licensed builds (Settings / Cloudflare worker)  

Licensed distribution uses the separate **ZubCut Control Panel** admin app for accounts, cloud sync, and crash reports. Build from `src/zubcut_control_panel.py` or install from the `control-panel-latest` release.

Architecture for contributors: [`docs/ZUBCUT_PRODUCT.md`](docs/ZUBCUT_PRODUCT.md)

---

## Install from source (Windows)

Download the source zip from **Releases**, or clone this repository from GitHub, then:

```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python src\zubcut.py
```

Run the terminal **as Administrator**.

---

## Build installer (Windows)

```cmd
pip install pyinstaller pillow
python build.py
```

Optional setup wizard: install [Inno Setup 6](https://jrsoftware.org/isdl.php), then `installer\Build-Installer.bat`.  
Output: `dist\ZubCut.exe` and `installer\output\ZubCut-Setup.exe` (names may vary by channel).

Settings are stored under `%APPDATA%\ZubCut\zubcut.json`.

---

## Updates

Use **Settings → Install Latest Build** to download and run the matching channel installer. There is no silent background update; you choose when to update.

---

## Security software

ARP and packet tools often trigger antivirus **false positives**. You can verify release binaries on VirusTotal after each publish if you maintain public builds.

---

## Disclaimer

For **education and authorized testing on networks you own or have permission to operate on** only. Misuse may violate local computer crime laws. You are responsible for how you use ZubCut.

---

## Community

- [Discord](https://discord.gg/zub)
- [Linktree](https://linktr.ee/zubcastle)

**© ZubOnTop. All rights reserved.**
