"""Queue window — shows all queued/running/completed jobs.

Opened via ⌘⇧Q from the main window.  It holds a shared
:class:`~m4bmaker.gui.queue_manager.QueueManager` instance and updates
its table in real time as jobs progress.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from m4bmaker.gui.job import Job, JobStatus
from m4bmaker.gui.queue_manager import QueueManager

# Column indices
_COL_TITLE = 0
_COL_STATUS = 1
_COL_PROGRESS = 2

_STATUS_LABELS = {
    JobStatus.QUEUED: "Queued",
    JobStatus.RUNNING: "Running",
    JobStatus.COMPLETED: "Done ✓",
    JobStatus.FAILED: "Failed ✗",
    JobStatus.CANCELLED: "Cancelled",
}


class QueueWindow(QMainWindow):
    """Secondary window showing the batch encode queue."""

    def __init__(self, queue_manager: QueueManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._qm = queue_manager
        self.setWindowTitle("Encode Queue")
        self.setMinimumSize(560, 320)
        self.resize(680, 400)

        self._build_ui()

        self._qm.job_updated.connect(self._on_job_updated)
        self._qm.queue_finished.connect(self._refresh_buttons)

        # Populate with any jobs already in the manager
        for job in self._qm.jobs:
            self._insert_row(job)
        self._refresh_buttons()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Table
        self._table = QTableWidget(0, 3)
        self._table.setObjectName("queueTable")
        self._table.setHorizontalHeaderLabels(["Title", "Status", "Progress"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 90)
        self._table.setColumnWidth(2, 160)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        layout.addWidget(self._table)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._start_btn = QPushButton("▶  Start Queue")
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch()

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(self._remove_btn)

        self._clear_btn = QPushButton("Clear Completed")
        self._clear_btn.clicked.connect(self._on_clear_completed)
        btn_row.addWidget(self._clear_btn)

        layout.addLayout(btn_row)

        # Status line
        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self._status_lbl)

    # ── table helpers ─────────────────────────────────────────────────────────

    def _row_for_job(self, job_id: str) -> int | None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_TITLE)
            if item and item.data(Qt.ItemDataRole.UserRole) == job_id:
                return row
        return None

    def _insert_row(self, job: Job) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        title_item = QTableWidgetItem(job.title)
        title_item.setData(Qt.ItemDataRole.UserRole, job.id)
        self._table.setItem(row, _COL_TITLE, title_item)

        status_item = QTableWidgetItem(_STATUS_LABELS.get(job.status, ""))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, _COL_STATUS, status_item)

        bar = QProgressBar()
        bar.setObjectName("jobProgress")
        bar.setRange(0, 100)
        bar.setValue(int(job.progress * 100))
        bar.setTextVisible(job.status == JobStatus.RUNNING)
        self._table.setCellWidget(row, _COL_PROGRESS, bar)
        self._table.setRowHeight(row, 28)

    def _update_row(self, row: int, job: Job) -> None:
        title_item = self._table.item(row, _COL_TITLE)
        if title_item:
            title_item.setText(job.title)

        status_item = self._table.item(row, _COL_STATUS)
        if status_item:
            status_item.setText(_STATUS_LABELS.get(job.status, ""))

        bar = self._table.cellWidget(row, _COL_PROGRESS)
        if isinstance(bar, QProgressBar):
            bar.setValue(int(job.progress * 100))
            bar.setTextVisible(job.status == JobStatus.RUNNING)
            if job.status == JobStatus.RUNNING and job.status_message:
                bar.setFormat(f"{int(job.progress * 100)}%")

    def _refresh_buttons(self) -> None:
        running = self._qm.is_running
        has_queued = bool(self._qm.pending_jobs)
        has_completed = bool(self._qm.completed_jobs)

        self._start_btn.setEnabled(has_queued and not running)
        self._stop_btn.setEnabled(running)
        self._clear_btn.setEnabled(has_completed)

        active = self._qm.active_jobs
        if active:
            self._status_lbl.setText(f"Encoding: {active[0].title}  {active[0].status_message}")
        elif running:
            self._status_lbl.setText("Processing…")
        else:
            total = len(self._qm.jobs)
            done = len(self._qm.completed_jobs)
            self._status_lbl.setText(f"{done}/{total} complete" if total else "")

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_job_updated(self, job_id: str) -> None:
        job = self._qm.get_job(job_id)
        if job is None:
            return
        row = self._row_for_job(job_id)
        if row is None:
            self._insert_row(job)
        else:
            self._update_row(row, job)
        self._refresh_buttons()

    def _on_start(self) -> None:
        self._qm.start()
        self._refresh_buttons()

    def _on_stop(self) -> None:
        self._qm.stop()
        self._refresh_buttons()

    def _on_remove(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        for index in sorted(rows, reverse=True):
            item = self._table.item(index.row(), _COL_TITLE)
            if item:
                job_id = item.data(Qt.ItemDataRole.UserRole)
                job = self._qm.get_job(job_id)
                if job and job.status != JobStatus.RUNNING:
                    self._qm.remove(job_id)
                    self._table.removeRow(index.row())
        self._refresh_buttons()

    def _on_clear_completed(self) -> None:
        self._qm.clear_completed()
        # Rebuild table from remaining jobs
        self._table.setRowCount(0)
        for job in self._qm.jobs:
            self._insert_row(job)
        self._refresh_buttons()

    # ── apply theme ───────────────────────────────────────────────────────────

    def apply_stylesheet(self, dark: bool) -> None:
        from m4bmaker.gui.styles import get_stylesheet
        self.setStyleSheet(get_stylesheet(dark))
