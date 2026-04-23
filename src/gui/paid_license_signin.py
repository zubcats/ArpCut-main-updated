"""
Paid build: sign in with account name, password, and sign-in code (offline; no JSON file for users).
"""
from __future__ import annotations

import json

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from constants import APP_DISPLAY_NAME
from tools.license_activation_code import decode_activation_token
from tools.license_offline import (
    install_license_document,
    load_and_validate_installed_license,
    validate_license_document,
)


def run_paid_license_signin(parent, window_icon) -> bool:
    """Show modal sign-in. Returns True if user completed install and license validates on disk."""
    dlg = PaidLicenseSignInDialog(parent, window_icon)
    if dlg.exec_() != QDialog.Accepted:
        return False
    return load_and_validate_installed_license().ok


class PaidLicenseSignInDialog(QDialog):
    def __init__(self, parent, window_icon):
        super().__init__(parent)
        self.setWindowTitle(f'{APP_DISPLAY_NAME} — Sign in')
        self.setWindowIcon(window_icon)
        self.setWindowModality(Qt.ApplicationModal)
        self.resize(520, 420)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(
            QLabel(
                'Enter the account name and password your administrator gave you,\n'
                'then paste the sign-in code (one line, starts with ZC1).',
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
        self.edtPassword.setPlaceholderText('Same password they chose for you')
        root.addWidget(self.edtPassword)

        root.addWidget(QLabel('Sign-in code', self))
        self.txtCode = QPlainTextEdit(self)
        self.txtCode.setPlaceholderText('Paste the full line starting with ZC1…')
        self.txtCode.setMinimumHeight(100)
        root.addWidget(self.txtCode)

        adv = QLabel('Advanced: you can paste legacy license JSON here instead of a ZC1 code.', self)
        adv.setStyleSheet('color: #888; font-size: 11px;')
        root.addWidget(adv)

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

    def _parse_license_document(self) -> dict | None:
        raw = self.txtCode.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, 'Sign in', 'Paste your sign-in code.')
            return None
        data = decode_activation_token(raw)
        if data is not None:
            return data
        try:
            return json.loads(raw)
        except Exception:
            QMessageBox.warning(
                self,
                'Invalid code',
                'Could not read that as a sign-in code or JSON.\n'
                'Use the full line starting with ZC1 from your administrator.',
            )
            return None

    def _try_sign_in(self) -> None:
        data = self._parse_license_document()
        if not isinstance(data, dict):
            return
        payload = data.get('payload')
        if not isinstance(payload, dict):
            QMessageBox.warning(self, 'Sign in', 'Invalid license data.')
            return
        lic_user = str(payload.get('user_name') or '').strip()
        account = self.edtAccount.text().strip()
        if lic_user:
            if not account:
                QMessageBox.warning(self, 'Sign in', 'Enter your account name.')
                return
            if account.casefold() != lic_user.casefold():
                QMessageBox.warning(
                    self,
                    'Account mismatch',
                    f'That name does not match this license (expected: {lic_user!r}).',
                )
                return
        password = self.edtPassword.text()
        res = validate_license_document(data, sign_in_password=password)
        if not res.ok:
            QMessageBox.warning(self, 'Sign in failed', res.reason)
            return
        try:
            install_license_document(data)
        except Exception as e:
            QMessageBox.critical(self, 'Sign in', f'Could not save license:\n{e}')
            return
        self.accept()
