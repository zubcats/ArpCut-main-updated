"""
Windows command-output locale helpers (EN + DE + FR + ES).

We do not call a language API. Localized Windows prints one language; matching
all known tokens (with English fallback) makes DE/FR/ES PCs work the same as EN.
Prefer IP/MAC/GUID regex and Get-Net* object properties when possible; use these
tokens only when scraping ``ipconfig`` / ``netsh`` / ``arp`` text.
"""
from __future__ import annotations

import re
import unicodedata

# --- Accent fold -----------------------------------------------------------------

def fold_latin(s: str) -> str:
    """Lowercase + strip combining marks (á→a) for ASCII-simple token match."""
    t = unicodedata.normalize('NFKD', (s or '').lower())
    return ''.join(ch for ch in t if not unicodedata.combining(ch))


# --- ipconfig / adapter headers --------------------------------------------------

# Section titles: "Ethernet adapter X:", "Adaptador de …:", "Carte …:", …
IPCONFIG_ADAPTER_MARKERS = (
    'adaptador',  # ES
    'adapter',  # EN + DE (...-Adapter)
    'scheda',  # IT (harmless extra)
    'carte',  # FR
)

_IPCONFIG_ADAPTER_HEADER_RE = re.compile(
    r'(?i)\b(' + '|'.join(re.escape(m) for m in IPCONFIG_ADAPTER_MARKERS) + r')\b'
)

# Property-line words that must never be treated as adapter section headers.
_IPCONFIG_HEADER_EXCLUDE = (
    'ipv4',
    'ip address',
    'ip-adresse',
    'adresse',
    'direcci',
    'indirizzo',
    'gateway',
    'passerelle',
    'enlace',
    'dhcp',
    'dns',
    'subnet',
    'mask',
    'mascara',
    'masque',
    'suffix',
    'description',
    'beschreibung',
    'descripci',
    'media state',
    'medienstatus',
    'etat du support',
    'estado de los medios',
)


def ipconfig_line_is_adapter_header(line: str) -> bool:
    s = (line or '').strip()
    if not s.endswith(':') or ':' not in s:
        return False
    head = s.split(':', 1)[0]
    low = fold_latin(head)
    if any(tok in low for tok in _IPCONFIG_HEADER_EXCLUDE):
        return False
    return bool(_IPCONFIG_ADAPTER_HEADER_RE.search(head))


def ipconfig_adapter_name_from_header(line: str) -> str:
    head = (line or '').split(':', 1)[0].strip()
    if not head:
        return ''
    low = fold_latin(head)
    for marker in IPCONFIG_ADAPTER_MARKERS:
        idx = low.find(marker)
        if idx < 0:
            continue
        rest = head[idx + len(marker) :].strip(' :-')
        if rest:
            parts = rest.split()
            return parts[-1] if parts else rest
        parts = head.split()
        return parts[-1] if parts else head
    parts = head.split()
    return parts[-1] if parts else head


# Host IPv4 assignment labels (not gateway/DNS/mask).
IPCONFIG_HOST_IPV4_TOKENS = (
    'ipv4 address',  # EN
    'ip address',
    'ipv4-adresse',  # DE
    'ip-adresse',
    'adresse ipv4',  # FR
    'adresse ip',
    'direccion ipv4',  # ES (folded)
    'direccion ip',
    'indirizzo ipv4',  # IT
    'indirizzo ip',
)

IPCONFIG_NON_HOST_IPV4_TOKENS = (
    'gateway',
    'standardgateway',  # DE
    'passerelle',  # FR
    'puerta de enlace',  # ES
    'enlace predeterminada',
    'gateway predefinito',  # IT
    'dhcp server',
    'dhcp-server',
    'serveur dhcp',
    'servidor dhcp',
    'server dhcp',
    'dns',
    'wins',
    'mask',
    'subnet',
    'subnetzmaske',
    'masque',
    'mascara',
    'route',
)


def ipconfig_line_is_host_ipv4(line: str) -> bool:
    low = fold_latin(line)
    if any(tok in low for tok in IPCONFIG_NON_HOST_IPV4_TOKENS):
        return False
    return any(tok in low for tok in IPCONFIG_HOST_IPV4_TOKENS)


# findstr /c: list for "has a default gateway" probes
IPCONFIG_GATEWAY_FINDSTR_ARGS = (
    '/c:"gateway"',
    '/c:"Standardgateway"',
    '/c:"passerelle"',
    '/c:"enlace"',
)


def ipconfig_gateway_findstr_command() -> str:
    return 'ipconfig | findstr /i ' + ' '.join(IPCONFIG_GATEWAY_FINDSTR_ARGS)


# --- arp -a Interface headers ----------------------------------------------------

