from tools.utils_gui import get_settings, set_settings


def get_nicknames_dict():
    n = get_settings('nicknames')
    return n if isinstance(n, dict) else {}


def get_nickname_last_ip_map():
    m = get_settings('nickname_last_ip')
    return m if isinstance(m, dict) else {}


def record_nickname_last_ip(mac: str, ip: str) -> None:
    """Remember last seen IPv4 for a nicknamed device so we can show it on the next launch if the scan misses it."""
    mac = (mac or '').strip()
    ip = (ip or '').strip()
    if not mac or not ip:
        return
    parts = ip.split('.')
    if len(parts) != 4:
        return
    try:
        if not all(0 <= int(x) <= 255 for x in parts):
            return
    except (TypeError, ValueError):
        return
    m = dict(get_nickname_last_ip_map())
    m[mac] = ip
    set_settings('nickname_last_ip', m)


def clear_nickname_last_ip(mac: str) -> None:
    mac = (mac or '').strip()
    if not mac:
        return
    m = dict(get_nickname_last_ip_map())
    if mac in m:
        del m[mac]
        set_settings('nickname_last_ip', m)


class Nicknames:
    def __init__(self):
        self.__db = get_settings('nicknames')
        if not isinstance(self.__db, dict):
            self.__db = {}

    def get_name(self, mac):
        return self.__db.get(mac, '-')

    def set_name(self, mac, name):
        self.__db[mac] = name
        set_settings('nicknames', self.__db)

    def reset_name(self, mac):
        if mac in self.__db:
            del self.__db[mac]
        set_settings('nicknames', self.__db)
        clear_nickname_last_ip(mac)

    @property
    def nicknames_database(self):
        return self.__db
