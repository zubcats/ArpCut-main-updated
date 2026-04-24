"""Paid build: online sign-in with account name and password only (HTTPS license server)."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from constants import APP_DISPLAY_NAME
from tools.license_offline import (
    install_license_document,
    load_and_validate_installed_license,
    validate_license_document,
)
from tools.license_remote_signin import effective_signin_url, fetch_license_document_via_signin

_LAST_SIGNIN_ERROR = ''


def _set_last_signin_error(reason: str) -> None:
    global _LAST_SIGNIN_ERROR
    _LAST_SIGNIN_ERROR = str(reason or '').strip()


def get_last_signin_error() -> str:
    return str(_LAST_SIGNIN_ERROR or '').strip()


def run_paid_license_signin(parent, window_icon) -> bool:
    """Show modal sign-in. Returns True if user completed install and license validates on disk."""
    _set_last_signin_error('')
    if not effective_signin_url():
        _set_last_signin_error('Missing sign-in server URL')
        QMessageBox.critical(
            parent,
            APP_DISPLAY_NAME,
            'This paid build has no online sign-in server configured.\n\n'
            'Set PAID_LICENSE_SIGNIN_URL in the app build, or the environment variable\n'
            'ZUBCUT_PAID_SIGNIN_URL, to your license server HTTPS URL.',
        )
        return False
    dlg = PaidLicenseSignInDialog(parent, window_icon)
    if dlg.exec_() != QDialog.Accepted:
        if not get_last_signin_error():
            _set_last_signin_error('Sign-in cancelled')
        return False
    res = load_and_validate_installed_license()
    if not res.ok:
        _set_last_signin_error(res.reason)
    return res.ok


class PaidLicenseSignInDialog(QDialog):
    def __init__(self, parent, window_icon):
        super().__init__(parent)
        self.setWindowTitle(f'{APP_DISPLAY_NAME} — Sign in')
        self.setWindowIcon(window_icon)
        self.setWindowModality(Qt.ApplicationModal)
        self._signin_url = effective_signin_url()
        self.resize(440, 220)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(
            QLabel(
                'Sign in with the account name and password from your administrator.',
                self,
            )
        )
        root.addWidget(QLabel('Account name', self))
        self.edtAccount = QLineEdit(self)
        self.edtAccount.setPlaceholderText('Account name')
        root.addWidget(self.edtAccount)

        root.addWidget(QLabel('Password', self))
        self.edtPassword = QLineEdit(self)
        self.edtPassword.setEchoMode(QLineEdit.Password)
        root.addWidget(self.edtPassword)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton('Cancel', self)
        cancel.clicked.connect(self.reject)
        self.btnSignIn = QPushButton('Sign in', self)
        self.btnSignIn.setDefault(True)
        self.btnSignIn.clicked.connect(self._try_sign_in)
        btn_row.addWidget(cancel)
        btn_row.addWidget(self.btnSignIn)
        root.addLayout(btn_row)

    def _try_sign_in(self) -> None:
        account = self.edtAccount.text().strip()
        password = self.edtPassword.text()
        data, err = fetch_license_document_via_signin(self._signin_url, account, password)
        if data is None:
            _set_last_signin_error(err)
            QMessageBox.warning(self, 'Sign in failed', err)
            return
        payload = data.get('payload')
        if not isinstance(payload, dict):
            _set_last_signin_error('Invalid license data from server')
            QMessageBox.warning(self, 'Sign in', 'Invalid license data from server.')
            return
        lic_user = str(payload.get('user_name') or '').strip()
        if lic_user and account.casefold() != lic_user.casefold():
            _set_last_signin_error('Account mismatch')
            QMessageBox.warning(
                self,
                'Account mismatch',
                f'That name does not match this license (expected: {lic_user!r}).',
            )
            return
        res = validate_license_document(data, sign_in_password=password)
        if not res.ok:
            _set_last_signin_error(res.reason)
            QMessageBox.warning(self, 'Sign in failed', res.reason)
            return
        try:
            install_license_document(data)
        except Exception as e:
            _set_last_signin_error(f'Could not save license: {e}')
            QMessageBox.critical(self, 'Sign in', f'Could not save license:\n{e}')
            return
        _set_last_signin_error('')
        self.accept()
