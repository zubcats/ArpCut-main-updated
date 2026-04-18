"""
Best-effort labels for the device table "Type" column.

Uses Wireshark manuf vendor strings and optional hostname hints when the
caller supplies them. Reverse DNS was intentionally omitted from the scan
path: parallel PTR lookups plus ThreadPoolExecutor shutdown(wait=True) could
block the scan worker for a long time on Windows and destabilize scanning.
"""
from __future__ import annotations

import re


def infer_network_device_type(_mac: str, vendor: str, hostname: str) -> str:
    """
    Return a short user-facing type string for the scan table.
    Falls back to 'User' when nothing matches (legacy default).

    ``hostname`` may be left empty; when set (e.g. from future mDNS/PTR),
    hostname-based rules take precedence over vendor heuristics.
    """
    v = (vendor or "").lower()
    h = (hostname or "").lower()

    # Hostname hints (often more specific than OUI vendor text).
    if h:
        if re.search(
            r"playstation|\.ps5\.|ps5-|ps4-|ps4\.|(?<![a-z0-9])ps[45](?![a-z0-9])",
            h,
        ):
            return "Game console (PlayStation)"
        if "xbox" in h:
            return "Game console (Xbox)"
        if "nintendo" in h or re.search(r"\bswitch\b", h):
            return "Game console (Nintendo)"
        if "steamdeck" in h or "steam-deck" in h:
            return "Handheld (Steam Deck)"
        if "iphone" in h or ("ipad" in h and "kindle" not in h):
            return "Mobile (Apple)"
        if "watch" in h and "apple" in h:
            return "Wearable (Apple Watch)"
        if "homepod" in h:
            return "Smart speaker (HomePod)"
        if any(x in h for x in ("macbook", "imac", "mac-mini", "macmini", "macbookpro", "macbookair", "macpro")):
            return "Computer (Mac)"
        if "surface" in h:
            return "Computer (Surface)"
        if any(x in h for x in ("chromecast", "google-home", "googlenest", "nest-hub")):
            return "Streaming / Google Nest"
        if any(x in h for x in ("echo-dot", "echo.", ".echo", "alexa")):
            return "Smart speaker (Amazon Echo)"
        if any(x in h for x in ("samsung-tv", "tizen", "bravia", "lgwebos", "webos-tv", "roku", "appletv")):
            return "TV / streaming box"
        if "android" in h or re.search(r"\bsm-[a-z0-9]", h):
            return "Phone / tablet (Android)"
        if any(x in h for x in ("laptop", "desktop", "windows-pc", "win-", "pc-")):
            return "Computer (PC / laptop)"

    # Vendor strings from manuf / Wireshark OUI database.
    if "sony interactive" in v or "sony computer entertainment" in v:
        return "Game console (PlayStation)"
    if "sony mobile" in v:
        return "Phone (Sony)"
    if "microsoft" in v and "xbox" in v:
        return "Game console (Xbox)"
    if "nintendo" in v:
        return "Game console (Nintendo)"
    if "valve" in v:
        return "Handheld / PC (Valve / Steam)"
    if "apple" in v:
        return "Apple device"
    if any(
        x in v
        for x in (
            "dell",
            "hewlett",
            "hp,",
            "hp inc",
            "lenovo",
            "acer",
            "msi",
            "toshiba",
            "fujitsu",
            "samsung electro-mechanics",
        )
    ):
        return "Computer (PC / laptop)"
    if "asustek computer" in v:
        return "Computer (PC / laptop)"
    if "asustek" in v and "communi" in v:
        return "Network gear (ASUS router/AP)"
    if "intel corporate" in v or "realtek" in v:
        return "Computer (likely PC / laptop)"
    if any(x in v for x in ("tp-link", "tp link", "ubiquiti", "netgear", "linksys", "eero")):
        return "Network gear (router / AP)"
    if "samsung" in v:
        return "Samsung device (phone / TV / …)"
    if "google" in v:
        return "Google device (Pixel / Nest / …)"
    if "amazon" in v:
        return "Amazon device (Echo / Fire / …)"
    if any(x in v for x in ("xiaomi", "huawei", "oneplus", "oppo", "vivo", "motorola")):
        return "Phone / tablet"
    if "raspberry" in v:
        return "Computer (Raspberry Pi)"
    if "espressif" in v:
        return "IoT (Wi-Fi module)"
    if "qualcomm" in v:
        return "Phone / modem (Qualcomm)"

    return "User"
