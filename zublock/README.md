# ZubLock

Keep a PlayStation game session on **this PC's hotspot** when another console signs into the same PSN account.

This folder lives in the ZubCut repo so friends can grab a zip. It is **not** part of ZubCut (no Kill, no ZubCut installer).

## Install

1. Download [ZubLock.zip](https://github.com/zubcats/ArpCut-main-updated/releases/download/zublock-latest/ZubLock.zip)
2. Unzip - you should see **ZubLock-Setup.exe**
3. Run **ZubLock-Setup.exe**

That puts **ZubLock** on the desktop and downloads WinDivert plus Python (with Tk) if this PC does not already have them.

If you still have the older zip with lots of files in it, double-click **Install-ZubLock** (or **ZubLock-Setup**) and ignore the rest.

## Use

1. Turn on the Windows hotspot.
2. Put the PlayStation on that hotspot (`192.168.137.x`). Leave the other console on house Wi-Fi.
3. Open **ZubLock** from the desktop and approve UAC.
4. Confirm the IP is `192.168.137.x` (this PC hotspot). House Wi-Fi IPs will not lock.
5. **Lock ON** - keep the window open while you play. **Lock OFF** or close the window to release the lock.

Lock only drops PSN session HTTPS on a few AWS ranges. Game UDP and CDN stay up. Close the window before you quit — that puts every packet back.

Needs 64-bit Windows and Administrator for the lock itself. If install says Windows blocked WinDivert, allow it in Windows Security and run the installer again.
