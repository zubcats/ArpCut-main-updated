# ZubLock

Keep a PlayStation game session on **this PC’s hotspot** when another console signs into the same PSN account.

This folder lives in the ZubCut repo so friends can grab a zip. It is **not** part of ZubCut (no Kill, no ZubCut installer).

## Install

1. Download [ZubLock.zip](https://github.com/zubcats/ArpCut-main-updated/releases/download/zublock-latest/ZubLock.zip)
2. Unzip
3. Run `Install-ZubLock.cmd`

That puts **ZubLock** on the desktop and downloads WinDivert plus Python (with Tk) if this PC does not already have them.

## Use

1. Turn on the Windows hotspot.
2. Put the PlayStation on that hotspot (`192.168.137.x`). Leave the other console on house Wi‑Fi.
3. Open **ZubLock** from the desktop and approve UAC.
4. **Lock ON** — keep the window open while you play.
5. **Lock OFF** when the other console should be able to take the session.

Lock only drops PSN session HTTPS on a few AWS ranges. Game UDP and CDN stay up.

Needs 64-bit Windows and Administrator for the lock itself. If install says Windows blocked WinDivert, allow it in Windows Security and run `Install-ZubLock.cmd` again.
