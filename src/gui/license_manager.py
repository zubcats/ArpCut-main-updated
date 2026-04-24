from datetime import timedelta

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from constants import APP_DISPLAY_NAME, PAID_LICENSE_MANAGER_UPDATE_URL
from tools.frameless_chrome import (
    FramelessResizableMixin,
    register_window_surface_effects,
    setup_frameless_main_window,
)
from tools.license_admin import (
    admin_public_verify_key_b64,
    cloud_kv_bundle_for_license_id,
    cloud_kv_key_for_account,
    create_license,
    delete_license,
    export_cloud_kv_bundle,
    list_license_rows,
    renew_license,
    set_license_status,
    signed_document_for_license_id,
)
from tools.license_cloud_sync import (
    delete_account_from_worker,
    load_cloud_sync_settings,
    push_account_to_worker,
    save_cloud_sync_settings,
    test_worker_reachable,
)
from tools.updater_core import download_installer, launch_installer


def _ask_new_sign_in_password(parent: QWidget) -> str | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle('Customer sign-in password')
    dlg.setModal(True)
    lay = QVBoxLayout(dlg)
    lay.addWidget(
        QLabel(
            'Choose the password this customer will type in ZubCut\n'
            '(min 8 characters). They use it with their account name when signing in online.',
            dlg,
        )
    )
    ed1 = QLineEdit(dlg)
    ed1.setEchoMode(QLineEdit.Password)
    ed2 = QLineEdit(dlg)
    ed2.setEchoMode(QLineEdit.Password)
    ed2.setPlaceholderText('Confirm password')
    lay.addWidget(ed1)
    lay.addWidget(ed2)
    row = QHBoxLayout()
    row.addStretch()
    cancel = QPushButton('Cancel', dlg)
    ok = QPushButton('OK', dlg)
    ok.setDefault(True)
    row.addWidget(cancel)
    row.addWidget(ok)
    lay.addLayout(row)
    chosen: list[str | None] = [None]

    def on_ok() -> None:
        a, b = ed1.text().strip(), ed2.text().strip()
        if len(a) < 8:
            QMessageBox.warning(dlg, 'Password', 'Use at least 8 characters.')
            return
        if a != b:
            QMessageBox.warning(dlg, 'Password', 'Passwords do not match.')
            return
        chosen[0] = a
        dlg.accept()

    ok.clicked.connect(on_ok)
    cancel.clicked.connect(dlg.reject)
    if dlg.exec_() != QDialog.Accepted:
        return None
    return chosen[0]


def _show_account_credentials(parent: QWidget, user: str) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle('Send to customer')
    dlg.setModal(True)
    v = QVBoxLayout(dlg)
    v.addWidget(
        QLabel(
            f'Give your customer:\n\n'
            f'• Account name: {user}\n'
            f'• Password: (the one you just chose)\n\n'
            f'They enter these in ZubCut (paid) sign-in after your build has the sign-in server URL set.',
            dlg,
        )
    )
    close = QPushButton('Close', dlg)
    close.clicked.connect(dlg.accept)
    v.addWidget(close)
    dlg.resize(520, 200)
    dlg.exec_()


def _human_remaining(seconds: int) -> str:
    if seconds < 0:
        return 'Expired'
    if seconds < 60:
        return f'{seconds}s'
    td = timedelta(seconds=seconds)
    days = td.days
    hours, rem = divmod(td.seconds, 3600)
    mins, _ = divmod(rem, 60)
    if days > 0:
        return f'{days}d {hours}h'
    if hours > 0:
        return f'{hours}h {mins}m'
    return f'{mins}m'


def _license_manager_qss() -> str:
    accent = '#316E69'
    panel = '#141414'
    field = '#2b2b2b'
    border = '#3d3d3d'
    hover = '#383838'
    press = '#323232'
    text = '#e8eaed'
    mute = '#9a9a9a'
    return f"""
QMainWindow#zubcutLicenseManager {{
    background-color: {panel};
}}
QMainWindow#zubcutLicenseManager QWidget {{
    color: {text};
    background-color: transparent;
}}
QMainWindow#zubcutLicenseManager QLabel {{
    color: {text};
}}
QMainWindow#zubcutLicenseManager QPushButton {{
    background-color: {field};
    color: {text};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 4px 10px;
    min-height: 22px;
}}
QMainWindow#zubcutLicenseManager QPushButton:hover {{
    background-color: {hover};
    border: 1px solid {hover};
}}
QMainWindow#zubcutLicenseManager QPushButton:pressed {{
    background-color: {press};
    border: 1px solid {press};
}}
QMainWindow#zubcutLicenseManager QTableWidget {{
    background-color: #000000;
    alternate-background-color: #0a0a0a;
    color: {text};
    gridline-color: #141414;
    border: 1px solid {border};
    selection-background-color: {accent};
    selection-color: #f2f2f2;
}}
QMainWindow#zubcutLicenseManager QHeaderView::section {{
    background-color: #000000;
    color: {mute};
    border: none;
    border-bottom: 1px solid #2a2a2a;
    border-right: 1px solid #141414;
    padding: 4px;
}}
QMainWindow#zubcutLicenseManager QGroupBox#cloudSyncGroup {{
    border: 1px solid {border};
    margin-top: 10px;
    padding-top: 6px;
    border-radius: 4px;
}}
QMainWindow#zubcutLicenseManager QGroupBox#cloudSyncGroup::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}}
"""


