"""Directory scan and natural sort for supported audio files."""

from __future__ import annotations

from pathlib import Path

from natsort import natsorted

from m4bmaker.errors import M4BError

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".wav", ".ogg"}
)


def scan_audio_files(directory: Path) -> list[Path]:
    """Return all supported audio files in *directory*, in natural sort order.

    Hidden files (names starting with ``.``) are skipped — this covers macOS
    AppleDouble resource-fork files (``._foo.mp3``) that appear on FAT/SMB
    volumes and otherwise pass the extension filter, then hard-fail probing
    as "corrupt".

    Raises :class:`~m4bmaker.errors.M4BError` if the directory does not exist
    or contains no audio files.
    """
    if not directory.is_dir():
        raise M4BError(f"Error: directory not found: {directory}")

    files: list[Path] = [
        p
        for p in directory.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() in AUDIO_EXTENSIONS
    ]

    if not files:
        raise M4BError(
            f"Error: no supported audio files found in {directory}\n"
            f"Supported formats: {', '.join(sorted(AUDIO_EXTENSIONS))}"
        )

    result: list[Path] = natsorted(files, key=lambda p: p.name)
    return result
