from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from license_manager.admin_crypto import (
    build_account_license,
    load_private_key,
    public_key_b64,
    renew_account_license,
    set_account_status,
)
from license_manager.cloud_api import CloudApiError, delete_account, test_connection, upsert_account
from license_manager.constants import APP_NAME, DEFAULT_WORKER_URL
from license_manager.settings_store import load_accounts, load_settings, save_accounts, save_settings
from license_manager.ui.crash_reports_widget import CrashReportsWidget


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1080, 720)
        self._accounts: list[dict] = []
        self._build_ui()
        self._load_from_disk()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel('Signing private key (.pem):', self))
        self.edtKeyPath = QLineEdit(self)
        key_row.addWidget(self.edtKeyPath, 1)
        btnBrowseKey = QPushButton('Browse…', self)
        btnBrowseKey.clicked.connect(self._browse_key)
        key_row.addWidget(btnBrowseKey)
        root.addLayout(key_row)

        self.lblPublicKey = QLabel('Public Verify Key: (load a private key)', self)
        self.lblPublicKey.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lblPublicKey.setWordWrap(True)
        root.addWidget(self.lblPublicKey)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_accounts_tab(), 'Accounts')
        self.tabs.addTab(self._build_cloud_tab(), 'Cloud sign-in sync')
        self.tabs.addTab(self._build_crash_tab(), 'Crash reports')
        root.addWidget(self.tabs, 1)

    def _build_accounts_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        btn_row = QHBoxLayout()
        for label, slot in (
            ('Create Account', self._create_account),
            ('Renew', self._renew_account),
            ('Revoke', self._revoke_account),
            ('Activate', self._activate_account),
            ('Delete', self._delete_account),
            ('Push selected to cloud', self._push_selected),
            ('View crash reports', self._view_crash_reports_for_account),
        ):
            btn = QPushButton(label, page)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.accountsTable = QTableWidget(0, 5, page)
        self.accountsTable.setHorizontalHeaderLabels(
            ['Account', 'Status', 'Expires', 'License ID', 'Cloud synced']
        )
        self.accountsTable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.accountsTable.setSelectionMode(QAbstractItemView.SingleSelection)
        self.accountsTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.accountsTable.verticalHeader().setVisible(False)
        hdr = self.accountsTable.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.accountsTable)
        return page

    def _build_cloud_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        box = QGroupBox('Cloud sign-in sync', page)
        form = QFormLayout(box)
        self.edtWorkerUrl = QLineEdit(DEFAULT_WORKER_URL, box)
        form.addRow('Worker URL', self.edtWorkerUrl)
        self.edtAdminSecret = QLineEdit(box)
        self.edtAdminSecret.setEchoMode(QLineEdit.Password)
        form.addRow('Admin secret', self.edtAdminSecret)
        self.chkAutoPush = QCheckBox('Push to cloud automatically when accounts change', box)
        form.addRow('', self.chkAutoPush)
        layout.addWidget(box)

        btn_row = QHBoxLayout()
        btnSave = QPushButton('Save cloud settings', page)
        btnSave.clicked.connect(self._save_cloud_settings)
        btnTest = QPushButton('Test connection', page)
        btnTest.clicked.connect(self._test_cloud)
        btn_row.addWidget(btnSave)
        btn_row.addWidget(btnTest)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()
        return page

    def _build_crash_tab(self) -> QWidget:
        self.crashWidget = CrashReportsWidget(self)
        return self.crashWidget

    def _load_from_disk(self) -> None:
        settings = load_settings()
        self.edtKeyPath.setText(str(settings.get('private_key_path') or ''))
        self.edtWorkerUrl.setText(str(settings.get('worker_url') or DEFAULT_WORKER_URL))
        self.edtAdminSecret.setText(str(settings.get('admin_secret') or ''))
        self.chkAutoPush.setChecked(bool(settings.get('auto_push_cloud', True)))
        self._accounts = load_accounts()
        self._refresh_accounts_table()
        self._refresh_public_key_label()
        self._apply_cloud_to_crash_widget()

    def _save_all_settings(self) -> None:
        save_settings(
            {
                'private_key_path': self.edtKeyPath.text().strip(),
                'worker_url': self.edtWorkerUrl.text().strip(),
                'admin_secret': self.edtAdminSecret.text(),
                'auto_push_cloud': self.chkAutoPush.isChecked(),
            }
        )

    def _apply_cloud_to_crash_widget(self) -> None:
        accounts = [str(r.get('account_key') or '') for r in self._accounts]
        self.crashWidget.configure(
            self.edtWorkerUrl.text().strip(),
            self.edtAdminSecret.text(),
            known_accounts=accounts,
        )

    def _browse_key(self) -> None:
        from PyQt5.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            'Select Ed25519 private key',
            '',
            'PEM files (*.pem);;All files (*)',
        )
        if path:
            self.edtKeyPath.setText(path)
            self._save_all_settings()
            self._refresh_public_key_label()

    def _refresh_public_key_label(self) -> None:
        path = self.edtKeyPath.text().strip()
        if not path:
            self.lblPublicKey.setText('Public Verify Key: (load a private key)')
            return
        try:
            pk = load_private_key(path)
            self.lblPublicKey.setText(f'Public Verify Key: {public_key_b64(pk)}')
        except Exception as exc:
            self.lblPublicKey.setText(f'Public Verify Key: error — {exc}')

    def _require_private_key(self):
        path = self.edtKeyPath.text().strip()
        if not path:
            QMessageBox.warning(self, APP_NAME, 'Select your Ed25519 signing private key first.')
            return None
        try:
            return load_private_key(path)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f'Could not load private key:\n{exc}')
            return None

    def _selected_account_index(self) -> int:
        rows = self.accountsTable.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _refresh_accounts_table(self) -> None:
        self.accountsTable.setRowCount(0)
        for rec in self._accounts:
            r = self.accountsTable.rowCount()
            self.accountsTable.insertRow(r)
            cols = (
                str(rec.get('account_key') or ''),
                str(rec.get('status') or ''),
                str(rec.get('expires_at') or ''),
                str(rec.get('license_id') or ''),
                str(rec.get('cloud_synced_at') or '—'),
            )
            for c, text in enumerate(cols):
                self.accountsTable.setItem(r, c, QTableWidgetItem(text))

    def _persist_accounts(self) -> None:
        save_accounts(self._accounts)
        self._refresh_accounts_table()

    def _cloud_ready(self) -> tuple[str, str] | None:
        url = self.edtWorkerUrl.text().strip()
        secret = self.edtAdminSecret.text()
        if not url or not secret:
            QMessageBox.warning(self, APP_NAME, 'Set Worker URL and Admin secret on the Cloud tab.')
            return None
        return url, secret

    def _maybe_push(self, account_key: str, bundle: dict) -> None:
        if not self.chkAutoPush.isChecked():
            return
        ready = self._cloud_ready()
        if not ready:
            return
        url, secret = ready
        try:
            upsert_account(url, secret, account_key, bundle)
        except CloudApiError as exc:
            QMessageBox.warning(self, 'Cloud push', str(exc))

    def _create_account(self) -> None:
        sk = self._require_private_key()
        if sk is None:
            return
        account, ok = QInputDialog.getText(self, 'Create Account', 'Account name (lowercase):')
        if not ok:
            return
        account = account.strip().lower()
        if not account:
            return
        password, ok = QInputDialog.getText(
            self,
            'Create Account',
            'Password for customer sign-in:',
            QLineEdit.Password,
        )
        if not ok or not password:
            return
        days, ok = QInputDialog.getInt(self, 'Create Account', 'Subscription days:', 30, 1, 3650)
        if not ok:
            return
        bundle, local = build_account_license(
            account_key=account,
            password=password,
            private_key=sk,
            days=days,
        )
        self._accounts = [r for r in self._accounts if r.get('account_key') != account]
        self._accounts.append(local)
        self._persist_accounts()
        self._maybe_push(account, bundle)
        QMessageBox.information(
            self,
            'Account created',
            f'Account: {account}\nExpires: {local.get("expires_at")}\n\n'
            'Give the customer this account name and password for ZubCut sign-in.',
        )

    def _renew_account(self) -> None:
        idx = self._selected_account_index()
        if idx < 0:
            QMessageBox.information(self, APP_NAME, 'Select an account first.')
            return
        sk = self._require_private_key()
        if sk is None:
            return
        rec = self._accounts[idx]
        days, ok = QInputDialog.getInt(self, 'Renew', 'Extend by days:', 30, 1, 3650)
        if not ok:
            return
        new_password, ok = QInputDialog.getText(
            self,
            'Renew',
            'New password (leave blank to keep auto-generated):',
            QLineEdit.Password,
        )
        if not ok:
            return
        bundle, local = renew_account_license(
            rec,
            private_key=sk,
            days=days,
            password=new_password or None,
        )
        self._accounts[idx] = local
        self._persist_accounts()
        self._maybe_push(local['account_key'], bundle)
        QMessageBox.information(self, 'Renewed', f'Account {local["account_key"]} renewed.')

    def _set_status(self, status: str) -> None:
        idx = self._selected_account_index()
        if idx < 0:
            QMessageBox.information(self, APP_NAME, 'Select an account first.')
            return
        sk = self._require_private_key()
        if sk is None:
            return
        bundle, local = set_account_status(self._accounts[idx], private_key=sk, status=status)
        self._accounts[idx] = local
        self._persist_accounts()
        self._maybe_push(local['account_key'], bundle)

    def _revoke_account(self) -> None:
        self._set_status('revoked')

    def _activate_account(self) -> None:
        self._set_status('active')

    def _delete_account(self) -> None:
        idx = self._selected_account_index()
        if idx < 0:
            QMessageBox.information(self, APP_NAME, 'Select an account first.')
            return
        rec = self._accounts[idx]
        account = str(rec.get('account_key') or '')
        if (
            QMessageBox.question(
                self,
                'Delete account',
                f'Delete local account {account}?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        ready = self._cloud_ready()
        if ready and self.chkAutoPush.isChecked():
            url, secret = ready
            try:
                delete_account(url, secret, account)
            except CloudApiError as exc:
                QMessageBox.warning(self, 'Cloud delete', str(exc))
        del self._accounts[idx]
        self._persist_accounts()

    def _push_selected(self) -> None:
        idx = self._selected_account_index()
        if idx < 0:
            QMessageBox.information(self, APP_NAME, 'Select an account first.')
            return
        ready = self._cloud_ready()
        if not ready:
            return
        url, secret = ready
        rec = self._accounts[idx]
        account = str(rec.get('account_key') or '')
        bundle = {
            'password_salt': rec.get('password_salt'),
            'password_hash_hex': rec.get('password_hash_hex'),
            'password_iters': rec.get('password_iters'),
            'license': rec.get('license'),
        }
        try:
            upsert_account(url, secret, account, bundle)
        except CloudApiError as exc:
            QMessageBox.warning(self, 'Push failed', str(exc))
            return
        from datetime import datetime, timezone

        rec['cloud_synced_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self._accounts[idx] = rec
        self._persist_accounts()
        QMessageBox.information(self, 'Push complete', f'Pushed {account} to cloud.')

    def _view_crash_reports_for_account(self) -> None:
        idx = self._selected_account_index()
        if idx < 0:
            QMessageBox.information(self, APP_NAME, 'Select an account first.')
            return
        ready = self._cloud_ready()
        if not ready:
            return
        account = str(self._accounts[idx].get('account_key') or '').strip().lower()
        self._apply_cloud_to_crash_widget()
        self.crashWidget.refresh()
        self.crashWidget.set_account_filter(account)
        self.tabs.setCurrentWidget(self.crashWidget)

    def _save_cloud_settings(self) -> None:
        self._save_all_settings()
        self._apply_cloud_to_crash_widget()
        QMessageBox.information(self, APP_NAME, 'Cloud settings saved.')

    def _test_cloud(self) -> None:
        ready = self._cloud_ready()
        if not ready:
            return
        url, secret = ready
        try:
            msg = test_connection(url, secret)
        except CloudApiError as exc:
            QMessageBox.warning(self, 'Test connection', str(exc))
            return
        self._save_all_settings()
        self._apply_cloud_to_crash_widget()
        QMessageBox.information(self, 'Test connection', msg)
