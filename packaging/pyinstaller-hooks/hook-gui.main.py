# PyInstaller runs this when `gui.main` is analyzed (entry imports ZubCutApp from there).
hiddenimports = [
    'gui.traffic',
    'ui.ui_traffic',
    'gui.license_signin',
    'tools.license_offline',
    'tools.license_remote_signin',
]
