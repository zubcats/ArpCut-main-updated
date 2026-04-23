# CI copy of src/constants.py (GitHub web UI often breaks indentation on the real file).
# Workflows copy this to src/constants.py before building. Edit the real src/constants.py first, then mirror changes here.
from os import path, environ
import sys

APP_BUNDLE_NAME = 'ZubCut'
APP_EXE_NAME = 'ZubCut.exe'
APP_DISPLAY_NAME = 'ZubCut'
AUTOSTART_REG_VALUE = 'ZubCut'
APP_USER_DATA_DIR = 'ZubCut'
# Update channel / feed settings (in-app updater + Settings button labels).
# Branch convention:  main  -> regular releases (UPDATE_CHANNEL 'stable' in code = production URL)
#                     experimental -> tester builds (UPDATE_CHANNEL 'experimental')
# CI overwrites UPDATE_CHANNEL and APP_BUILD_TIME_ISO per branch; match your branch when developing.
UPDATE_CHANNEL = 'experimental'
# Direct download URL for the latest installer package per channel (.exe).
UPDATE_DOWNLOAD_URL_STABLE = 'https://github.com/zubcats/ArpCut-main-updated/releases/download/stable-latest/ZubCut-Setup.exe'
UPDATE_DOWNLOAD_URL_EXPERIMENTAL = 'https://github.com/zubcats/ArpCut-main-updated/releases/download/experimental-latest/ZubCut-Setup-experimental.exe'
# UTC ISO timestamp when this binary was built (CI overwrites). Used to detect newer installers online.
APP_BUILD_TIME_ISO = ''

# Cross-platform settings paths
if sys.platform.startswith('win'):
    OLD_DOCUMENTS_PATH = path.join(environ.get('USERPROFILE', ''), 'Documents', 'elmocut')
    DOCUMENTS_PATH = path.join(environ.get('APPDATA', ''), APP_USER_DATA_DIR)
else:
    home = environ.get('HOME', '')
    if sys.platform == 'darwin':
        DOCUMENTS_PATH = path.join(home, 'Library', 'Application Support', APP_USER_DATA_DIR)
    else:
        DOCUMENTS_PATH = path.join(home, '.config', APP_USER_DATA_DIR)
    OLD_DOCUMENTS_PATH = path.join(home, '.config', 'elmocut') if sys.platform != 'darwin' else path.join(home, 'Library', 'Application Support', 'elmocut')

OLD_SETTINGS_PATH = path.join(OLD_DOCUMENTS_PATH, 'elmocut.json')
SETTINGS_PATH = path.join(DOCUMENTS_PATH, 'zubcut.json')

# Extra legacy settings to migrate if zubcut.json is missing (Windows)
LEGACY_SETTINGS_CANDIDATES = []
if sys.platform.startswith('win'):
    _ad = environ.get('APPDATA', '')
    LEGACY_SETTINGS_CANDIDATES = [
        path.join(_ad, 'ZubCut', 'zubcut.json'),
        path.join(_ad, 'ZubCut', 'zubcut.json'),
    ]

TABLE_HEADER_LABELS = ['IP Address', 'MAC Address', 'Vendor', 'Type', 'Nickname']
SCAN_TABLE_COLUMN_MAC = 1
SCAN_TABLE_COLUMN_VENDOR = 2

# Experimental scan table: Me / Router rows — muted grey-green / dark sage.
ADMIN_DEVICE_TABLE_ROW_BG = '#5D706E'
ADMIN_DEVICE_TABLE_ROW_FG = '#eef1f0'
UI_LOG_VICTIM_BLOCK_FG = '#32716D'
UI_TOGGLE_BORDER_ACCENT = '#316E69'
UI_TABLE_SELECTION_BG = '#316E69'
UI_TABLE_SELECTION_FG = '#f2f2f2'
UI_LOG_RESTORE_FG = ADMIN_DEVICE_TABLE_ROW_BG
# When a newer build is available: Settings / main gear highlight (ID selectors vs global QSS).
UPDATE_AVAILABLE_PUSHBUTTON_QSS = (
    'QPushButton#btnUpdate { background-color: #1a3d28; color: #d8f0e4; font-weight: bold; '
    'border: 1px solid #2d5738; border-radius: 4px; }'
)
UPDATE_AVAILABLE_SETTINGS_GEAR_QSS = (
    'QPushButton#btnSettings { background-color: #1a3d28; color: #d8f0e4; font-weight: bold; '
    'border: 1px solid #2d5738; border-radius: 4px; }'
)

# Frameless / stylesheet corner radius (logical px); mask uses same value to avoid corner bleed.
WINDOW_CORNER_RADIUS_PX = 12

# Windows-only Npcap details (ignored on macOS/Linux)
NPCAP_URL = 'https://npcap.com/dist/npcap-1.87.exe'
NPCAP_PATH = 'C:\\Windows\\SysWOW64\\Npcap'

GLOBAL_MAC = 'FF:FF:FF:FF:FF:FF'

DUMMY_ROUTER = {
    'ip': '192.168.1.1',
    'mac': 'FF:FF:FF:FF:FF:FF',
    'vendor': 'NONE',
    'type': 'Router',
    'name': '-',
    'admin': True
}

DUMMY_IFACE = {'name': 'NULL', 'mac': GLOBAL_MAC, 'guid': 'NULL', 'ips': ['0.0.0.0']}

HKEY_AUTOSTART_PATH = 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run'

SETTINGS_KEYS = [
    'count', 'autostart', 'minimized', 'remember', 'killed', 'autoupdate', 'threads', 'iface', 'nicknames',
    'key_kill', 'key_lag', 'key_dupe',
    'show_scan_mac_column', 'show_scan_vendor_column',
]

SETTINGS_VALS = [255, False, True, False, [], True, 12, '', {}, 'L', 'M', 'P', False, False]

# Paid-channel offline licensing (no backend dependency).
# Keep enforcement disabled until a public verify key is configured and licenses are issued.
PAID_LICENSE_ENFORCEMENT = False
PAID_LICENSE_PUBLIC_KEY_B64 = ''
PAID_LICENSE_FILE_PATH = path.join(DOCUMENTS_PATH, 'paid-license.json')
PAID_LICENSE_ADMIN_DB_PATH = path.join(DOCUMENTS_PATH, 'paid-license-admin.json')
PAID_LICENSE_ADMIN_SIGNING_KEY_PATH = path.join(DOCUMENTS_PATH, 'paid-license-signing.key')
PAID_LICENSE_EXPORT_DIR = path.join(DOCUMENTS_PATH, 'paid-licenses')
PAID_LICENSE_MANAGER_UPDATE_URL = 'https://github.com/zubcats/ArpCut-main-updated/releases/download/paid-latest/ZubCut-License-Manager-Setup.exe'
