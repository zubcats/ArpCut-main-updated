WinDivert (64-bit) driver files for the Clumsy mode optional installer task.

1. Download the official WinDivert release (e.g. WinDivert-2.2.2-A.zip) from the WinDivert project.
2. From the archive, copy the x64 folder contents into this directory so that WinDivert.inf and
   WinDivert64.sys sit next to each other (same layout as the upstream x64 package).
3. Rebuild the Inno setup. If this folder is empty, setup skips WinDivert install (same pattern as
   a missing bundled Npcap exe).

The post-install step runs: pnputil /add-driver "<app>\windivert\WinDivert.inf" /install
