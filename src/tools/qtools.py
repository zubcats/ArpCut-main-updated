from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QMessageBox as QMsg, QStyledItemDelegate, QStyle
from PyQt5.QtCore import Qt, pyqtSignal, QEvent, QObject

class Buttons:
    CANCEL = QMsg.Cancel
    YES    = QMsg.Yes
    NO     = QMsg.No
    OK     = QMsg.Ok

class MsgType:
    INFO     = QMsg.information
    WARN     = QMsg.warning
    CRITICAL = QMsg.critical
    ERROR    = QMsg.critical

class MsgIcon:
    INFO     = QMsg.Information
    WARN     = QMsg.Warning
    CRITICAL = QMsg.Critical

def colored_item(elmnt, c1, c2):
    """
    Add colors to Table rows
    """
    elmnt.setBackground(QColor(c1))
    elmnt.setForeground(QColor(c2))


def scan_table_item_flags():
    """Every scan-table cell stays enabled and selectable.

    Me/Router use sage styling and reject Kill/Lag in the click handlers. If those
    rows omit ItemIsSelectable, Qt 5.15 can trap currentIndex on them so later
    clicks on a User/PS5 row never take selection.
    """
    return Qt.ItemIsEnabled | Qt.ItemIsSelectable


def resolve_scan_table_click_row(n_rows, clicked_row, current_row=-1) -> int:
    """Prefer the clicked row so a stale Me/Router currentIndex cannot mask a client click."""
    try:
        n = int(n_rows)
        clicked = int(clicked_row)
    except (TypeError, ValueError):
        return -1
    if 0 <= clicked < n:
        return clicked
    try:
        current = int(current_row)
    except (TypeError, ValueError):
        return -1
    if 0 <= current < n:
        return current
    return -1


class TableRowNoCellFocusDelegate(QStyledItemDelegate):
    """Uniform row chrome: no per-cell focus/hover/selection paint — row colours come from item BackgroundRole."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.state &= ~QStyle.State_HasFocus
        option.state &= ~QStyle.State_MouseOver
        option.state &= ~QStyle.State_Selected

def msg_box(title, text, window_icon, icon, buttons=Buttons.OK):
    """
    Main app independent QMessageBox
    """
    msg = QMsg()
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setWindowIcon(icon)
    msg.setIcon(window_icon)
    msg.setStandardButtons(buttons)
    return msg.exec_()

def clickable(widget):
    class Filter(QObject):
        clicked = pyqtSignal()
        def eventFilter(self, obj, event):
            if obj == widget and \
               event.type() == QEvent.MouseButtonRelease and \
               obj.rect().contains(event.pos()):
                    self.clicked.emit()
                    return True
            return False
    
    _filter = Filter(widget)
    widget.installEventFilter(_filter)
    return _filter.clicked