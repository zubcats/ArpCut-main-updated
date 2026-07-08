from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from license_manager.cloud_api import CloudApiError, delete_crash, get_crash, list_crashes


class CrashReportsWidget(QWidget):
    """Crash reports from ZubCut users (worker KV index)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker_url = ''
        self._admin_secret = ''
        self._rows: list[dict] = []
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self.refresh)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        self.lblStatus = QLabel('Configure Cloud sign-in sync to load crash reports.', self)
        header.addWidget(self.lblStatus, 1)
        self.chkAutoRefresh = QPushButton('Auto-refresh: Off', self)
        self.chkAutoRefresh.setCheckable(True)
        self.chkAutoRefresh.clicked.connect(self._toggle_auto_refresh)
        header.addWidget(self.chkAutoRefresh)
        self.btnRefresh = QPushButton('Refresh', self)
        self.btnRefresh.clicked.connect(self.refresh)
        header.addWidget(self.btnRefresh)
        root.addLayout(header)

        splitter = QSplitter(Qt.Vertical, self)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ['Ref', 'Received', 'Account', 'Build', 'Exception', 'Message']
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self._load_selected_body())
        splitter.addWidget(self.table)

        detail_box = QGroupBox('Report body', self)
        detail_layout = QVBoxLayout(detail_box)
        self.txtBody = QTextEdit(detail_box)
        self.txtBody.setReadOnly(True)
        self.txtBody.setPlaceholderText('Select a crash report to view the full log…')
        self.txtBody.setFontFamily('Consolas')
        detail_layout.addWidget(self.txtBody)

        btn_row = QHBoxLayout()
        self.btnView = QPushButton('View full report', detail_box)
        self.btnView.clicked.connect(self._load_selected_body)
        self.btnExport = QPushButton('Export body…', detail_box)
        self.btnExport.clicked.connect(self._export_body)
        self.btnDelete = QPushButton('Delete report', detail_box)
        self.btnDelete.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.btnView)
        btn_row.addWidget(self.btnExport)
        btn_row.addStretch()
        btn_row.addWidget(self.btnDelete)
        detail_layout.addLayout(btn_row)
        splitter.addWidget(detail_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter)

        self._set_actions_enabled(False)

    def configure(self, worker_url: str, admin_secret: str) -> None:
        self._worker_url = str(worker_url or '').strip()
        self._admin_secret = str(admin_secret or '').strip()
        ready = bool(self._worker_url and self._admin_secret)
        self.btnRefresh.setEnabled(ready)
        self.chkAutoRefresh.setEnabled(ready)
        if ready:
            self.lblStatus.setText(f'Worker: {self._worker_url}')
        else:
            self.lblStatus.setText('Set Worker URL and Admin secret on the Cloud tab, then Save.')
            self._auto_timer.stop()
            self.chkAutoRefresh.setChecked(False)
            self.chkAutoRefresh.setText('Auto-refresh: Off')

    def refresh(self) -> None:
        if not self._worker_url or not self._admin_secret:
            return
        try:
            self._rows = list_crashes(self._worker_url, self._admin_secret, limit=200)
        except CloudApiError as exc:
            self.lblStatus.setText(str(exc))
            QMessageBox.warning(self, 'Crash reports', str(exc))
            return
        self._populate_table()
        self.lblStatus.setText(f'{len(self._rows)} crash report(s) — Worker: {self._worker_url}')

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        for row in self._rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            ref = str(row.get('ref') or '')
            received = str(row.get('received_at') or row.get('time_utc') or '')
            account = str(row.get('account_hint') or '')
            build = ' '.join(
                p
                for p in (
                    str(row.get('build_channel') or ''),
                    str(row.get('build_commit') or '')[:12],
                    str(row.get('app_version') or ''),
                )
                if p
            )
            exc_type = str(row.get('exc_type') or '')
            message = str(row.get('exc_message') or '')
            for col, text in enumerate((ref, received, account, build, exc_type, message)):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.UserRole, ref)
                self.table.setItem(r, col, item)
        if self._rows:
            self.table.selectRow(0)
        else:
            self.txtBody.clear()
            self._set_actions_enabled(False)

    def _selected_ref(self) -> str:
        items = self.table.selectedItems()
        if not items:
            return ''
        item = self.table.item(items[0].row(), 0)
        return str(item.data(Qt.UserRole) or item.text() if item else '')

    def _on_selection_changed(self) -> None:
        ref = self._selected_ref()
        self._set_actions_enabled(bool(ref))
        if not ref:
            self.txtBody.clear()
            return
        summary = next((r for r in self._rows if r.get('ref') == ref), None)
        if summary:
            lines = [
                f'ref={summary.get("ref")}',
                f'received_at={summary.get("received_at")}',
                f'account_hint={summary.get("account_hint")}',
                f'platform={summary.get("platform")}',
                f'exc={summary.get("exc_type")}: {summary.get("exc_message")}',
                '',
                '(double-click or View full report to load body)',
            ]
            self.txtBody.setPlainText('\n'.join(lines))

    def _load_selected_body(self) -> None:
        ref = self._selected_ref()
        if not ref:
            return
        try:
            report = get_crash(self._worker_url, self._admin_secret, ref)
        except CloudApiError as exc:
            QMessageBox.warning(self, 'Crash report', str(exc))
            return
        body = str(report.get('body') or '')
        head = [
            f'ref={report.get("ref")}',
            f'received_at={report.get("received_at")}',
            f'account_hint={report.get("account_hint")}',
            f'platform={report.get("platform")}',
            f'build={report.get("build_channel")} {report.get("build_commit")} {report.get("app_version")}',
            f'exc={report.get("exc_type")}: {report.get("exc_message")}',
            '',
        ]
        self.txtBody.setPlainText('\n'.join(head) + body)

    def _export_body(self) -> None:
        ref = self._selected_ref()
        if not ref:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            'Export crash report',
            f'{ref}.log',
            'Log files (*.log);;Text files (*.txt);;All files (*)',
        )
        if not path:
            return
        try:
            report = get_crash(self._worker_url, self._admin_secret, ref)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(str(report.get('body') or ''))
            QMessageBox.information(self, 'Export', f'Saved to:\n{path}')
        except (CloudApiError, OSError) as exc:
            QMessageBox.warning(self, 'Export', str(exc))

    def _delete_selected(self) -> None:
        ref = self._selected_ref()
        if not ref:
            return
        if (
            QMessageBox.question(
                self,
                'Delete crash report',
                f'Delete crash report {ref} from the server?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        try:
            delete_crash(self._worker_url, self._admin_secret, ref)
        except CloudApiError as exc:
            QMessageBox.warning(self, 'Delete', str(exc))
            return
        self.refresh()

    def _toggle_auto_refresh(self, checked: bool) -> None:
        if checked:
            self.chkAutoRefresh.setText('Auto-refresh: On (60s)')
            self._auto_timer.start(60_000)
            self.refresh()
        else:
            self.chkAutoRefresh.setText('Auto-refresh: Off')
            self._auto_timer.stop()

    def _set_actions_enabled(self, enabled: bool) -> None:
        self.btnView.setEnabled(enabled)
        self.btnExport.setEnabled(enabled)
        self.btnDelete.setEnabled(enabled)
