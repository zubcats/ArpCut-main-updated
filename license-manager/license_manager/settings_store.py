from __future__ import annotations

import json
import os
from typing import Any

from license_manager.constants import ACCOUNTS_PATH, SETTINGS_PATH


def _ensure_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def load_settings() -> dict[str, Any]:
    _ensure_dir(SETTINGS_PATH)
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: dict[str, Any]) -> None:
    _ensure_dir(SETTINGS_PATH)
    with open(SETTINGS_PATH, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)


def load_accounts() -> list[dict[str, Any]]:
    _ensure_dir(ACCOUNTS_PATH)
    try:
        with open(ACCOUNTS_PATH, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_accounts(rows: list[dict[str, Any]]) -> None:
    _ensure_dir(ACCOUNTS_PATH)
    with open(ACCOUNTS_PATH, 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, indent=2)
