"""PyInstaller hook: bundle cryptography (Ed25519 license verify)."""

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = collect_all('cryptography')
datas += copy_metadata('cryptography')
