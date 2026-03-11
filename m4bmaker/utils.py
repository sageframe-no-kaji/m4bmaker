"""Utility helpers: ffmpeg/ffprobe detection and progress logging."""

from __future__ import annotations

import os
import shutil
import sys

_INSTALL_HINT = (
    "  macOS (Homebrew): brew install ffmpeg\n"
    "  Ubuntu/Debian:    sudo apt install ffmpeg\n"
    "  Docker:           see docs/docker.md"
)

# Common locations not on the minimal PATH inside a .app bundle
_EXTRA_DIRS = [
    "/opt/homebrew/bin",   # Apple Silicon Homebrew
    "/usr/local/bin",      # Intel Homebrew / manual installs
    "/opt/local/bin",      # MacPorts
]


def _which(name: str) -> str | None:
    """Like shutil.which but also checks common Homebrew locations."""
    path = shutil.which(name)
    if path:
        return path
    for d in _EXTRA_DIRS:
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def find_ffmpeg() -> str:
    """Return the path to the ffmpeg executable or exit with install instructions."""
    path = _which("ffmpeg")
    if path is None:
        sys.exit(
            "Error: ffmpeg not found on PATH.\n"
            "Please install ffmpeg >= 6.0:\n" + _INSTALL_HINT
        )
    return path


def find_ffprobe() -> str:
    """Return the path to the ffprobe executable or exit with install instructions."""
    path = _which("ffprobe")
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
