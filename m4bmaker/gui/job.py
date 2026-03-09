"""Job model for the batch encoding queue.

A :class:`Job` is a frozen snapshot of a complete audiobook build
configuration — everything needed to call :func:`run_pipeline` without
touching the main window.  Jobs are managed by
:class:`~m4bmaker.gui.queue_manager.QueueManager`.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from m4bmaker.models import Book, BookMetadata, Chapter


class JobStatus(Enum):
    QUEUED = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class Job:
    """Immutable build configuration + mutable runtime state."""

    # ── identity ─────────────────────────────────────────────────────────────
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ── build inputs (snapshot of GUI state at enqueue time) ─────────────────
    book: Book = field(default_factory=lambda: Book([], [], BookMetadata()))
    output_path: Path = field(default_factory=lambda: Path("."))
    bitrate: str = "96k"
    stereo: bool = False
    sample_rate: int | None = None  # None → let ffmpeg decide

    # ── runtime state (mutable) ───────────────────────────────────────────────
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0          # 0.0 – 1.0
    status_message: str = ""
    error_message: str = ""

    # ── display ───────────────────────────────────────────────────────────────
    @property
    def title(self) -> str:
        """Best display name: metadata title → folder name → output stem."""
        if self.book.metadata.title:
            return self.book.metadata.title
        if self.book.files:
            return self.book.files[0].parent.name
        return self.output_path.stem

    @property
    def is_done(self) -> bool:
        return self.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )


def job_from_book(
    book: Book,
    output_path: Path,
    bitrate: str = "96k",
    stereo: bool = False,
    sample_rate: int | None = None,
) -> Job:
    """Create a :class:`Job` from the current GUI book state.

    Deep-copies *book* so later edits to the main window do not affect
    the queued job.
    """
    return Job(
        book=deepcopy(book),
        output_path=output_path,
        bitrate=bitrate,
        stereo=stereo,
        sample_rate=sample_rate,
    )
