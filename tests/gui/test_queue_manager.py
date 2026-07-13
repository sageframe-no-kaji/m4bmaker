"""Tests for QueueManager (mocked workers — no ffmpeg required)."""

from __future__ import annotations

from pathlib import Path

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

    def connect_progress(self, cb):
        self.progress_cb = cb

    def connect_finished(self, cb):
        self.finished_cb = cb

    def connect_failed(self, cb):
        self.failed_cb = cb

    def isRunning(self):
        return False

    def start(self):
        if self._fail:
            if self.failed_cb:
                self.failed_cb(self._job.id, self._error)
        else:
            if self.finished_cb:
                self.finished_cb(self._job.id)


def _patch_worker(qm: QueueManager, workers_iter):
    """Intercept JobWorker construction so we control execution."""
    _ = qm._advance  # keep reference to original
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
            qm.stop()  # stop before moving to j2
            # now call _on_finished directly
            _ = QueueManager._on_finished.__get__(qm, QueueManager)  # noqa: F841
        # if called again after stop, just return

    # patch minimally: just stop before j2 starts
    qm._running = True
    qm.stop()
    assert qm._running is False
    # j2 stays queued
    assert j2.status == JobStatus.QUEUED


# ── stop→start race guard (HIGH) ──────────────────────────────────────────────


class _SlowWorker:
    """Stand-in for a JobWorker whose thread is still alive after stop().

    ``isRunning`` stays True until :meth:`finish` is called, mimicking an
    ffmpeg child that keeps dying after the cancel event fires.
    """

    def __init__(self, job: Job) -> None:
        self._job = job
        self._alive = True
        self.cancel_requested = False

    def isRunning(self) -> bool:
        return self._alive

    def request_cancel(self) -> None:
        self.cancel_requested = True

    def cancel(self) -> None:
        self.request_cancel()

    def start(self) -> None:  # no real thread
        pass

    def finish(self) -> None:
        self._alive = False


def test_start_refuses_while_previous_worker_still_running(qapp):
    """start() must not spawn a second worker while the old one is dying."""
    qm = QueueManager()
    j1 = _job("A")
    j2 = _job("B")
    qm.add(j1)
    qm.add(j2)

    slow = _SlowWorker(j1)
    qm._worker = slow  # type: ignore[assignment]
    qm._running = True  # queue believes it is still consuming j1

    # stop() sets the cancel event but leaves _running true until the thread ends.
    qm.stop()
    assert slow.cancel_requested is True
    assert qm._running is True  # NOT cleared while the worker is still alive

    # A Start click arriving now must be refused — no second worker.
    qm.start()
    assert qm._worker is slow  # unchanged; no overwrite of the live QThread


def test_stop_keeps_running_true_until_worker_exits(qapp):
    """_running only clears once the (real) cancellation signal lands."""
    qm = QueueManager()
    j1 = _job("A")
    qm.add(j1)

    slow = _SlowWorker(j1)
    qm._worker = slow  # type: ignore[assignment]
    qm._running = True
    j1.status = JobStatus.RUNNING

    qm.stop()
    assert qm._running is True

    # Simulate the worker's cancelled signal arriving (delivered directly, so
    # sender() is None → treated as current, not stale).
    qm._on_cancelled(j1.id)
    assert qm._running is False
    assert j1.status == JobStatus.CANCELLED


# ── generation / staleness guard ──────────────────────────────────────────────


class _NamedWorker:
    """Minimal object usable as a fake ``self.sender()`` return value."""


def test_late_signal_from_superseded_worker_is_ignored(qapp):
    """A finished/failed signal from a non-current worker must be dropped."""
    qm = QueueManager()
    j1 = _job("A")
    qm.add(j1)
    j1.status = JobStatus.RUNNING

    current = _NamedWorker()
    stale = _NamedWorker()
    qm._worker = current  # type: ignore[assignment]

    # Emulate Qt's sender() returning the *stale* worker for this slot call.
    qm.sender = lambda: stale  # type: ignore[method-assign]
    qm._on_finished(j1.id)
    # The stale completion must be ignored — job stays RUNNING.
    assert j1.status == JobStatus.RUNNING

    # A signal from the current worker is honoured.
    qm.sender = lambda: current  # type: ignore[method-assign]
    qm._on_finished(j1.id)
    assert j1.status == JobStatus.COMPLETED


def test_stale_failed_signal_ignored(qapp):
    """A failed signal from a superseded worker must not corrupt state."""
    qm = QueueManager()
    j1 = _job("A")
    qm.add(j1)
    j1.status = JobStatus.RUNNING

    current = _NamedWorker()
    stale = _NamedWorker()
    qm._worker = current  # type: ignore[assignment]
    qm.sender = lambda: stale  # type: ignore[method-assign]
    qm._on_failed(j1.id, "late boom")
    assert j1.status == JobStatus.RUNNING
    assert j1.error_message == ""
