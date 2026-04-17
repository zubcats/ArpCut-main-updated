from os import path, environ
import sys

APP_BUNDLE_NAME = 'ZubCut'
APP_EXE_NAME = 'ZubCut.exe'
APP_DISPLAY_NAME = 'ZubCut'
AUTOSTART_REG_VALUE = 'ZubCut'
APP_USER_DATA_DIR = 'ZubCut'
# Update channel / feed settings.
# Set channel to "stable" for normal users, "experimental" for tester builds.
UPDATE_CHANNEL = 'experimental'
# Direct download URL for the latest installer package per channel (.exe).
# Point these at hosted assets (e.g. release artifacts or CDN links).
UPDATE_DOWNLOAD_URL_STABLE = 'https://github.com/zubcats/ArpCut-main-updated/releases/latest/download/ZubCut-Setup.exe'
UPDATE_DOWNLOAD_URL_EXPERIMENTAL = 'https://github.com/zubcats/ArpCut-main-updated/releases/download/experimental-latest/ZubCut-Setup-experimental.exe'

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
        path.join(_ad, 'ArpCutUpdated', 'arpcut.json'),
        path.join(_ad, 'ZubCut', 'arpcut.json'),
    ]

TABLE_HEADER_LABELS = ['IP Address', 'MAC Address', 'Vendor', 'Type', 'Nickname']

# Frameless / stylesheet corner radius (logical px); mask uses same value to avoid corner bleed.
WINDOW_CORNER_RADIUS_PX = 12

# Windows-only Npcap details (ignored on macOS/Linux)
NPCAP_URL = 'https://nmap.org/npcap/dist/npcap-1.50.exe'
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
]

# key_* stored as QKeySequence PortableText (e.g. L, M, P or Ctrl+L)
SETTINGS_VALS = [255, False, True, False, [], True, 12, '', {}, 'L', 'M', 'P']
