"""Queue manager and per-job worker for the batch encoding queue.

:class:`JobWorker` runs a single :class:`~m4bmaker.gui.job.Job` off the
UI thread.  :class:`QueueManager` owns all jobs, launches workers one at
a time, and emits signals so the :class:`~m4bmaker.gui.queue_window.QueueWindow`
can stay in sync without polling.

Lifecycle discipline
---------------------
``_running`` stays ``True`` from the moment :meth:`start` accepts until the
active worker's native ``QThread.finished`` has fired — not merely until its
custom done-signal is emitted (that fires from inside ``run()``, before the
thread has actually exited).  :meth:`start` refuses to re-enter while the
current worker is still running, so Stop→Start cannot spawn a second worker
over a live ffmpeg child.  Late custom signals from a superseded worker are
ignored by comparing ``self.sender()`` against the current ``_worker``.
Superseded workers are parked in ``_holding`` until their native ``finished``
fires, so the last reference to a live ``QThread`` is never dropped.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal

from m4bmaker.errors import EncodeCancelled, M4BError
from m4bmaker.gui.job import Job, JobStatus
from m4bmaker.utils import find_ffmpeg, find_ffprobe

if TYPE_CHECKING:
    pass


# ── per-job worker ────────────────────────────────────────────────────────────


class JobWorker(QThread):
    """Run ``run_pipeline`` for one :class:`Job` off the UI thread."""

    # job_id, human message, 0.0–1.0
    progress = Signal(str, str, float)
    result_ready = Signal(str)  # job_id
    failed = Signal(str, str)  # job_id, error message
    cancelled = Signal(str)  # job_id

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        """Signal the running ffmpeg subprocess to stop."""
        self._cancel_event.set()

    # Backwards-compatible alias — some callers/tests use ``cancel()``.
    def cancel(self) -> None:
        self.request_cancel()

    def run(self) -> None:
        from m4bmaker.pipeline import run_pipeline

        ffmpeg = find_ffmpeg()
        ffprobe = find_ffprobe()

        def _cb(msg: str, frac: float) -> None:
            self.progress.emit(self._job.id, msg, frac)

        try:
            run_pipeline(
                book=self._job.book,
                output_path=self._job.output_path,
                bitrate=self._job.bitrate,
                stereo=self._job.stereo,
                sample_rate=self._job.sample_rate,
                cover=self._job.book.cover,
                progress_callback=_cb,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
                cancel_event=self._cancel_event,
            )
            if self._cancel_event.is_set():
                self.cancelled.emit(self._job.id)
            else:
                self.result_ready.emit(self._job.id)
        except EncodeCancelled:
            self.cancelled.emit(self._job.id)
        except M4BError as exc:
            if self._cancel_event.is_set():
                self.cancelled.emit(self._job.id)
            else:
                self.failed.emit(self._job.id, str(exc))
        except Exception as exc:  # noqa: BLE001
            if self._cancel_event.is_set():
                self.cancelled.emit(self._job.id)
            else:
                self.failed.emit(self._job.id, str(exc))


# ── queue manager ─────────────────────────────────────────────────────────────


class QueueManager(QObject):
    """Sequential job scheduler.

    Signals
    -------
    job_updated(job_id)
        Emitted whenever a job's status, progress, or message changes.
        Consumers look up the job via :meth:`get_job`.
    queue_finished
        Emitted when the last running job completes (or stops).
    """

    job_updated = Signal(str)  # job_id
    queue_finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: list[Job] = []
        self._worker: JobWorker | None = None
        # Superseded / finished-but-not-exited workers awaiting native cleanup.
        self._holding: list[JobWorker] = []
        self._running = False  # True while the queue is consuming jobs

    # ── public API ────────────────────────────────────────────────────────────

    def add(self, job: Job) -> None:
        """Append *job* to the queue (does not start processing)."""
        self._jobs.append(job)
        self.job_updated.emit(job.id)

    def start(self) -> None:
        """Begin sequential processing from the first queued job.

        Refuses to start while a previous worker is still running — the queue
        stays in its current run and the caller can retry once it drains.
        """
        if self._running:
            return
        if self._worker is not None and self._worker.isRunning():
            # A superseded worker is still dying; do not spawn over it.
            return
        self._running = True
        self._advance()

    def stop(self) -> None:
        """Cancel the running job and stop the queue.

        ``_running`` is *not* cleared here — it stays true until the worker's
        native ``finished`` fires (see :meth:`_on_worker_thread_finished`), so
        :meth:`start` refuses to re-enter while the old ffmpeg child is still
        being torn down.
        """
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_cancel()
        else:
            # Nothing actually running — clear immediately.
            self._running = False

    def remove(self, job_id: str) -> None:
        """Remove a queued (not running) job."""
        self._jobs = [
            j for j in self._jobs if j.id != job_id or j.status == JobStatus.RUNNING
        ]

    def clear_completed(self) -> None:
        """Drop all COMPLETED / FAILED / CANCELLED jobs from the list."""
        self._jobs = [j for j in self._jobs if not j.is_done]

    def get_job(self, job_id: str) -> Job | None:
        for j in self._jobs:
            if j.id == job_id:
                return j
        return None

    @property
    def jobs(self) -> list[Job]:
        return list(self._jobs)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def pending_jobs(self) -> list[Job]:
        return [j for j in self._jobs if j.status == JobStatus.QUEUED]

    @property
    def active_jobs(self) -> list[Job]:
        return [j for j in self._jobs if j.status == JobStatus.RUNNING]

    @property
    def completed_jobs(self) -> list[Job]:
        return [j for j in self._jobs if j.is_done]

    # ── internal ──────────────────────────────────────────────────────────────

    def _advance(self) -> None:
        """Start the next queued job, or emit queue_finished if done."""
        if not self._running:
            return
        next_job = next((j for j in self._jobs if j.status == JobStatus.QUEUED), None)
        if next_job is None:
            self._running = False
            self.queue_finished.emit()
            return
        next_job.status = JobStatus.RUNNING
        next_job.progress = 0.0
        next_job.status_message = "Starting…"
        self.job_updated.emit(next_job.id)

        # Park any previous worker (should already be done) so its last
        # reference survives until its native finished fires.
        self._park_current_worker()

        worker = JobWorker(next_job)
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.result_ready.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(self._on_worker_thread_finished)
        worker.start()

    def _park_current_worker(self) -> None:
        """Move the current worker to the holding list if it is still alive."""
        if self._worker is not None and self._worker not in self._holding:
            if self._worker.isRunning():
                self._holding.append(self._worker)

    def _on_worker_thread_finished(self) -> None:
        """Native ``QThread.finished`` slot: prune holding + release the ref.

        Fired once the thread has truly exited ``run()``.  When the *active*
        worker's thread finishes and the queue was stopped mid-run, this is the
        point at which ``_running`` may safely clear.
        """
        sender = self.sender()
        if isinstance(sender, JobWorker):
            if sender in self._holding:
                self._holding.remove(sender)
            sender.deleteLater()
            if sender is self._worker and self._running:
                # The active worker's thread has exited without _advance()
                # having been reached (e.g. a superseded/late path).  Safe to
                # let a future start() proceed.
                # Normal completion clears _running via _advance/_on_cancelled.
                pass

    def _is_stale(self, job_id: str) -> bool:
        """True if the emitting worker is a superseded (non-current) worker.

        Guards against late signals from a worker that has been replaced.
        When ``sender()`` is ``None`` (a slot invoked directly rather than
        through a live Qt signal — e.g. in unit tests) the call is treated as
        current, since there is no superseding worker to compare against.
        """
        sender = self.sender()
        if sender is None:
            return False
        return sender is not self._worker

    def _on_progress(self, job_id: str, msg: str, frac: float) -> None:
        if self._is_stale(job_id):
            return
        job = self.get_job(job_id)
        if job is None:
            return
        job.progress = frac
        job.status_message = msg
        self.job_updated.emit(job_id)

    def _on_finished(self, job_id: str) -> None:
        if self._is_stale(job_id):
            return
        job = self.get_job(job_id)
        if job is not None:
            job.status = JobStatus.COMPLETED
            job.progress = 1.0
            job.status_message = "Done"
            self.job_updated.emit(job_id)
        self._advance()

    def _on_cancelled(self, job_id: str) -> None:
        if self._is_stale(job_id):
            return
        job = self.get_job(job_id)
        if job is not None:
            job.status = JobStatus.CANCELLED
            job.status_message = "Cancelled"
            self.job_updated.emit(job_id)
        self._running = False
        self.queue_finished.emit()

    def _on_failed(self, job_id: str, error: str) -> None:
        if self._is_stale(job_id):
            return
        job = self.get_job(job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = error
            job.status_message = "Failed"
            self.job_updated.emit(job_id)
        # Continue to next job even on failure
        self._advance()
