"""
Paid build: sign in by account name + license file or pasted JSON (offline signed license).
"""
from __future__ import annotations

import json

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from constants import APP_DISPLAY_NAME
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
        self.resize(500, 420)
        self._path: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(
            QLabel(
                'Enter the account name you were given, then attach the license file\n'
                'your administrator sent you, or paste the full license JSON.',
                self,
            )
        )
        root.addWidget(QLabel('Account name', self))
        self.edtAccount = QLineEdit(self)
        self.edtAccount.setPlaceholderText('Same name as on your license')
        root.addWidget(self.edtAccount)

        row = QHBoxLayout()
        self.btnBrowse = QPushButton('Choose license file…', self)
        self.btnBrowse.clicked.connect(self._browse)
        row.addWidget(self.btnBrowse)
        row.addStretch()
        root.addLayout(row)
        self.lblPath = QLabel('No file selected', self)
        self.lblPath.setWordWrap(True)
        self.lblPath.setStyleSheet('color: #888;')
        root.addWidget(self.lblPath)

        root.addWidget(QLabel('Or paste license JSON', self))
        self.txtPaste = QPlainTextEdit(self)
        self.txtPaste.setPlaceholderText('{ "payload": { ... }, "signature": "..." }')
        self.txtPaste.setMaximumHeight(130)
        root.addWidget(self.txtPaste)

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

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            'Select license file',
            '',
            'License JSON (*.json);;All files (*.*)',
        )
        if path:
            self._path = path
            self.lblPath.setText(path)
            self.txtPaste.clear()

    def _load_document(self) -> dict | None:
        raw = self.txtPaste.toPlainText().strip()
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                QMessageBox.warning(self, 'Invalid JSON', 'Could not parse pasted text as JSON.')
                return None
        if self._path:
            try:
                with open(self._path, 'r', encoding='utf-8') as fh:
                    return json.load(fh)
            except Exception as e:
                QMessageBox.warning(self, 'License file', f'Could not read file:\n{e}')
                return None
        QMessageBox.warning(self, 'Sign in', 'Choose a license file or paste the license JSON.')
        return None

    def _try_sign_in(self) -> None:
        data = self._load_document()
        if not isinstance(data, dict):
            return
        payload = data.get('payload')
        if not isinstance(payload, dict):
            QMessageBox.warning(self, 'Sign in', 'Invalid license document.')
            return
        lic_user = str(payload.get('user_name') or '').strip()
        account = self.edtAccount.text().strip()
        if lic_user:
            if not account:
                QMessageBox.warning(self, 'Sign in', 'Enter the account name you were given.')
                return
            if account.casefold() != lic_user.casefold():
                QMessageBox.warning(
                    self,
                    'Account mismatch',
                    f'That name does not match this license (expected: {lic_user!r}).',
                )
                return
        res = validate_license_document(data)
        if not res.ok:
            QMessageBox.warning(self, 'Sign in failed', res.reason)
            return
        try:
            install_license_document(data)
        except Exception as e:
            QMessageBox.critical(self, 'Sign in', f'Could not save license:\n{e}')
            return
        self.accept()
