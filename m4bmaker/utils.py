"""Utility helpers: ffmpeg/ffprobe detection and progress logging."""

from __future__ import annotations

import shutil
import sys


_INSTALL_HINT = (
    "  macOS (Homebrew): brew install ffmpeg\n"
    "  Ubuntu/Debian:    sudo apt install ffmpeg\n"
    "  Docker:           see docs/docker.md"
)


def find_ffmpeg() -> str:
    """Return the path to the ffmpeg executable or exit with install instructions."""
    path = shutil.which("ffmpeg")
    if path is None:
        sys.exit(
            "Error: ffmpeg not found on PATH.\n"
            "Please install ffmpeg >= 6.0:\n" + _INSTALL_HINT
        )
    return path


def find_ffprobe() -> str:
    """Return the path to the ffprobe executable or exit with install instructions."""
    path = shutil.which("ffprobe")
    if path is None:
        sys.exit(
            "Error: ffprobe not found on PATH.\n"
            "ffprobe is bundled with ffmpeg. Please install ffmpeg >= 6.0:\n"
            + _INSTALL_HINT
        )
    return path


def log(msg: str) -> None:
    """Print a timestamped progress message to stdout."""
    print(msg, flush=True)
