"""Tests for QueueWindow (requires qapp fixture)."""

from __future__ import annotations

from pathlib import Path

import pytest

from m4bmaker.gui.job import Job, JobStatus, job_from_book
from m4bmaker.gui.queue_manager import QueueManager
from m4bmaker.gui.queue_window import QueueWindow, _COL_STATUS, _COL_TITLE
from m4bmaker.models import Book, BookMetadata
from PySide6.QtCore import Qt


def _job(title: str = "Book") -> Job:
    book = Book(
        files=[Path("/a.mp3")],
        chapters=[],
        metadata=BookMetadata(title=title),
    )
    return job_from_book(book, Path(f"/out/{title}.m4b"))


@pytest.fixture()
def qm(qapp):
    return QueueManager()


@pytest.fixture()
def win(qm):
    w = QueueWindow(qm)
    return w


# ── construction ──────────────────────────────────────────────────────────────


def test_window_creates_without_error(win):
    assert win is not None


def test_table_starts_empty(win):
    assert win._table.rowCount() == 0


def test_start_btn_disabled_when_empty(win):
    assert not win._start_btn.isEnabled()


def test_stop_btn_disabled_when_not_running(win):
    assert not win._stop_btn.isEnabled()


# ── row management ────────────────────────────────────────────────────────────


def test_add_job_to_manager_inserts_row(qm):
    win = QueueWindow(qm)
    j = _job("Dune")
    qm.add(j)
    assert win._table.rowCount() == 1


def test_row_shows_correct_title(qm):
    win = QueueWindow(qm)
    j = _job("Foundation")
    qm.add(j)
    item = win._table.item(0, _COL_TITLE)
    assert item is not None
    assert item.text() == "Foundation"


def test_row_shows_queued_status(qm):
    win = QueueWindow(qm)
    j = _job("X")
    qm.add(j)
    status_item = win._table.item(0, _COL_STATUS)
    assert status_item is not None
    assert "Queued" in status_item.text()


def test_start_btn_enabled_after_job_added(qm):
    win = QueueWindow(qm)
    qm.add(_job("A"))
    assert win._start_btn.isEnabled()


def test_pre_existing_jobs_shown_on_open(qapp):
    qm = QueueManager()
    qm.add(_job("Pre1"))
    qm.add(_job("Pre2"))
    win = QueueWindow(qm)
    assert win._table.rowCount() == 2


# ── clear completed ───────────────────────────────────────────────────────────


def test_clear_completed_removes_done_rows(qm):
    win = QueueWindow(qm)
    j1 = _job("done")
    j1.status = JobStatus.COMPLETED
    j2 = _job("waiting")
    qm._jobs = [j1, j2]
    # Manually insert rows for the test
    win._table.setRowCount(0)
    win._insert_row(j1)
    win._insert_row(j2)
    win._on_clear_completed()
    assert win._table.rowCount() == 1


# ── remove job ────────────────────────────────────────────────────────────────


def test_remove_queued_job_removes_row(qm):
    win = QueueWindow(qm)
    j = _job("removable")
    qm.add(j)
    # Select row 0
    win._table.selectRow(0)
    win._on_remove()
    assert win._table.rowCount() == 0
    assert qm.get_job(j.id) is None


def test_remove_running_job_not_removed(qm):
    win = QueueWindow(qm)
    j = _job("running")
    j.status = JobStatus.RUNNING
    qm._jobs = [j]
    win._insert_row(j)
    win._table.selectRow(0)
    win._on_remove()
    # Running jobs must not be removed
    assert win._table.rowCount() == 1


# ── job_updated signal ────────────────────────────────────────────────────────


def test_status_updates_on_job_updated_signal(qm):
    win = QueueWindow(qm)
    j = _job("updating")
    qm.add(j)
    # Simulate transition to RUNNING
    j.status = JobStatus.RUNNING
    j.progress = 0.5
    qm.job_updated.emit(j.id)
    status_item = win._table.item(0, _COL_STATUS)
    assert status_item is not None
    assert "Running" in status_item.text()
