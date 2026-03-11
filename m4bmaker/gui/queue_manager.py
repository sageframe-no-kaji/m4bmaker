"""Queue manager and per-job worker for the batch encoding queue.

:class:`JobWorker` runs a single :class:`~m4bmaker.gui.job.Job` off the
UI thread.  :class:`QueueManager` owns all jobs, launches workers one at
a time, and emits signals so the :class:`~m4bmaker.gui.queue_window.QueueWindow`
can stay in sync without polling.
"""

from __future__ import annotations

import shutil
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal

from m4bmaker.gui.job import Job, JobStatus

if TYPE_CHECKING:
    pass


# ── per-job worker ────────────────────────────────────────────────────────────


class JobWorker(QThread):
    """Run ``run_pipeline`` for one :class:`Job` off the UI thread."""

    # job_id, human message, 0.0–1.0
    progress = Signal(str, str, float)
    finished = Signal(str)   # job_id
    failed = Signal(str, str)  # job_id, error message
    cancelled = Signal(str)  # job_id

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Signal the running ffmpeg subprocess to stop."""
        self._cancel_event.set()

    def run(self) -> None:
        from m4bmaker.pipeline import run_pipeline

        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        ffprobe = shutil.which("ffprobe") or "ffprobe"

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
                self.finished.emit(self._job.id)
        except SystemExit as exc:
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

    job_updated = Signal(str)   # job_id
    queue_finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: list[Job] = []
        self._worker: JobWorker | None = None
        self._running = False  # True while the queue is consuming jobs

    # ── public API ────────────────────────────────────────────────────────────

    def add(self, job: Job) -> None:
        """Append *job* to the queue (does not start processing)."""
        self._jobs.append(job)
        self.job_updated.emit(job.id)

    def start(self) -> None:
        """Begin sequential processing from the first queued job."""
        if self._running:
            return
        self._running = True
        self._advance()

    def stop(self) -> None:
        """Cancel the running job immediately and stop the queue."""
        self._running = False
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()

    def remove(self, job_id: str) -> None:
        """Remove a queued (not running) job."""
        self._jobs = [j for j in self._jobs if j.id != job_id or j.status == JobStatus.RUNNING]

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
        return self._running and self._worker is not None and self._worker.isRunning()

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

        self._worker = JobWorker(next_job)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.start()

    def _on_progress(self, job_id: str, msg: str, frac: float) -> None:
        job = self.get_job(job_id)
        if job is None:
            return
        job.progress = frac
        job.status_message = msg
        self.job_updated.emit(job_id)

    def _on_finished(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is not None:
            job.status = JobStatus.COMPLETED
            job.progress = 1.0
            job.status_message = "Done"
            self.job_updated.emit(job_id)
        self._advance()

    def _on_cancelled(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is not None:
            job.status = JobStatus.CANCELLED
            job.status_message = "Cancelled"
            self.job_updated.emit(job_id)
        self._running = False
        self.queue_finished.emit()

    def _on_failed(self, job_id: str, error: str) -> None:
        job = self.get_job(job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = error
            job.status_message = "Failed"
            self.job_updated.emit(job_id)
        # Continue to next job even on failure
        self._advance()
