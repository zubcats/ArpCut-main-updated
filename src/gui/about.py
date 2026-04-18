from PyQt5.QtWidgets import QMainWindow, QLabel
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt

from ui.ui_about import Ui_MainWindow
from tools.qtools import clickable
from tools.utils import goto
from tools.branding import resolve_zubcut_png_path
from assets import app_icon
from constants import APP_DISPLAY_NAME
from tools.frameless_chrome import FramelessResizableMixin, setup_frameless_main_window
from tools.utils_gui import register_window_surface_effects, application_theme_stylesheet

DISCORD_URL = 'https://discord.gg/zub'
LINKTREE_URL = 'https://linktr.ee/zubcastle'


class About(FramelessResizableMixin, QMainWindow, Ui_MainWindow):
    def __init__(self, elmocut, icon):
        super().__init__()
        self.elmocut = elmocut

        self.icon = icon
        self.setWindowIcon(icon)
        self.setupUi(self)

        self.setMinimumSize(420, 620)
        self.setMaximumSize(480, 720)
        self.resize(420, 640)

        self.lblAppIcon.setAlignment(Qt.AlignCenter)
        self.lblAppIcon.setScaledContents(False)
        self.lblAppIcon.setMinimumSize(360, 280)
        self.lblAppIcon.setMaximumHeight(340)
        self.lblAppIcon.setCursor(Qt.ArrowCursor)

        self.lblAppName.setText(f'{APP_DISPLAY_NAME} v{self.elmocut.version}')

        self.lblMyName.setText('ZubOnTop')
        self.lblMyName.setStyleSheet('font-weight: bold;')
        self.lblMyName.setCursor(Qt.ArrowCursor)

        self.lblNickName.hide()

        self.lblTwitter.setText('🔗 Linktree')
        self.lblTwitter.setStyleSheet('color: #43b581; font-size: 12px;')
        clickable(self.lblTwitter).connect(self.open_linktree)

        self.lblLinkedIn.setText('💬 Discord')
        self.lblLinkedIn.setStyleSheet('color: #7289da; font-size: 12px;')
        clickable(self.lblLinkedIn).connect(self.open_discord)

        self.lblGitHub.hide()
        self.lblReddit.hide()

        self.add_credits_section()

        # Full-frame artwork for the dialog (same file as app icon, no margin crop).
        self._about_logo_full = QPixmap()
        _path = resolve_zubcut_png_path()
        if _path:
            self._about_logo_full.load(_path)

        setup_frameless_main_window(self, self.windowTitle(), self.icon, maximizable=False)
        register_window_surface_effects(self)

    def add_credits_section(self):
        credits = QLabel(self.centralwidget)
        credits.setText('ZubCut')
        credits.setAlignment(Qt.AlignCenter)
        credits.setStyleSheet('color: gray; font-size: 10px; margin-top: 15px;')
        self.gridLayout.addWidget(credits, 5, 0, 1, 4)

    def showEvent(self, event):
        super().showEvent(event)
        self.setStyleSheet(application_theme_stylesheet())
        self._refresh_about_logo()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_about_logo()

    def _refresh_about_logo(self):
        label = self.lblAppIcon
        w, h = label.width(), label.height()
        if w < 8 or h < 8:
            return
        dpr = label.devicePixelRatioF()
        tw = max(1, int(w * dpr))
        th = max(1, int(h * dpr))
        if not self._about_logo_full.isNull():
            pm = self._about_logo_full
        else:
            pm = self.icon.pixmap(tw, th, QIcon.Normal, QIcon.Off)
            if pm.isNull() or pm.width() < 2:
                pm = QPixmap()
                pm.loadFromData(app_icon)
        pm = pm.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        label.setPixmap(pm)

    def open_discord(self):
        goto(DISCORD_URL)

    def open_linktree(self):
        goto(LINKTREE_URL)
