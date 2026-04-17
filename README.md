# ZubCut

Cross-platform network control tool for ARP spoofing. Works on Windows and macOS.

**Author:** ZubOnTop

<img width="879" height="625" alt="Bildschirmfoto 2025-12-11 um 16 31 27" src="https://github.com/user-attachments/assets/5bedfb0d-ee48-42e5-bbb5-1353c71a4ab9" />


---

## Download

Pre-built binaries are available from the **Releases** tab on this repository.

**CI builds:** Push the repo to GitHub, open the **Actions** tab, run workflow **Build Release** (or **Build Windows installer only**). Pushes to **`main`** build the regular ZubCut installer; pushes to **`experimental`** build the tester installer. Manual runs can set `release_channel` (`stable` / `experimental` / `auto` — `auto` follows branch rules).

From artifacts:
- Regular (main) installer: `ZubCut-Windows-Installer`
- Experimental installer: `ZubCut-Windows-Installer-Experimental`

Step-by-step: **`HOW-TO-DOWNLOAD-INSTALLER.txt`** in the repo root.

| Platform | File | Notes |
|----------|------|-------|
| Windows | `ZubCut.exe` | Requires [Npcap](https://npcap.com/) (installer can bundle `npcap-1.87.exe`) |
| macOS | `ZubCut-macOS.zip` | Unzip and run |
| Linux | `ZubCut` | Experimental |

**Requirements:** Administrator/root privileges required.

If the pre-built binaries don't work on your machine, build from source (see below).

---

## Features

**Scanning**
- ARP Scan - Fast device discovery
- Ping Scan - Thorough scan, finds all devices

**Device Control**
- Kill toggle (bottom bar) — block or restore the selected device
- Kill All / Unkill All — mass control (tray menu includes Unkill All)

**Advanced**
- Lag Switch — Intermittent blocking with configurable timing and direction (incoming/outgoing/both)
- Dupe — One-shot lag for a fixed duration (ms), then full stop (no repeat)
- Traffic Monitor — Real-time bandwidth per device

**Other**
- Dark theme
- System tray
- Device nicknames
- Remember killed devices
- In-app manual updater with channel-aware installs (regular vs experimental)

---

## Installation from Source

### Windows

1. Install Python 3.8+ from [python.org](https://python.org/downloads) - check "Add to PATH"
2. Install [Npcap 1.87](https://npcap.com/dist/npcap-1.87.exe) - check "WinPcap API-compatible Mode"
3. Clone and run:

```cmd
git clone <your-repository-url>
cd <repo-folder>
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python src\zubcut.py
```

Run as Administrator.

### macOS

1. Install Python:
```bash
brew install python@3.11
```

2. Clone and run:
```bash
git clone <your-repository-url>
cd <repo-folder>
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
sudo python3 src/zubcut.py
```

---

## Building

Install PyInstaller, then run the build script:

```bash
pip install pyinstaller pillow
python build.py
```

That's it. Works on Windows, macOS, and Linux.

Output:
- Windows: `dist/ZubCut.exe`
- macOS: `dist/ZubCut.app`
- Linux: `dist/ZubCut`

**Windows installer (optional):** Install [Inno Setup 6](https://jrsoftware.org/isdl.php), then run `installer\Build-Installer.bat`. The setup wizard installs under `Program Files\ZubCut` and stores settings under `%APPDATA%\ZubCut`. See `installer/HOWTO-INSTALLER.txt`.

If `installer\npcap-1.87.exe` is present while building setup, the installer will run Npcap silently only when Npcap is missing on the target machine.

---

## Updates

- The Settings button **Install Latest Build (...)** is a manual updater.
- Regular installs pull regular builds; experimental installs pull experimental builds.
- There is no background auto-update check; updates run only when you trigger them.

---

## Button Reference

| Button | Action |
|--------|--------|
| ARP Scan | Fast network scan |
| Ping Scan | Thorough scan |
| Kill All | Block all devices |
| Unkill All | Restore all devices |
| Lag Switch (bottom) | Intermittent blocking (cycles) |
| Kill toggle (bottom) | Block or restore selected device |
| Dupe (bottom) | One-shot timed lag, then stop |

---

## VirusTotal

Network tools often trigger antivirus false positives. The code is open source and auditable.

<!-- Add VirusTotal link after uploading release binary -->
[Windows](https://www.virustotal.com/gui/file/0d7db182f64251f0c22952192894b66b96cd2a87f9a143767bd07bbdcad4eb14)
[Macos](https://www.virustotal.com/gui/file/948666b8fad8db4d3870123c794bad28453de5c3265d2cf0be94a1d79e086d46)
[Linux](https://www.virustotal.com/gui/file/15e91b6b6099b6271f74577c1f44070d2983121199d280d28250bec130be84c5)

---

## Disclaimer

This software is for educational and authorized network administration purposes only.

Only use on networks you own or have explicit permission to test. Unauthorized use may violate computer crime laws.

---

## Credits

- ZubOnTop

---

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE)
