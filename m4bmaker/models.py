"""Shared data models used by the pipeline, CLI, and GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Chapter:
    """A single audiobook chapter.

    *start_time* is in seconds (float).  *source_file* is the audio file that
    contributes this chapter; it is ``None`` for chapters loaded from an
    external ``--chapters-file``.
    """

    index: int
    start_time: float  # seconds
    title: str
    source_file: Path | None = field(default=None)


@dataclass
class BookMetadata:
    """Typed metadata for an audiobook."""

    title: str = ""
    author: str = ""
    narrator: str = ""
    genre: str = ""


@dataclass
class Book:
    """All information needed to encode an audiobook.

    Returned by :func:`m4bmaker.pipeline.load_audiobook` and used by both
    the CLI and the GUI as the central object passed through editing steps
    before encoding begins.
    """

    files: list[Path]
    chapters: list[Chapter]
    metadata: BookMetadata
    cover: Path | None = field(default=None)


@dataclass
class PipelineResult:
    """Outcome of a completed encode."""

    output_file: Path
    chapter_count: int
    duration_seconds: float
