"""Load/save keyboard shortcuts from settings (QKeySequence PortableText)."""
from PyQt5.QtGui import QKeySequence


def keyseq_from_setting(value, fallback_qt_key):
    """Build QKeySequence from stored string; fallback is Qt.Key_* enum value."""
    if not value or not isinstance(value, str):
        return QKeySequence(fallback_qt_key)
    s = value.strip()
    ks = QKeySequence.fromString(s, QKeySequence.PortableText)
    if ks.isEmpty():
        ks = QKeySequence(s)
    if ks.isEmpty():
        return QKeySequence(fallback_qt_key)
    return ks


def keyseq_to_setting(qs):
    if qs is None or qs.isEmpty():
        return ''
    return qs.toString(QKeySequence.PortableText)
