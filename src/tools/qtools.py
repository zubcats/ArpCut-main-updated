from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QMessageBox as QMsg, QStyledItemDelegate, QStyle
from PyQt5.QtCore import pyqtSignal, QEvent, QObject

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


class TableRowNoCellFocusDelegate(QStyledItemDelegate):
    """Uniform row chrome: no per-cell focus ring or stylesheet hover on the cell under the cursor."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.state &= ~QStyle.State_HasFocus
        option.state &= ~QStyle.State_MouseOver

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