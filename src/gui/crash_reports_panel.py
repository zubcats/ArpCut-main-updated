"""Crash reports tab for ZubCut Control Panel."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tools.control_panel_crashes import CrashApiError, delete_crash_report, get_crash_report, list_crash_reports

_FILTER_ALL = ''
_FILTER_UNKNOWN = '__unknown__'


class CrashReportsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._known_accounts: list[str] = []
        self._account_filter = _FILTER_ALL
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self.refresh)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.lblStatus = QLabel('Save cloud settings on the Accounts tab, then Refresh.', self)
        self.lblStatus.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lblStatus.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header.addWidget(self.lblStatus, 1)
        header.addWidget(QLabel('Account:', self))
        self.cmbAccount = QComboBox(self)
        self.cmbAccount.setMinimumWidth(180)
        self.cmbAccount.currentIndexChanged.connect(self._on_filter_changed)
        header.addWidget(self.cmbAccount)
        self.chkAutoRefresh = QPushButton('Auto-refresh: Off', self)
        self.chkAutoRefresh.setCheckable(True)
        self.chkAutoRefresh.clicked.connect(self._toggle_auto_refresh)
        header.addWidget(self.chkAutoRefresh)
        self.btnRefresh = QPushButton('Refresh', self)
        self.btnRefresh.clicked.connect(self.refresh)
        header.addWidget(self.btnRefresh)
        self.btnZcLegend = QPushButton('ZC code legend', self)
        self.btnZcLegend.setToolTip(
            'Show all diagnostic ZC-* support codes (separate from crash refs).'
        )
        self.btnZcLegend.clicked.connect(self._show_zc_legend)
        header.addWidget(self.btnZcLegend)
        root.addLayout(header)

        splitter = QSplitter(Qt.Vertical, self)
        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ['Ref', 'Received', 'Account', 'Build', 'ZC codes', 'Exception', 'Message']
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        for col in range(6):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self._load_selected_body())
        splitter.addWidget(self.table)

        detail = QGroupBox('Report body', self)
        detail_lay = QVBoxLayout(detail)
        self.txtBody = QTextEdit(detail)
        self.txtBody.setReadOnly(True)
        self.txtBody.setFontFamily('Consolas')
        detail_lay.addWidget(self.txtBody)
        btn_row = QHBoxLayout()
        self.btnView = QPushButton('View full report', detail)
        self.btnView.clicked.connect(self._load_selected_body)
        self.btnExport = QPushButton('Export body…', detail)
        self.btnExport.clicked.connect(self._export_body)
        self.btnDelete = QPushButton('Delete report', detail)
        self.btnDelete.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.btnView)
        btn_row.addWidget(self.btnExport)
        btn_row.addStretch()
        btn_row.addWidget(self.btnDelete)
        detail_lay.addLayout(btn_row)
        splitter.addWidget(detail)
        root.addWidget(splitter)
        self._set_actions_enabled(False)
        self._rebuild_filter_combo()

    def set_known_accounts(self, accounts: list[str]) -> None:
        self._known_accounts = [str(a or '').strip().lower() for a in accounts if str(a or '').strip()]
        self._rebuild_filter_combo()

    def set_account_filter(self, account: str) -> None:
        self._account_filter = str(account or '').strip().lower() or _FILTER_ALL
        self._sync_filter_combo_selection()
        self._populate_table()
        self._update_status_label()

    def refresh(self) -> None:
        try:
            self._rows = list_crash_reports(limit=200)
        except CrashApiError as exc:
            self._set_status_label('Refresh failed. See details in the popup.', str(exc))
            QMessageBox.warning(self, 'Crash reports', str(exc))
            return
        self._rebuild_filter_combo()
        self._populate_table()
        self._update_status_label()

    def _show_zc_legend(self) -> None:
        """Local registry of diagnostic codes — always available even for old reports."""
        try:
            from tools.user_errors import zc_code_catalog

            rows = zc_code_catalog()
        except Exception as exc:
            QMessageBox.warning(self, 'ZC codes', str(exc))
            return
        lines = [
            'Diagnostic support codes (not crash refs like ZC-ABC123):',
            '',
        ]
        for row in rows:
            lines.append(f"{row.get('code')}: {row.get('message')}")
        # Prefer the detail pane so we don't need a giant modal.
        self.txtBody.setPlainText('\n'.join(lines))
        self._set_status_label(f'{len(rows)} ZC codes in registry')

    def _filtered_rows(self) -> list[dict]:
        if self._account_filter == _FILTER_ALL:
            return list(self._rows)
        if self._account_filter == _FILTER_UNKNOWN:
            return [r for r in self._rows if not str(r.get('account_hint') or '').strip()]
        return [
            r
            for r in self._rows
            if str(r.get('account_hint') or '').lower() == self._account_filter
        ]

    def _rebuild_filter_combo(self) -> None:
        current = self._account_filter
        accounts = set(self._known_accounts)
        has_unknown = False
        for row in self._rows:
            acct = str(row.get('account_hint') or '').strip().lower()
            if acct:
                accounts.add(acct)
            else:
                has_unknown = True
        self.cmbAccount.blockSignals(True)
        self.cmbAccount.clear()
        self.cmbAccount.addItem('All accounts', _FILTER_ALL)
        for acct in sorted(accounts):
            count = sum(1 for r in self._rows if str(r.get('account_hint') or '').lower() == acct)
            self.cmbAccount.addItem(f'{acct} ({count})', acct)
        if has_unknown:
            unknown_count = sum(1 for r in self._rows if not str(r.get('account_hint') or '').strip())
            self.cmbAccount.addItem(f'(not signed in) ({unknown_count})', _FILTER_UNKNOWN)
        self._account_filter = current
        self._sync_filter_combo_selection()
        self.cmbAccount.blockSignals(False)

    def _sync_filter_combo_selection(self) -> None:
        idx = self.cmbAccount.findData(self._account_filter)
        if idx < 0:
            self._account_filter = _FILTER_ALL
            idx = 0
        self.cmbAccount.setCurrentIndex(idx)

    def _on_filter_changed(self, _index: int) -> None:
        data = self.cmbAccount.currentData()
        self._account_filter = str(data) if data is not None else _FILTER_ALL
        self._populate_table()
        self._update_status_label()

    def _update_status_label(self) -> None:
        visible = len(self._filtered_rows())
        total = len(self._rows)
        msg = f'{visible} shown' + (f' of {total} total' if visible != total else '')
        self._set_status_label(msg)

    def _set_status_label(self, text: str, detail: str = '') -> None:
        self.lblStatus.setText(str(text or ''))
        self.lblStatus.setToolTip(str(detail or ''))

    def _populate_table(self) -> None:
        rows = self._filtered_rows()
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            ref = str(row.get('ref') or '')
            received = str(row.get('received_at') or row.get('time_utc') or '')
            account = str(row.get('account_hint') or '') or '(not signed in)'
            build = ' '.join(
                p
                for p in (
                    str(row.get('build_channel') or ''),
                    str(row.get('build_commit') or '')[:12],
                    str(row.get('app_version') or ''),
                )
                if p
            )
            zc_raw = row.get('zc_codes') or []
            if isinstance(zc_raw, list):
                zc_codes = ', '.join(
                    str(c.get('code') if isinstance(c, dict) else c)
                    for c in zc_raw
                    if c
                )
            else:
                zc_codes = str(zc_raw or '')
            exc_type = str(row.get('exc_type') or '')
            message = str(row.get('exc_message') or '')
            for col, text in enumerate(
                (ref, received, account, build, zc_codes, exc_type, message)
            ):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.UserRole, ref)
                self.table.setItem(r, col, item)
        if rows:
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
            zc = summary.get('zc_codes') or []
            if isinstance(zc, list):
                zc_txt = ', '.join(
                    str(c.get('code') if isinstance(c, dict) else c) for c in zc if c
                ) or '—'
            else:
                zc_txt = str(zc or '—')
            self.txtBody.setPlainText(
                '\n'.join(
                    [
                        f'ref={summary.get("ref")}',
                        f'account={summary.get("account_hint") or "(not signed in)"}',
                        f'license_id={summary.get("license_id") or "—"}',
                        f'zc_codes={zc_txt}',
                        f'exc={summary.get("exc_type")}: {summary.get("exc_message")}',
                        '',
                        '(double-click to load full body)',
                    ]
                )
            )

    def _load_selected_body(self) -> None:
        ref = self._selected_ref()
        if not ref:
            return
        try:
            report = get_crash_report(ref)
        except CrashApiError as exc:
            QMessageBox.warning(self, 'Crash report', str(exc))
            return
        zc_lines = []
        for c in report.get('zc_codes') or []:
            if not isinstance(c, dict):
                continue
            code = str(c.get('code') or '')
            if not code:
                continue
            level = str(c.get('level') or '')
            msg = str(c.get('message') or '')
            bit = f'{code}' + (f' ({level})' if level else '')
            if msg:
                bit = f'{bit}: {msg}'
            zc_lines.append(bit)
        head = [
            f'ref={report.get("ref")}',
            f'account={report.get("account_hint") or "(not signed in)"}',
            f'license_id={report.get("license_id") or "—"}',
            f'build={report.get("build_channel")} {report.get("build_commit")}',
            'zc_codes:',
            *(f'  {line}' for line in (zc_lines or ['(none observed)'])),
            '',
        ]
        self.txtBody.setPlainText('\n'.join(head) + str(report.get('body') or ''))

    def _export_body(self) -> None:
        ref = self._selected_ref()
        if not ref:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export crash report', f'{ref}.log')
        if not path:
            return
        try:
            report = get_crash_report(ref)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(str(report.get('body') or ''))
            QMessageBox.information(self, 'Export', f'Saved to:\n{path}')
        except (CrashApiError, OSError) as exc:
            QMessageBox.warning(self, 'Export', str(exc))

    def _delete_selected(self) -> None:
        ref = self._selected_ref()
        if not ref:
            return
        if QMessageBox.question(self, 'Delete', f'Delete {ref}?', QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            delete_crash_report(ref)
        except CrashApiError as exc:
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
