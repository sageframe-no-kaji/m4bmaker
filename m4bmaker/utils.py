"""Utility helpers: ffmpeg/ffprobe detection and progress logging."""

from __future__ import annotations

import os
import shutil
import sys

_INSTALL_HINT = (
    "  macOS (Homebrew): brew install ffmpeg\n"
    "  Windows:          winget install Gyan.FFmpeg\n"
    "  Ubuntu/Debian:    sudo apt install ffmpeg"
)

# Common locations not on the minimal PATH inside a .app bundle
_EXTRA_DIRS = [
    "/opt/homebrew/bin",  # Apple Silicon Homebrew
    "/usr/local/bin",  # Intel Homebrew / manual installs
    "/opt/local/bin",  # MacPorts
]


def _which(name: str) -> str | None:
    """Like shutil.which but checks bundled app binaries first, then Homebrew."""
    # On Windows the executable has a .exe extension
    names = [name + ".exe", name] if sys.platform == "win32" else [name]

    # When frozen by PyInstaller (--onefile): sys._MEIPASS is the extraction dir
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for n in names:
            candidate = os.path.join(meipass, n)
            if os.path.isfile(candidate):
                return candidate

    # When frozen as a macOS .app bundle (--onedir + BUNDLE):
    # binaries land in Contents/Frameworks/, which is a sibling of Contents/MacOS/
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        for n in names:
            # Check same dir as executable (covers onedir non-bundle + Windows)
            candidate = os.path.join(exe_dir, n)
            if os.path.isfile(candidate):
                return candidate
            # Check Contents/Frameworks/ (macOS .app bundle)
            frameworks = os.path.normpath(
                os.path.join(exe_dir, "..", "Frameworks", n)
            )
            if os.path.isfile(frameworks):
                return frameworks

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
