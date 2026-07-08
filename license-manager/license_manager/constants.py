from __future__ import annotations

import os
import sys

APP_NAME = 'ZubCut License Manager'
APP_DIR_NAME = 'ZubCut-LicenseManager'
DEFAULT_WORKER_URL = 'https://zubcut-license-signin.zubcats.workers.dev'
SIGNIN_PBKDF2_ITERS_DEFAULT = 100_000

if sys.platform.startswith('win'):
    _base = os.path.join(os.environ.get('APPDATA', ''), APP_DIR_NAME)
else:
    _base = os.path.join(os.environ.get('HOME', ''), '.config', APP_DIR_NAME)

SETTINGS_PATH = os.path.join(_base, 'settings.json')
ACCOUNTS_PATH = os.path.join(_base, 'accounts.json')
