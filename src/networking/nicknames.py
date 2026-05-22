"""Per-subnet nicknames: same MAC on hotspot vs home LAN keeps separate names and table rows."""
from __future__ import annotations

from tools.utils import good_mac
from tools.utils_gui import get_settings, set_settings


def ipv4_subnet_prefix(ip: str) -> str:
    """First three octets, e.g. 192.168.137 from 192.168.137.50."""
    ip = (ip or '').strip()
    parts = ip.split('.')
    if len(parts) != 4:
        return ''
    try:
        if not all(0 <= int(x) <= 255 for x in parts):
            return ''
    except (TypeError, ValueError):
        return ''
    return '.'.join(parts[:3])


def is_legacy_nickname_key(key: str) -> bool:
    """Pre-v2 storage: MAC only (no ``|subnet`` suffix)."""
    k = (key or '').strip()
    return bool(k) and '|' not in k and ':' in k


def nickname_profile_key(mac: str, ip: str) -> str:
    """Stable settings key: ``aa:bb:cc:dd:ee:ff|192.168.137``."""
    mac = good_mac(mac)
    prefix = ipv4_subnet_prefix(ip)
    if not mac or not prefix:
        return mac or ''
    return f'{mac}|{prefix}'


def parse_nickname_profile_key(key: str) -> tuple[str, str]:
    """Return (mac, subnet_prefix) from a profile or legacy key."""
    k = (key or '').strip()
    if '|' in k:
        mac_part, prefix = k.split('|', 1)
        return good_mac(mac_part), prefix.strip()
    return good_mac(k), ''


def get_nicknames_dict() -> dict:
    n = get_settings('nicknames')
    return n if isinstance(n, dict) else {}


def get_nickname_last_ip_map() -> dict:
    m = get_settings('nickname_last_ip')
    return m if isinstance(m, dict) else {}


def migrate_nickname_storage() -> None:
    """Move MAC-only nicknames to MAC|subnet keys using the last known IP per device."""
    db = dict(get_nicknames_dict())
    last = dict(get_nickname_last_ip_map())
    changed = False
    for key, name in list(db.items()):
        if not is_legacy_nickname_key(key) or not name or name == '-':
            continue
        ip = last.get(key)
        if not ip:
            continue
        pk = nickname_profile_key(key, ip)
        if not pk:
            continue
        if db.get(pk) in (None, '-', ''):
            db[pk] = name
        if key in db:
            del db[key]
            changed = True
    for key, ip in list(last.items()):
        if not is_legacy_nickname_key(key):
            continue
        pk = nickname_profile_key(key, ip)
        if not pk or pk == key:
            continue
        last[pk] = ip
        del last[key]
        changed = True
    if changed:
        set_settings('nicknames', db)
        set_settings('nickname_last_ip', last)


def record_nickname_last_ip(mac: str, ip: str) -> None:
    """Remember last IPv4 for this MAC on this subnet (phantom row after restart)."""
    ip = (ip or '').strip()
    if not ip:
        return
    try:
        from tools.clumsy_inline import clumsy_mode_enabled, clumsy_ics_downstream_prefix

        prefix = clumsy_ics_downstream_prefix()
        if not clumsy_mode_enabled() and ip.startswith(prefix):
            return
    except Exception:
        pass
    pk = nickname_profile_key(mac, ip)
    if not pk:
        return
    m = dict(get_nickname_last_ip_map())
    m[pk] = ip
    set_settings('nickname_last_ip', m)


def clear_nickname_last_ip(mac: str, ip: str | None = None) -> None:
    mac = good_mac(mac)
    if not mac:
        return
    m = dict(get_nickname_last_ip_map())
    if ip:
        pk = nickname_profile_key(mac, ip)
        if pk in m:
            del m[pk]
            set_settings('nickname_last_ip', m)
        return
    prefix = None
    to_del = [k for k in m if k == mac or k.startswith(mac + '|')]
    if not to_del:
        return
    for k in to_del:
        del m[k]
    set_settings('nickname_last_ip', m)


class Nicknames:
    def __init__(self):
        migrate_nickname_storage()
        raw = get_nicknames_dict()
        self.__db = dict(raw) if isinstance(raw, dict) else {}

    def _persist(self) -> None:
        set_settings('nicknames', dict(self.__db))

    def get_name(self, mac, ip=None):
        mac = good_mac(mac)
        if ip:
            pk = nickname_profile_key(mac, ip)
            if pk and pk in self.__db:
                return self.__db[pk]
        if mac and is_legacy_nickname_key(mac) and mac in self.__db:
            return self.__db[mac]
        if mac and ip:
            prefix = ipv4_subnet_prefix(ip)
            for key, val in self.__db.items():
                km, kp = parse_nickname_profile_key(key)
                if km == mac and kp == prefix:
                    return val
        return '-'

    def set_name(self, mac, name, ip=None):
        if not ip:
            self.__db[good_mac(mac)] = name
            self._persist()
            return
        pk = nickname_profile_key(mac, ip)
        if not pk:
            return
        self.__db[pk] = name
        legacy = good_mac(mac)
        if legacy in self.__db and is_legacy_nickname_key(legacy):
            del self.__db[legacy]
        self._persist()

    def reset_name(self, mac, ip=None):
        if ip:
            pk = nickname_profile_key(mac, ip)
            if pk in self.__db:
                del self.__db[pk]
            clear_nickname_last_ip(mac, ip)
        else:
            mac = good_mac(mac)
            for key in list(self.__db.keys()):
                km, _ = parse_nickname_profile_key(key)
                if km == mac or key == mac:
                    del self.__db[key]
            clear_nickname_last_ip(mac)
        self._persist()

    @property
    def nicknames_database(self):
        return self.__db
