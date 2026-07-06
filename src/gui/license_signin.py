"""Online sign-in with account name and password (HTTPS license server)."""
from __future__ import annotations

import os

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
from tools.license_remote_signin import (
    effective_signin_url,
    ensure_signin_verify_key,
    fetch_license_document_via_signin,
    fetch_remote_verify_key_b64,
    signin_failure_hint,
    write_signin_diagnostic,
)

_LAST_SIGNIN_ERROR = ''


def _format_signin_error(reason: str) -> str:
    reason = str(reason or '').strip()
    hint = signin_failure_hint(reason)
    if hint:
        return f'{reason}\n\n{hint}'
    return reason


def _show_signin_failure(parent, title: str, reason: str, *, account: str = '', step: str = '') -> None:
    log_path = write_signin_diagnostic(step=step or 'signin', account=account, error=reason)
    text = _format_signin_error(reason)
    text = f'{text}\n\nDetails saved to:\n{log_path}'
    QMessageBox.warning(parent, title, text)


def _set_last_signin_error(reason: str) -> None:
    global _LAST_SIGNIN_ERROR
    _LAST_SIGNIN_ERROR = str(reason or '').strip()


def get_last_signin_error() -> str:
    return str(_LAST_SIGNIN_ERROR or '').strip()


def run_license_signin(parent, window_icon) -> bool:
    """Show modal sign-in. Returns True if user completed install and license validates on disk."""
    _set_last_signin_error('')
    if not effective_signin_url():
        _set_last_signin_error('Missing sign-in server URL')
        QMessageBox.critical(
            parent,
            APP_DISPLAY_NAME,
            'This build has no online sign-in server configured.\n\n'
            'Install the latest official ZubCut build from GitHub, or set the environment variable\n'
            'ZUBCUT_LICENSE_SIGNIN_URL to your license server HTTPS URL.',
        )
        return False
    try:
        from tools.license_offline import _effective_public_key_b64

        ok_key, key_err = ensure_signin_verify_key()
        if not ok_key and not _effective_public_key_b64():
            _set_last_signin_error(key_err or 'Missing license verify key in this build')
            QMessageBox.critical(
                parent,
                APP_DISPLAY_NAME,
                'This build could not load the license verification key.\n\n'
                f'{key_err or "Reinstall from the official GitHub release."}\n\n'
                'If you are the admin: set Worker secret LICENSE_PUBLIC_KEY_B64 '
                '(same as License Manager → Public Verify Key) and redeploy the worker.',
            )
            return False
    except Exception:
        pass
    dlg = LicenseSignInDialog(parent, window_icon)
    if dlg.exec_() != QDialog.Accepted:
        if not get_last_signin_error():
            _set_last_signin_error('Sign-in cancelled')
        return False
    res = load_and_validate_installed_license()
    if not res.ok:
        _set_last_signin_error(res.reason)
    return res.ok


class LicenseSignInDialog(QDialog):
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
        account = self.edtAccount.text().strip().lower()
        password = self.edtPassword.text()
        data, err = fetch_license_document_via_signin(self._signin_url, account, password)
        if data is None:
            _set_last_signin_error(err)
            _show_signin_failure(self, 'Sign in failed', err, account=account, step='server')
            return
        payload = data.get('payload')
        if not isinstance(payload, dict):
            err = 'Invalid license data from server'
            _set_last_signin_error(err)
            _show_signin_failure(self, 'Sign in', err, account=account, step='payload')
            return
        # Password was already verified by the HTTPS sign-in server (KV bundle).
        # Do not re-check payload.password_hash here — bundle root salt/hash can
        # differ from embedded payload fields and would reject valid logins.
        res = validate_license_document(data)
        if not res.ok and 'signature invalid' in str(res.reason or '').casefold():
            remote_key = fetch_remote_verify_key_b64(self._signin_url)
            if remote_key:
                os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64'] = remote_key
                res = validate_license_document(data)
        if not res.ok:
            _set_last_signin_error(res.reason)
            _show_signin_failure(self, 'Sign in failed', res.reason, account=account, step='verify')
            return
        try:
            install_license_document(
                data,
                signin_account=account,
                verify_key_b64=os.environ.get('ZUBCUT_LICENSE_PUBLIC_KEY_B64', ''),
            )
        except Exception as e:
            err = f'Could not save license: {e}'
            _set_last_signin_error(err)
            write_signin_diagnostic(step='save', account=account, error=err)
            QMessageBox.critical(self, 'Sign in', err)
            return
        write_signin_diagnostic(step='ok', account=account, error='')
        _set_last_signin_error('')
        self.accept()
