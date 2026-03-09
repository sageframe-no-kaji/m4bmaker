"""Shared pytest fixtures for the m4bmaker test suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_stub_mp3(path: Path) -> Path:
    """Write a minimal valid-looking (but audio-less) stub file at *path*."""
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 128)  # fake MP3 header
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_audio_dir(tmp_path: Path) -> Path:
    """A tmp directory pre-populated with three stub .mp3 files in numeric order."""
    for name in ("01 - Chapter One.mp3", "02 - Chapter Two.mp3", "10 - Chapter Ten.mp3"):
        make_stub_mp3(tmp_path / name)
    return tmp_path


@pytest.fixture()
def ffprobe_json_factory() -> Generator[None, None, None]:
    """Not a real fixture — just documents the factory pattern used in tests."""
    yield  # no-op; tests call make_ffprobe_json directly


def make_ffprobe_json(duration: float) -> str:
    """Return a minimal ffprobe JSON response string for *duration* seconds."""
    return json.dumps({"format": {"duration": str(duration)}})


@pytest.fixture()
def mock_ffprobe_run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch subprocess.run so ffprobe returns a 3-second duration for every file."""
    mock = MagicMock()
    mock.return_value.returncode = 0
    mock.return_value.stdout = make_ffprobe_json(3.0)
    mock.return_value.stderr = ""
    monkeypatch.setattr("m4bmaker.chapters.subprocess.run", mock)
    return mock


@pytest.fixture()
def mock_ffmpeg_run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch subprocess.run in encoder so ffmpeg always succeeds without running."""
    mock = MagicMock()
    mock.return_value.returncode = 0
    mock.return_value.stdout = ""
    mock.return_value.stderr = ""
    monkeypatch.setattr("m4bmaker.encoder.subprocess.run", mock)
    return mock
