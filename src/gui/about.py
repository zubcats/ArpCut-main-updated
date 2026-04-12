from PyQt5.QtWidgets import QMainWindow, QLabel, QVBoxLayout, QWidget, QHBoxLayout
from PyQt5.QtGui import QPixmap, QFont, QIcon
from PyQt5.QtCore import Qt

from ui.ui_about import Ui_MainWindow
from tools.qtools import clickable
from tools.utils import goto
from assets import twitter_icon, linkedin_icon, github_icon, app_icon
from constants import APP_DISPLAY_NAME

class About(QMainWindow, Ui_MainWindow):
    # User's social links - EDIT THESE
    USER_DISCORD = 'YOUR_DISCORD_INVITE_OR_USERNAME'  # e.g., 'discord.gg/xxxx' or 'mvgnus'
    USER_TWITTER = 'YOUR_TWITTER_HANDLE'  # e.g., 'mvgnus_'
    USER_GITHUB = 'Mvgnu'  # GitHub username
    
    def __init__(self, elmocut, icon):
        super().__init__()
        self.elmocut = elmocut

        # Setup UI
        self.icon = icon
        self.setWindowIcon(icon)
        self.setupUi(self)
        
        self.setMinimumSize(420, 620)
        self.setMaximumSize(480, 720)
        self.resize(420, 640)

        clickable(self.lblAppIcon).connect(self.user_github)
        self.lblAppIcon.setAlignment(Qt.AlignCenter)
        self.lblAppIcon.setScaledContents(False)
        self.lblAppIcon.setMinimumSize(360, 280)
        self.lblAppIcon.setMaximumHeight(340)

        # Set app info
        self.lblAppName.setText(f'{APP_DISPLAY_NAME} v{self.elmocut.version}')
        self.lblMyName.setText('Mvgnus')
        self.lblMyName.setStyleSheet('font-weight: bold;')
        
        # Replace nickname label with "My Socials" section
        self.lblNickName.setText('— My Socials —')
        self.lblNickName.setStyleSheet('color: #3498db; font-weight: bold; margin-top: 10px;')
        
        # Repurpose existing social labels for user socials
        # Twitter -> X (Twitter)
        self.lblTwitter.setText('𝕏 Twitter')
        self.lblTwitter.setStyleSheet('color: white; font-size: 12px;')
        clickable(self.lblTwitter).connect(self.user_twitter)
        
        # LinkedIn -> Discord  
        self.lblLinkedIn.setText('💬 Discord')
        self.lblLinkedIn.setStyleSheet('color: #7289da; font-size: 12px;')
        clickable(self.lblLinkedIn).connect(self.user_discord)
        
        # GitHub -> User's GitHub
        self.lblGitHub.setText('🐙 GitHub')
        self.lblGitHub.setStyleSheet('color: #6cc644; font-size: 12px;')
        clickable(self.lblGitHub).connect(self.user_github)
        
        self.lblReddit.setText('')
        self.lblReddit.hide()
        
        # Add credits label at bottom
        self.add_credits_section()
    
    def add_credits_section(self):
        credits = QLabel(self.centralwidget)
        credits.setText('ZubCut')
        credits.setAlignment(Qt.AlignCenter)
        credits.setStyleSheet('color: gray; font-size: 10px; margin-top: 15px;')
        self.gridLayout.addWidget(credits, 5, 0, 1, 4)
    
    def showEvent(self, event):
        super().showEvent(event)
        self.setStyleSheet(self.elmocut.styleSheet())
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
        pm = self.icon.pixmap(tw, th, QIcon.Normal, QIcon.Off)
        if pm.isNull() or pm.width() < 2:
            pm = QPixmap()
            pm.loadFromData(app_icon)
        pm = pm.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        label.setPixmap(pm)

    # User's social links
    def user_twitter(self):
        if self.USER_TWITTER and self.USER_TWITTER != 'YOUR_TWITTER_HANDLE':
            goto(f'https://twitter.com/{self.USER_TWITTER}')
    
    def user_discord(self):
        if self.USER_DISCORD and self.USER_DISCORD != 'YOUR_DISCORD_INVITE_OR_USERNAME':
            # Could be discord.gg link or just show username
            if 'discord.gg' in self.USER_DISCORD or 'discord.com' in self.USER_DISCORD:
                goto(self.USER_DISCORD)
            else:
                goto(f'https://discord.com/users/{self.USER_DISCORD}')
    
    def user_github(self):
        goto(f'https://github.com/{self.USER_GITHUB}')
    
