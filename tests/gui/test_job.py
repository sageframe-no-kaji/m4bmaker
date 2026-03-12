"""Tests for the Job model (no Qt required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from m4bmaker.gui.job import Job, JobStatus, job_from_book
from m4bmaker.models import Book, BookMetadata, Chapter

# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_book(title: str = "Dune", files: list[Path] | None = None) -> Book:
    return Book(
        files=files or [Path("/audio/01.mp3"), Path("/audio/02.mp3")],
        chapters=[Chapter(index=0, start_time=0.0, title="Part 1")],
        metadata=BookMetadata(title=title, author="Herbert"),
    )


# ── JobStatus ─────────────────────────────────────────────────────────────────


def test_all_statuses_exist():
    names = {s.name for s in JobStatus}
    assert names == {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}


# ── Job defaults ──────────────────────────────────────────────────────────────


def test_job_default_status_is_queued():
    j = Job()
    assert j.status == JobStatus.QUEUED


def test_job_default_progress_is_zero():
    j = Job()
    assert j.progress == 0.0


def test_job_gets_unique_ids():
    ids = {Job().id for _ in range(50)}
    assert len(ids) == 50


# ── title property ────────────────────────────────────────────────────────────


def test_title_uses_metadata_when_present():
    j = Job(book=_make_book("Foundation"))
    assert j.title == "Foundation"


def test_title_falls_back_to_folder_name():
    book = _make_book(title="")
    j = Job(book=book, output_path=Path("/out/Foundation.m4b"))
    assert j.title == "audio"  # parent of /audio/01.mp3


def test_title_falls_back_to_output_stem():
    book = Book(files=[], chapters=[], metadata=BookMetadata(title=""))
    j = Job(book=book, output_path=Path("/out/MyBook.m4b"))
    assert j.title == "MyBook"


# ── is_done property ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status", [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
)
def test_is_done_true_for_terminal_states(status):
    j = Job(status=status)
    assert j.is_done is True


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING])
def test_is_done_false_for_active_states(status):
    j = Job(status=status)
    assert j.is_done is False


# ── job_from_book ─────────────────────────────────────────────────────────────


def test_job_from_book_deep_copies_book():
    book = _make_book("Dune")
    j = job_from_book(book, Path("/out/dune.m4b"))
    book.metadata.title = "MUTATED"
    assert j.book.metadata.title == "Dune"


def test_job_from_book_encodes_settings():
    book = _make_book()
    j = job_from_book(
        book, Path("/out/x.m4b"), bitrate="128k", stereo=True, sample_rate=44100
    )
    assert j.bitrate == "128k"
    assert j.stereo is True
    assert j.sample_rate == 44100


def test_job_from_book_output_path():
    book = _make_book()
    out = Path("/out/audiobook.m4b")
    j = job_from_book(book, out)
    assert j.output_path == out
