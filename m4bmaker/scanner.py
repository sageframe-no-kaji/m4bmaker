"""Directory scan and natural sort for supported audio files."""

from __future__ import annotations

import sys
from pathlib import Path

from natsort import natsorted

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"}
)


def scan_audio_files(directory: Path) -> list[Path]:
    """Return all supported audio files in *directory*, in natural sort order.

    Raises SystemExit if the directory does not exist or contains no audio files.
    """
    if not directory.is_dir():
        sys.exit(f"Error: directory not found: {directory}")

    files: list[Path] = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    ]

    if not files:
        sys.exit(
            f"Error: no supported audio files found in {directory}\n"
            f"Supported formats: {', '.join(sorted(AUDIO_EXTENSIONS))}"
        )

    return natsorted(files, key=lambda p: p.name)  # type: ignore[no-any-return]
