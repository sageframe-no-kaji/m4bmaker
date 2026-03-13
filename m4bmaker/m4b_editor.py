"""Load and rewrite chapter metadata in existing .m4b files without re-encoding.

Uses ``ffprobe -show_chapters`` to read current chapter markers and
``ffmpeg -c copy`` to write updated chapters back into the container
without touching the audio stream.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from m4bmaker.chapters import write_ffmetadata
from m4bmaker.models import BookMetadata, Chapter
from m4bmaker.utils import subprocess_flags


def load_m4b_chapters(path: Path, ffprobe: str) -> tuple[list[Chapter], float]:
    """Return ``(chapters, total_duration_s)`` from an existing .m4b file.

    Uses ``ffprobe -show_chapters -show_format``.  If the file contains no
    chapter markers an empty list is returned (total_duration is still set).
    Raises :exc:`SystemExit` if ffprobe fails.
    """
    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_chapters",
        "-show_format",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, **subprocess_flags())
    except subprocess.CalledProcessError as exc:
        sys.exit(f"Error reading '{path.name}': {exc.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        sys.exit(f"Error parsing ffprobe output for '{path.name}': {exc}")

    total_duration = float(data.get("format", {}).get("duration", 0.0))

    raw_chapters = data.get("chapters", [])
    chapters: list[Chapter] = []
    for i, ch in enumerate(raw_chapters, 1):
        start_s = float(ch.get("start_time", 0.0))
        title = ch.get("tags", {}).get("title", f"Chapter {i}")
        chapters.append(
            Chapter(index=i, start_time=start_s, title=title, source_file=path)
        )

    return chapters, total_duration


def save_m4b_chapters(
    source: Path,
    chapters: list[Chapter],
    total_duration: float,
    dest: Path,
    ffmpeg: str,
) -> None:
    """Rewrite *dest* with updated chapter metadata, keeping audio intact.

    *source* and *dest* may be the same path — an intermediate temp file is
    used in that case so the original is not corrupted on failure.

    Raises :exc:`SystemExit` if ffmpeg fails.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        meta_file = tmp_dir / "chapters.ffmetadata"
        write_ffmetadata(chapters, BookMetadata(), meta_file, total_duration)

        in_place = source.resolve() == dest.resolve()
        out_path = tmp_dir / "out.m4b" if in_place else dest

        dest.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-i",
            str(meta_file),
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-c",
            "copy",
            "-metadata",
            "stik=2",  # iTunes audiobook type — required for iOS Books
            "-brand",
            "M4B ",  # ftyp major brand — required for iOS Books
            str(out_path),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, **subprocess_flags())
        except subprocess.CalledProcessError as exc:
            sys.exit(f"Error saving chapters to '{dest.name}': {exc.stderr.strip()}")

        if in_place:
            dest.write_bytes(out_path.read_bytes())
