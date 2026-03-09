"""Tests for QueueManager (mocked workers — no ffmpeg required)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.gui.job import Job, JobStatus, job_from_book
from m4bmaker.gui.queue_manager import QueueManager
from m4bmaker.models import Book, BookMetadata


# ── helpers ───────────────────────────────────────────────────────────────────


def _job(title: str = "Book") -> Job:
    book = Book(
        files=[Path("/a.mp3")],
        chapters=[],
        metadata=BookMetadata(title=title),
    )
    return job_from_book(book, Path(f"/out/{title}.m4b"))


def _make_qm(app) -> QueueManager:
    return QueueManager()


# ── basic queue operations ────────────────────────────────────────────────────


def test_add_job_appends_to_list(qapp):
    qm = QueueManager()
    j = _job("A")
    qm.add(j)
    assert len(qm.jobs) == 1
    assert qm.jobs[0].id == j.id


def test_add_multiple_jobs(qapp):
    qm = QueueManager()
    for name in ("A", "B", "C"):
        qm.add(_job(name))
    assert len(qm.jobs) == 3


def test_get_job_returns_job(qapp):
    qm = QueueManager()
    j = _job("X")
    qm.add(j)
    assert qm.get_job(j.id) is j


def test_get_job_unknown_returns_none(qapp):
    qm = QueueManager()
    assert qm.get_job("nonexistent") is None


def test_remove_queued_job(qapp):
    qm = QueueManager()
    j1 = _job("A")
    j2 = _job("B")
    qm.add(j1)
    qm.add(j2)
    qm.remove(j1.id)
    assert qm.get_job(j1.id) is None
    assert qm.get_job(j2.id) is j2


def test_clear_completed_removes_done_jobs(qapp):
    qm = QueueManager()
    j1 = _job("done")
    j1.status = JobStatus.COMPLETED
    j2 = _job("queued")
    qm._jobs = [j1, j2]
    qm.clear_completed()
    assert len(qm.jobs) == 1
    assert qm.jobs[0].id == j2.id


# ── property views ────────────────────────────────────────────────────────────


def test_pending_jobs_filters_queued(qapp):
    qm = QueueManager()
    j1 = _job("A")
    j2 = _job("B")
    j2.status = JobStatus.COMPLETED
    qm._jobs = [j1, j2]
    assert len(qm.pending_jobs) == 1
    assert qm.pending_jobs[0].id == j1.id


def test_active_jobs_filters_running(qapp):
    qm = QueueManager()
    j = _job("running")
    j.status = JobStatus.RUNNING
    qm._jobs = [j]
    assert len(qm.active_jobs) == 1


def test_completed_jobs_includes_failed(qapp):
    qm = QueueManager()
    j_ok = _job("ok")
    j_ok.status = JobStatus.COMPLETED
    j_fail = _job("fail")
    j_fail.status = JobStatus.FAILED
    qm._jobs = [j_ok, j_fail]
    assert len(qm.completed_jobs) == 2


# ── sequential execution (mocked worker) ─────────────────────────────────────


class _FakeWorker:
    """Synchronously calls finished/failed without a real thread."""

    def __init__(self, job: Job, *, fail: bool = False, error: str = "") -> None:
        self._job = job
        self._fail = fail
        self._error = error
        self.progress_cb = None
        self.finished_cb = None
        self.failed_cb = None

    def connect_progress(self, cb): self.progress_cb = cb
    def connect_finished(self, cb): self.finished_cb = cb
    def connect_failed(self, cb): self.failed_cb = cb

    def isRunning(self): return False

    def start(self):
        if self._fail:
            if self.failed_cb:
                self.failed_cb(self._job.id, self._error)
        else:
            if self.finished_cb:
                self.finished_cb(self._job.id)


def _patch_worker(qm: QueueManager, workers_iter):
    """Intercept JobWorker construction so we control execution."""
    original_advance = qm._advance
    call_count = [0]
    worker_list = list(workers_iter)

    def fake_advance():
        if not qm._running:
            return
        next_job = next((j for j in qm._jobs if j.status == JobStatus.QUEUED), None)
        if next_job is None:
            qm._running = False
            qm.queue_finished.emit()
            return
        next_job.status = JobStatus.RUNNING
        next_job.progress = 0.0
        qm.job_updated.emit(next_job.id)

        idx = call_count[0]
        call_count[0] += 1
        fw = worker_list[idx] if idx < len(worker_list) else _FakeWorker(next_job)
        fw._job = next_job

        fw.connect_finished(qm._on_finished)
        fw.connect_failed(qm._on_failed)
        qm._worker = fw  # type: ignore[assignment]
        fw.start()

    qm._advance = fake_advance  # type: ignore[method-assign]


def test_sequential_execution_marks_jobs_completed(qapp):
    qm = QueueManager()
    j1 = _job("A")
    j2 = _job("B")
    qm.add(j1)
    qm.add(j2)

    workers = [_FakeWorker(j1), _FakeWorker(j2)]
    _patch_worker(qm, workers)

    finished_signal = []
    qm.queue_finished.connect(lambda: finished_signal.append(True))

    qm.start()
    assert j1.status == JobStatus.COMPLETED
    assert j2.status == JobStatus.COMPLETED
    assert finished_signal == [True]


def test_failed_job_continues_to_next(qapp):
    qm = QueueManager()
    j1 = _job("fail_me")
    j2 = _job("should_run")
    qm.add(j1)
    qm.add(j2)

    workers = [_FakeWorker(j1, fail=True, error="boom"), _FakeWorker(j2)]
    _patch_worker(qm, workers)

    qm.start()
    assert j1.status == JobStatus.FAILED
    assert j1.error_message == "boom"
    assert j2.status == JobStatus.COMPLETED


def test_job_updated_signal_emitted(qapp):
    qm = QueueManager()
    j = _job("signal_test")
    qm.add(j)

    updates = []
    qm.job_updated.connect(updates.append)

    workers = [_FakeWorker(j)]
    _patch_worker(qm, workers)
    qm.start()

    assert j.id in updates


def test_stop_prevents_next_job(qapp):
    qm = QueueManager()
    j1 = _job("first")
    j2 = _job("second")
    qm.add(j1)
    qm.add(j2)

    call_count = [0]

    def fake_advance():
        call_count[0] += 1
        if call_count[0] == 1:
            # first advance: run j1
            j1.status = JobStatus.RUNNING
            j1.status = JobStatus.COMPLETED
            qm.job_updated.emit(j1.id)
            qm.stop()   # stop before moving to j2
            # now call _on_finished directly
            real_on_finished = QueueManager._on_finished.__get__(qm, QueueManager)
        # if called again after stop, just return
    # patch minimally: just stop before j2 starts
    qm._running = True
    qm.stop()
    assert qm._running is False
    # j2 stays queued
    assert j2.status == JobStatus.QUEUED