class LicenseManagerWindow(FramelessResizableMixin, QMainWindow):
    def __init__(self, icon):
        super().__init__()
        self.setObjectName('zubcutLicenseManager')
        self.setWindowTitle(f'{APP_DISPLAY_NAME} License Manager')
        self.setWindowIcon(icon)
        self.resize(980, 640)
        self._build_ui()
        self.setStyleSheet(_license_manager_qss())
        setup_frameless_main_window(self, self.windowTitle(), icon, maximizable=False)
        # Solid client like main ZubCut window — translucent frameless + mask can look like a second window on Windows.
        self._zubcut_use_translucent_surface = False
        register_window_surface_effects(self)
        self.refresh_rows()

    def _build_ui(self):
        root = QWidget(self)
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        self.lblKey = QLabel(self)
        self.lblKey.setText(f'Public Verify Key (put this in ZubCut paid constants): {admin_public_verify_key_b64()}')
        self.lblKey.setWordWrap(True)
        lay.addWidget(self.lblKey)

        cloud = QGroupBox('Cloud sign-in sync (optional)', self)
        cloud.setObjectName('cloudSyncGroup')
        cloud_lay = QVBoxLayout(cloud)
        cloud_lay.setSpacing(6)
        cloud_lay.addWidget(
            QLabel(
                'Link License Manager to your Cloudflare Worker: new accounts and changes '
                'can push automatically so customers only need account name + password in ZubCut.',
                self,
            )
        )
        row_url = QHBoxLayout()
        row_url.addWidget(QLabel('Worker base URL:', self))
        self.edtCloudUrl = QLineEdit(self)
        self.edtCloudUrl.setPlaceholderText('https://your-worker.workers.dev')
        row_url.addWidget(self.edtCloudUrl, 1)
        cloud_lay.addLayout(row_url)
        row_sec = QHBoxLayout()
        row_sec.addWidget(QLabel('Admin secret:', self))
        self.edtCloudSecret = QLineEdit(self)
        self.edtCloudSecret.setEchoMode(QLineEdit.Password)
        self.edtCloudSecret.setPlaceholderText('Same as wrangler secret ADMIN_SECRET')
        row_sec.addWidget(self.edtCloudSecret, 1)
        cloud_lay.addLayout(row_sec)
        self.chkCloudAuto = QCheckBox(
            'After I create, renew, or change account status, push to cloud automatically',
            self,
        )
        self.chkCloudAuto.setChecked(True)
        cloud_lay.addWidget(self.chkCloudAuto)
        cloud_btns = QHBoxLayout()
        self.btnCloudSave = QPushButton('Save cloud settings', self)
        self.btnCloudTest = QPushButton('Test connection', self)
        self.btnPushCloud = QPushButton('Push selected to cloud', self)
        cloud_btns.addWidget(self.btnCloudSave)
        cloud_btns.addWidget(self.btnCloudTest)
        cloud_btns.addWidget(self.btnPushCloud)
        cloud_btns.addStretch()
        cloud_lay.addLayout(cloud_btns)
        lay.addWidget(cloud)

        btn_row = QHBoxLayout()
        self.btnRefresh = QPushButton('Refresh', self)
        self.btnCreate = QPushButton('Create Account', self)
        self.btnRenew = QPushButton('Renew Selected', self)
        self.btnRevoke = QPushButton('Revoke Selected', self)
        self.btnActivate = QPushButton('Activate Selected', self)
        self.btnDelete = QPushButton('Delete account', self)
        self.btnExportKv = QPushButton('Export KV file (manual)', self)
        self.btnUpdateManager = QPushButton('Install Latest Manager Build', self)
        for b in (
            self.btnRefresh,
            self.btnCreate,
            self.btnRenew,
            self.btnRevoke,
            self.btnActivate,
            self.btnDelete,
            self.btnExportKv,
            self.btnUpdateManager,
        ):
            b.setAutoDefault(False)
            b.setDefault(False)
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self.table = QTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ['User', 'License ID', 'Status', 'Expires (UTC)', 'Time Left', 'Device Bound']
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(self.table.SelectRows)
        self.table.setSelectionMode(self.table.SingleSelection)
        self.table.setEditTriggers(self.table.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        lay.addWidget(self.table)

        self.lblSummary = QLabel(self)
        lay.addWidget(self.lblSummary)

        self.btnRefresh.clicked.connect(self.refresh_rows)
        self.btnCreate.clicked.connect(self.create_account)
        self.btnRenew.clicked.connect(self.renew_selected)
        self.btnRevoke.clicked.connect(lambda: self.set_selected_status('revoked'))
        self.btnActivate.clicked.connect(lambda: self.set_selected_status('active'))
        self.btnDelete.clicked.connect(self.delete_selected_account)
        self.btnExportKv.clicked.connect(self.export_kv_bundle_selected)
        self.btnUpdateManager.clicked.connect(self.install_latest_manager_build)

        self.btnCloudSave.clicked.connect(self._save_cloud_sync_clicked)
        self.btnCloudTest.clicked.connect(self._test_cloud_sync_clicked)
        self.btnPushCloud.clicked.connect(self.push_cloud_selected)

        self._load_cloud_sync_fields()

    def _load_cloud_sync_fields(self) -> None:
        s = load_cloud_sync_settings()
        self.edtCloudUrl.setText(str(s.get('worker_base_url') or ''))
        self.edtCloudSecret.setText(str(s.get('admin_secret') or ''))
        self.chkCloudAuto.setChecked(bool(s.get('auto_sync', True)))

    def _save_cloud_sync_clicked(self) -> None:
        save_cloud_sync_settings(
            worker_base_url=self.edtCloudUrl.text(),
            admin_secret=self.edtCloudSecret.text(),
            auto_sync=self.chkCloudAuto.isChecked(),
        )
        QMessageBox.information(self, 'Saved', 'Cloud sync settings saved.')

    def _test_cloud_sync_clicked(self) -> None:
        ok, msg = test_worker_reachable(self.edtCloudUrl.text())
        if ok:
            QMessageBox.information(self, 'Test', msg)
        else:
            QMessageBox.warning(self, 'Test failed', msg)

    def _maybe_auto_push_cloud(self, license_id: str) -> tuple[bool, str]:
        s = load_cloud_sync_settings()
        if not s.get('auto_sync'):
            return True, ''
        base = str(s.get('worker_base_url') or '').strip()
        secret = str(s.get('admin_secret') or '')
        if not base or not secret:
            return (
                False,
                'Cloud auto-sync is on but Worker URL or admin secret is empty. '
                'Fill them and click Save cloud settings, or turn off auto-sync.',
            )
        return push_account_to_worker(license_id)

    def push_cloud_selected(self) -> None:
        lic_id = self._selected_license_id()
        if not lic_id:
            QMessageBox.warning(self, 'Cloud', 'Select an account first.')
            return
        ok, msg = push_account_to_worker(lic_id)
        if ok:
            QMessageBox.information(self, 'Cloud', msg)
        else:
            QMessageBox.warning(self, 'Cloud', msg)

    def _selected_license_id(self) -> str | None:
        items = self.table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        id_item = self.table.item(row, 1)
        return id_item.text().strip() if id_item else None

    def _selected_user_display(self) -> str:
        items = self.table.selectedItems()
        if not items:
            return ''
        row = items[0].row()
        u = self.table.item(row, 0)
        return u.text().strip() if u else ''

    def delete_selected_account(self) -> None:
        lic_id = self._selected_license_id()
        if not lic_id:
            QMessageBox.warning(self, 'Delete account', 'Select an account first.')
            return
        user = self._selected_user_display()
        confirm = QMessageBox.question(
            self,
            'Delete account',
            f'Delete this account permanently from License Manager?\n\n'
            f'User: {user}\nLicense ID: {lic_id}\n\n'
            f'This cannot be undone.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        doc = signed_document_for_license_id(lic_id)
        p = (doc or {}).get('payload') or {}
        account_key = cloud_kv_key_for_account(str(p.get('user_name') or ''))

        if not delete_license(lic_id):
            QMessageBox.warning(self, 'Delete account', 'Could not delete that account.')
            return

        self.refresh_rows()

        cloud_ok, cloud_msg = delete_account_from_worker(account_key)
        if not cloud_ok:
            QMessageBox.warning(
                self,
                'Delete account',
                f'Account removed locally, but cloud removal failed:\n{cloud_msg}',
            )
            return
        msg = 'Account deleted.'
        if cloud_msg:
            msg = f'{msg}\n\n{cloud_msg}'
        QMessageBox.information(self, 'Delete account', msg)

    def refresh_rows(self):
        rows = list_license_rows()
        self.table.setRowCount(len(rows))
        active = 0
        for r, row in enumerate(rows):
            status = row['status']
            if status == 'active' and row['remaining_sec'] >= 0:
                active += 1
            vals = [
                row['user_name'],
                row['license_id'],
                status,
                row['expires_at'],
                _human_remaining(int(row['remaining_sec'])),
                'Yes' if row['device_hash'] else 'No',
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignCenter)
                if status != 'active' or row['remaining_sec'] < 0:
                    item.setForeground(Qt.gray)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.lblSummary.setText(f'Accounts: {len(rows)} total / {active} active')

    def create_account(self):
        user, ok = QInputDialog.getText(self, 'Create Account', 'User name:')
        if not ok:
            return
        user = str(user).strip()
        if not user:
            QMessageBox.warning(self, 'Create Account', 'User name is required.')
            return
        days, ok = QInputDialog.getInt(self, 'Create Account', 'Duration in days:', 30, 1, 36500, 1)
        if not ok:
            return
        dev_hash, ok = QInputDialog.getText(
            self,
            'Create Account',
            'Optional device hash (leave blank for non-bound license):',
        )
        if not ok:
            return
        pwd = _ask_new_sign_in_password(self)
        if pwd is None:
            return
        rec = create_license(user, days, str(dev_hash or '').strip(), sign_in_password=pwd)
        self.refresh_rows()
        lic_id = str(rec.get('payload', {}).get('license_id') or '')
        _show_account_credentials(self, user)
        ok, msg = self._maybe_auto_push_cloud(lic_id)
        if not ok:
            QMessageBox.warning(self, 'Cloud sync', msg)

    def renew_selected(self):
        lic_id = self._selected_license_id()
        if not lic_id:
            QMessageBox.warning(self, 'Renew', 'Select an account first.')
            return
        days, ok = QInputDialog.getInt(self, 'Renew Account', 'Extend by days:', 30, 1, 36500, 1)
        if not ok:
            return
        rec = renew_license(lic_id, days)
        if not rec:
            QMessageBox.warning(self, 'Renew', 'Could not renew selected account.')
            return
        self.refresh_rows()
        QMessageBox.information(self, 'Renew', 'Account renewed.')
        ok, msg = self._maybe_auto_push_cloud(lic_id)
        if not ok:
            QMessageBox.warning(self, 'Cloud sync', msg)

    def set_selected_status(self, status: str):
        lic_id = self._selected_license_id()
        if not lic_id:
            QMessageBox.warning(self, 'Update Status', 'Select an account first.')
            return
        rec = set_license_status(lic_id, status)
        if not rec:
            QMessageBox.warning(self, 'Update Status', 'Could not update selected account.')
            return
        self.refresh_rows()
        QMessageBox.information(self, 'Update Status', f'Account status set to {status}.')
        ok, msg = self._maybe_auto_push_cloud(lic_id)
        if not ok:
            QMessageBox.warning(self, 'Cloud sync', msg)

    def export_kv_bundle_selected(self):
        lic_id = self._selected_license_id()
        if not lic_id:
            QMessageBox.warning(self, 'Export KV bundle', 'Select an account first.')
            return
        bundle = cloud_kv_bundle_for_license_id(lic_id)
        if bundle is None:
            QMessageBox.warning(
                self,
                'Export KV bundle',
                'Only accounts with a customer sign-in password can export an online bundle.\n'
                'Create the account with a password, or see backend/cloudflare-license-signin/README.md.',
            )
            return
        doc = signed_document_for_license_id(lic_id)
        p = (doc or {}).get('payload') or {}
        user = str(p.get('user_name') or '')
        kv_key = cloud_kv_key_for_account(user)
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            'Export Cloudflare KV bundle',
            f'kv-{kv_key or lic_id[:8]}.json',
            'JSON Files (*.json)',
        )
        if not out_path:
            return
        if not export_cloud_kv_bundle(lic_id, out_path):
            QMessageBox.warning(self, 'Export KV bundle', 'Could not write that file.')
            return
        QMessageBox.information(
            self,
            'KV bundle exported',
            f'Wrote:\n{out_path}\n\n'
            f'Workers KV key (case-insensitive account name):\n  {kv_key!r}\n\n'
            f'Deploy steps: backend/cloudflare-license-signin/README.md',
        )

    def install_latest_manager_build(self):
        url = str(PAID_LICENSE_MANAGER_UPDATE_URL or '').strip()
        if not url:
            QMessageBox.warning(self, 'Update URL Missing', 'Manager update URL is not configured.')
            return
        confirm = QMessageBox.question(
            self,
            'Install Latest Manager Build',
            (
                'This will download and run the latest ZubCut License Manager installer.\n'
                'Continue?'
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            path = download_installer(url)
            launch_installer(path)
            app = QApplication.instance()
            if app is not None:
                app.quit()
        except Exception as e:
            QMessageBox.critical(
                self,
                'Update Failed',
                f'Could not download/install manager update.\n{e}',
            )
        finally:
            QApplication.restoreOverrideCursor()

