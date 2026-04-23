from datetime import timedelta

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from constants import APP_DISPLAY_NAME, PAID_LICENSE_MANAGER_UPDATE_URL
from tools.license_admin import (
    admin_public_verify_key_b64,
    create_license,
    export_license_document,
    list_license_rows,
    renew_license,
    set_license_status,
)
from tools.updater_core import launch_installer
from tools.updater_progress import download_update_with_progress_dialog


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


class LicenseManagerWindow(QMainWindow):
    def __init__(self, icon):
        super().__init__()
        self.setWindowTitle(f'{APP_DISPLAY_NAME} License Manager')
        self.setWindowIcon(icon)
        self.resize(980, 560)
        self._build_ui()
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

        btn_row = QHBoxLayout()
        self.btnRefresh = QPushButton('Refresh', self)
        self.btnCreate = QPushButton('Create Account', self)
        self.btnRenew = QPushButton('Renew Selected', self)
        self.btnRevoke = QPushButton('Revoke Selected', self)
        self.btnActivate = QPushButton('Activate Selected', self)
        self.btnExport = QPushButton('Export License File', self)
        self.btnUpdateManager = QPushButton('Install Latest Manager Build', self)
        for b in (
            self.btnRefresh,
            self.btnCreate,
            self.btnRenew,
            self.btnRevoke,
            self.btnActivate,
            self.btnExport,
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
        lay.addWidget(self.table)

        self.lblSummary = QLabel(self)
        lay.addWidget(self.lblSummary)

        self.btnRefresh.clicked.connect(self.refresh_rows)
        self.btnCreate.clicked.connect(self.create_account)
        self.btnRenew.clicked.connect(self.renew_selected)
        self.btnRevoke.clicked.connect(lambda: self.set_selected_status('revoked'))
        self.btnActivate.clicked.connect(lambda: self.set_selected_status('active'))
        self.btnExport.clicked.connect(self.export_selected)
        self.btnUpdateManager.clicked.connect(self.install_latest_manager_build)

    def _selected_license_id(self) -> str | None:
        items = self.table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        id_item = self.table.item(row, 1)
        return id_item.text().strip() if id_item else None

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
        rec = create_license(user, days, str(dev_hash or '').strip())
        self.refresh_rows()
        out = export_license_document(rec['payload']['license_id'])
        QMessageBox.information(
            self,
            'Create Account',
            f"Created account '{user}'.\nLicense exported to:\n{out}",
        )

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

    def export_selected(self):
        lic_id = self._selected_license_id()
        if not lic_id:
            QMessageBox.warning(self, 'Export License', 'Select an account first.')
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            'Export License File',
            f'{lic_id[:8]}.json',
            'JSON Files (*.json)',
        )
        if not out_path:
            return
        wrote = export_license_document(lic_id, out_path)
        if not wrote:
            QMessageBox.warning(self, 'Export License', 'Could not export selected account.')
            return
        QMessageBox.information(self, 'Export License', f'License exported:\n{wrote}')

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
            path = download_update_with_progress_dialog(self, url)
            if not path:
                return
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

