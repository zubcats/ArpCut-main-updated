"""PyInstaller hook: bundle PyNaCl and libsodium native extension for license verify."""

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all('nacl')
