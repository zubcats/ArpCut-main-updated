# PyInstaller runs this when `gui.main` is analyzed (entry imports ElmoCut from there).
hiddenimports = [
    'gui.traffic',
    'ui.ui_traffic',
    'gui.paid_license_signin',
    'tools.license_offline',
    'tools.license_remote_signin',
]