# EN Interface: / DE Schnittstelle: / ES Interfaz: / FR Interface :
ARP_INTERFACE_HEADER_RE = re.compile(
    r'(?i)\b(?:interface|schnittstelle|interfaz)\b\s*:'
)


def arp_line_is_interface_header(line: str) -> bool:
    return bool(ARP_INTERFACE_HEADER_RE.search(line or ''))


def arp_ifindex_pattern(gateway_ip: str) -> re.Pattern[str]:
    """
    Match ``Interface: 192.168.137.1 --- 0x10`` (and DE/FR/ES header words).

    Anchors on gateway IP + ``--- 0xHEX`` so missing/odd header words still work.
    """
    gw = re.escape((gateway_ip or '').strip())
    return re.compile(
        rf'(?i)(?:interface|schnittstelle|interfaz)?\s*:?\s*{gw}\s*---\s*0x([0-9a-fA-F]+)',
    )


# --- netsh wlan show interfaces --------------------------------------------------

# Canonical key <- localized netsh field names (folded).
WLAN_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    'name': ('name', 'nom', 'nombre', 'nome'),
    'state': ('state', 'zustand', 'etat', 'estado', 'stato'),
    'ssid': ('ssid',),
    'bssid': ('bssid',),
    'authentication': (
        'authentication',
        'authentifizierung',
        'authentification',
        'autenticacion',
        'autenticazione',
    ),
    'cipher': ('cipher', 'verschlusselung', 'chiffrement', 'cifrado', 'crittografia'),
    'radio type': ('radio type', 'funktyp', 'type de radio', 'tipo de radio', 'tipo radio'),
    'band': ('band', 'bandbreite', 'bande', 'banda'),
    'channel': ('channel', 'kanal', 'canal', 'canale'),
    'signal': ('signal', 'signalstarke', 'senal', 'segnale'),
    'profile': ('profile', 'profil', 'perfil', 'profilo'),
    'guid': ('guid',),
    'receive rate (mbps)': (
        'receive rate (mbps)',
        'receive rate',
        'empfangsrate (mbit/s)',
        'debit de reception (mbit/s)',
        'velocidad de recepcion (mbps)',
    ),
    'transmit rate (mbps)': (
        'transmit rate (mbps)',
        'transmit rate',
        'sendrate (mbit/s)',
        'debit de transmission (mbit/s)',
        'velocidad de transmision (mbps)',
    ),
}

# Connected / not-connected state values (folded).
WLAN_STATE_CONNECTED = (
    'connected',  # EN
    'verbunden',  # DE
    'connecte',  # FR (é folded)
    'conectado',  # ES
    'connesso',  # IT
)
WLAN_STATE_DISCONNECTED = (
    'disconnected',
    'getrennt',
    'deconnecte',
    'desconectado',
    'disconnesso',
)


def wlan_canonical_key(raw_key: str) -> str:
    """Map a localized netsh field name to a canonical English key (or '')."""
    folded = fold_latin(re.sub(r'\s+', ' ', (raw_key or '').strip()))
    if not folded:
        return ''
    for canon, aliases in WLAN_KEY_ALIASES.items():
        if folded in aliases or folded == canon:
            return canon
    return folded  # keep unknown keys as-is (still useful)


def wlan_state_is_connected(state: str, *, ssid: str = '') -> bool:
    """True when netsh reports an associated link (locale-aware)."""
    st = fold_latin(state)
    if st in WLAN_STATE_CONNECTED:
        return True
    if st in WLAN_STATE_DISCONNECTED:
        return False
    # Fallback: non-empty SSID usually means associated even if state word is unknown.
    return bool((ssid or '').strip())


# --- Junk friendly-name filters --------------------------------------------------

BAD_IFACE_STATE_WORDS = frozenset(
    {
        # EN
        'connected',
        'disconnected',
        'enabled',
        'disabled',
        'dedicated',
        'description',
        # DE
        'verbunden',
        'getrennt',
        'aktiviert',
        'deaktiviert',
        'beschreibung',
        'dediziert',
        # FR
        'connecte',
        'deconnecte',
        'active',
        'desactive',
        'description',
        'dedie',
        # ES
        'conectado',
        'desconectado',
        'habilitado',
        'deshabilitado',
        'descripcion',
        'dedicado',
    }
)


def is_bad_iface_display_name(s: str) -> bool:
    t = fold_latin((s or '').strip())
    if not t:
        return True
    if t == 'description' or t.startswith('description') or t.startswith('beschreibung'):
        return True
    if t.startswith('descripcion') or t.startswith('description'):
        return True
    if t in BAD_IFACE_STATE_WORDS:
        return True
    if re.match(r'^interface-\d+$', t):
        return True
    # netsh last-token truncation of "Local Area Connection* 10" → "10"
    if re.fullmatch(r'\d{1,3}', t):
        return True
    return False
