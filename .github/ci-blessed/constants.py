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
# Branch convention:  git `main`  -> stable / production builds (UPDATE_CHANNEL `main` in code)
#                     experimental -> tester builds (UPDATE_CHANNEL `experimental`)
# CI overwrites UPDATE_CHANNEL and APP_BUILD_TIME_ISO per branch; match your branch when developing.
UPDATE_CHANNEL = 'experimental'

GITHUB_REPO_SLUG = 'zubcats/ArpCut-main-updated'
GITHUB_RELEASES_BASE = f'https://github.com/{GITHUB_REPO_SLUG}/releases'

# Single-line: tools/ci_apply_build_constants.py replaces these via ^NAME\s*=.*$
UPDATE_DOWNLOAD_URL_MAIN = f'{GITHUB_RELEASES_BASE}/download/stable-latest/ZubCut-Setup.exe'
UPDATE_DOWNLOAD_URL_EXPERIMENTAL = f'{GITHUB_RELEASES_BASE}/download/experimental-latest/ZubCut-Setup-experimental.exe'
APP_BUILD_TIME_ISO = ''
APP_BUILD_COMMIT = ''

if sys.platform.startswith('win'):
    from zubcut_legacy_migrate import (
        legacy_documents_path_windows,
        legacy_settings_path_windows,
    )

    DOCUMENTS_PATH = path.join(environ.get('APPDATA', ''), APP_USER_DATA_DIR)
    _up = environ.get('USERPROFILE', '')
    OLD_DOCUMENTS_PATH = legacy_documents_path_windows(_up)
    OLD_SETTINGS_PATH = legacy_settings_path_windows(_up)
else:
    from zubcut_legacy_migrate import (
        legacy_documents_path_unix,
        legacy_settings_path_unix,
    )

    home = environ.get('HOME', '')
    DOCUMENTS_PATH = path.join(home, '.config', APP_USER_DATA_DIR)
    _darwin = sys.platform == 'darwin'
    OLD_DOCUMENTS_PATH = legacy_documents_path_unix(home, darwin=_darwin)
    OLD_SETTINGS_PATH = legacy_settings_path_unix(home, darwin=_darwin)
SETTINGS_PATH = path.join(DOCUMENTS_PATH, 'zubcut.json')
LICENSE_FILE_PATH = path.join(DOCUMENTS_PATH, 'zubcut-license.json')
LICENSE_PUBLIC_KEY_B64 = ''
LICENSE_SIGNIN_URL = 'https://zubcut-license-signin.zubcats.workers.dev'

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

# Experimental scan table: Me / Router rows — muted grey-green / dark sage (door trim reference).
ADMIN_DEVICE_TABLE_ROW_BG = '#5D706E'
ADMIN_DEVICE_TABLE_ROW_FG = '#eef1f0'
# Main status strip (lblleft HTML): victim block / kill / lag on / dupe burst — teal-grey swatch.
UI_LOG_VICTIM_BLOCK_FG = '#32716D'
# Kill / Lag / Dupe toolbar buttons + Settings / Lag / Dupe field borders & spin combo chrome.
UI_TOGGLE_BORDER_ACCENT = '#316E69'
# Scan table: selected data row (item brushes); device-count label — same teal grey-green swatch.
UI_TABLE_SELECTION_BG = '#316E69'
UI_TABLE_SELECTION_FG = '#f2f2f2'
# Clumsy mode (inline Ethernet) row — tan / golden selection, dark text (user reference swatch).
CLUMSY_INLINE_MAC = '02:00:00:00:CB:01'
CLUMSY_TABLE_ROW_BG = '#F5E6C8'
CLUMSY_TABLE_ROW_SEL_BG = '#E8A838'
CLUMSY_TABLE_ROW_HOVER_BG = '#EDD4A0'
CLUMSY_TABLE_ROW_FG = '#1a1a1a'
# Unkill, lag off, dupe finished, kill OFF — same sage as Me/Router row background.
UI_LOG_RESTORE_FG = ADMIN_DEVICE_TABLE_ROW_BG
# When a newer build is available: reuse the prior Me/Router strip green for Settings / main gear.
# Use object-name selectors so these beat app-level QPushButton#btnSettings / auxiliary-window rules.
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
    'count', 'autostart', 'minimized', 'remember', 'killed', 'autoupdate', 'threads', 'iface', 'iface_before_clumsy', 'nicknames',
    'nickname_last_ip',
    'key_kill', 'key_lag', 'key_dupe', 'key_pctcut',
    'show_scan_mac_column', 'show_scan_vendor_column',
    'traffic_percent',
    'clumsy_mode',
    'clumsy_topology',
    'mitm_delay_up_ms',
    'mitm_delay_down_ms',
    'mitm_cap_up_mbps',
    'mitm_cap_down_mbps',
    'mitm_delay_enabled',
    'mitm_cap_enabled',
    'mitm_adv_delay_on',
    'mitm_adv_delay_in',
    'mitm_adv_delay_out',
    'mitm_adv_delay_ms',
    'mitm_adv_jitter_on',
    'mitm_adv_jitter_in',
    'mitm_adv_jitter_out',
    'mitm_adv_jitter_ms',
    'mitm_adv_cap_on',
    'mitm_adv_cap_in',
    'mitm_adv_cap_out',
    'mitm_adv_cap_out_mbps',
    'mitm_adv_cap_in_mbps',
    'mitm_adv_loss_on',
    'mitm_adv_loss_in',
    'mitm_adv_loss_out',
    'mitm_adv_loss_pct',
]

# key_* stored as QKeySequence PortableText (e.g. L, M, P or Ctrl+L)
# show_scan_* default False: MAC / Vendor columns hidden until enabled (header or table context menu).
# clumsy_mode default False: must be enabled in Settings (requires restart).
SETTINGS_VALS = [
    25,
    False,
    True,
    False,
    [],
    True,
    12,
    '',
    '',
    {},
    {},
    'L',
    'M',
    'P',
    'K',
    False,
    False,
    50,
    False,
    'hotspot',
    0,
    0,
    0.0,
    0.0,
    True,
    True,
    False,
    True,
    True,
    0,
    False,
    True,
    True,
    0,
    False,
    True,
    True,
    0.0,
    0.0,
    False,
    True,
    True,
    0,
]
