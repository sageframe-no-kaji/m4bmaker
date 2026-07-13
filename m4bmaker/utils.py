"""Utility helpers: ffmpeg/ffprobe detection and progress logging."""

from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from m4bmaker.errors import M4BError

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

    # When frozen by PyInstaller: sys._MEIPASS is the data dir
    # (_internal/ in onedir, temp dir in onefile).
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for n in names:
            candidate = os.path.join(meipass, n)
            if os.path.isfile(candidate):
                return candidate
            # static_ffmpeg's hook places binaries in a platform subdir (e.g. win32/)
            try:
                for entry in os.scandir(meipass):
                    if entry.is_dir():
                        candidate = os.path.join(entry.path, n)
                        if os.path.isfile(candidate):
                            return candidate
            except OSError:
                pass

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
            frameworks = os.path.normpath(os.path.join(exe_dir, "..", "Frameworks", n))
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


def subprocess_flags() -> dict[str, Any]:
    """Return kwargs that suppress console windows on Windows frozen builds."""
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import subprocess as _sp

        return {"creationflags": _sp.CREATE_NO_WINDOW}
    return {}


def log(msg: str) -> None:
    """Print a timestamped progress message to stdout."""
    print(msg, flush=True)


# ── filename sanitisation ────────────────────────────────────────────────────

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_RESERVED_CHARS_RE = re.compile(r'[/\\:*?"<>|]')
_WHITESPACE_RUN_RE = re.compile(r"\s+")

_MAX_FILENAME_LENGTH = 120


def sanitize_filename_component(s: str) -> str:
    """Return *s* made safe for use as a single filename or directory component.

    - Strips NUL and other control characters.
    - Replaces each of ``/ \\ : * ? " < > |`` with ``-``.
    - Collapses runs of whitespace into a single space.
    - Strips leading/trailing dots and spaces (Windows disallows trailing
      dots/spaces; leading dots create hidden files on POSIX).
    - A result of ``""``, ``"."``, or ``".."`` becomes ``"Untitled"``.
    - Truncates to 120 characters.
    """
    cleaned = _CONTROL_CHARS_RE.sub("", s)
    cleaned = _RESERVED_CHARS_RE.sub("-", cleaned)
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned)
    cleaned = cleaned.strip(" .")

    if cleaned in ("", ".", ".."):
        return "Untitled"

    return cleaned[:_MAX_FILENAME_LENGTH]


# ── process-lifetime temp root ───────────────────────────────────────────────

_temp_root: str | None = None


def get_temp_root() -> Path:
    """Return a per-process temp directory, created lazily on first call.

    The directory is registered with :mod:`atexit` for recursive removal so
    callers (e.g. :mod:`m4bmaker.cover`) can allocate short-lived subdirs
    under it without leaking them across the life of the process.
    """
    global _temp_root
    if _temp_root is None:
        _temp_root = tempfile.mkdtemp(prefix="m4bmaker_")
        atexit.register(shutil.rmtree, _temp_root, ignore_errors=True)
    return Path(_temp_root)


# ── interactive input helper ─────────────────────────────────────────────────


def safe_input(prompt: str, no_prompt_hint: str = "--no-prompt") -> str:
    """Wrap :func:`input` so EOF/interrupt produce a clean exit, not a traceback.

    Raises :class:`~m4bmaker.errors.M4BError` with a one-line message
    suggesting *no_prompt_hint* when stdin is closed (EOFError) or the user
    interrupts (KeyboardInterrupt) while a prompt is awaiting input.
    """
    try:
        return input(prompt)
    except EOFError:
        raise M4BError(
            f"No input available for prompt. Use {no_prompt_hint} to run "
            "non-interactively."
        ) from None
    except KeyboardInterrupt:
        raise M4BError("Cancelled.") from None
