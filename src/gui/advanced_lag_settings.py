"""Advanced Lag Settings — extra lag-related options (placeholder for upcoming features).

Section count and labels: edit SECTION_TITLES below (or replace the tuple when you finalize names).
Each entry becomes one QGroupBox in the same spirit as the main Settings window.
"""

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QWidget,
    QLabel,
    QDialogButtonBox,
    QPushButton,
    QGroupBox,
    QScrollArea,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from constants import ADMIN_DEVICE_TABLE_ROW_BG
from tools.frameless_chrome import FramelessResizableMixin, CustomTitleBar
from tools.utils_gui import register_window_surface_effects

# Rename / extend this tuple when you finalize section names (order = top to bottom).
SECTION_TITLES = (
    'Section 1',
    'Section 2',
)


def _section_group(title: str, parent: QWidget) -> QGroupBox:
    """One settings-style section: titled QGroupBox with a vertical slot for future controls."""
    box = QGroupBox(title, parent)
    font = QFont(box.font())
    font.setPointSize(10)
    box.setFont(font)
    inner = QVBoxLayout(box)
    inner.setContentsMargins(12, 10, 12, 12)
    inner.setSpacing(6)
    stub = QLabel('Controls for this section will be added here.', box)
    stub.setWordWrap(True)
    stub.setStyleSheet('color: #9a9a9a; font-size: 11px;')
    inner.addWidget(stub)
    return box


class AdvancedLagSettingsDialog(FramelessResizableMixin, QDialog):
    """Non-modal panel opened from the main flow toggles (right-click → Advanced Lag Settings)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Same QSS object name as Lag Switch / Dupe panels (shared chrome in utils_gui).
        self.setObjectName('zubcutLagDupeDialog')
        self.elmocut = parent
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowTitle('Advanced Lag Settings')
        self.setModal(False)
        self.setMinimumWidth(400)
        self.setMinimumHeight(320)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        win_icon = parent.icon if parent else None
        root.addWidget(
            CustomTitleBar(
                self,
                'Advanced Lag Settings',
                win_icon,
                maximizable=False,
                caption_accent=ADMIN_DEVICE_TABLE_ROW_BG,
            )
        )

        body = QWidget(self)
        body.setObjectName('zubcutDialogBody')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        scroll = QScrollArea(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_inner = QWidget(scroll)
        scroll_layout = QVBoxLayout(scroll_inner)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(10)

        self._section_groups = []
        if SECTION_TITLES:
            for title in SECTION_TITLES:
                grp = _section_group(title, scroll_inner)
                self._section_groups.append(grp)
                scroll_layout.addWidget(grp)
        else:
            empty = QLabel(
                'Add entries to SECTION_TITLES in advanced_lag_settings.py to create sections.',
                scroll_inner,
            )
            empty.setWordWrap(True)
            empty.setStyleSheet('color: #9a9a9a; font-size: 11px;')
            scroll_layout.addWidget(empty)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_inner)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, body)
        buttons.rejected.connect(self.hide)
        layout.addWidget(buttons)

        root.addWidget(body, 1)
        for _pb in self.findChildren(QPushButton):
            _pb.setAutoDefault(False)
            _pb.setDefault(False)
        self._zubcut_use_translucent_surface = False
        register_window_surface_effects(self)
