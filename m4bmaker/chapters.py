"""ffprobe-based duration probing and FFMETADATA chapter file generation."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Matches leading digits optionally followed by separators (space/dash/dot/underscore).
# Examples stripped: "01 - ", "1.", "02_", "003 "
_CHAPTER_TITLE_RE = re.compile(r"^\d+[\s.\-_]*")


@dataclass
class Chapter:
    title: str
    start_ms: int  # inclusive start, milliseconds
    end_ms: int  # exclusive end, milliseconds


def _strip_chapter_prefix(stem: str) -> str:
    """Remove leading numeric prefix and separators from a filename stem."""
    cleaned = _CHAPTER_TITLE_RE.sub("", stem).strip()
    return cleaned if cleaned else stem


def get_duration(file: Path, ffprobe: str) -> float:
    """Return the duration of *file* in seconds using ffprobe JSON output."""
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(file),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(
            f"Error: ffprobe failed for '{file}'.\n"
            f"The file may be corrupt or in an unsupported format.\n"
            f"ffprobe stderr: {exc.stderr.strip()}"
        )

    try:
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        sys.exit(
            f"Error: could not parse ffprobe output for '{file}': {exc}"
        )

    return duration


def build_chapters(files: list[Path], ffprobe: str) -> list[Chapter]:
    """Build a Chapter list from *files* using ffprobe for durations."""
    chapters: list[Chapter] = []
    cursor_ms = 0

    for path in files:
        duration_sec = get_duration(path, ffprobe)
        duration_ms = round(duration_sec * 1000)
        title = _strip_chapter_prefix(path.stem)
        chapters.append(
            Chapter(
                title=title,
                start_ms=cursor_ms,
                end_ms=cursor_ms + duration_ms,
            )
        )
        cursor_ms += duration_ms

    return chapters


def write_ffmetadata(
    chapters: list[Chapter], meta: dict[str, str], dest: Path
) -> None:
    """Write an FFMETADATA1 file with global tags and chapter markers to *dest*."""
    lines: list[str] = [";FFMETADATA1\n"]

    # Global metadata tags
    if meta.get("title"):
        lines.append(f"title={meta['title']}\n")
    if meta.get("author"):
        lines.append(f"artist={meta['author']}\n")
    if meta.get("narrator"):
        lines.append(f"composer={meta['narrator']}\n")

    lines.append("\n")

    for chapter in chapters:
        lines.append("[CHAPTER]\n")
        lines.append("TIMEBASE=1/1000\n")
        lines.append(f"START={chapter.start_ms}\n")
        lines.append(f"END={chapter.end_ms}\n")
        lines.append(f"title={chapter.title}\n")
        lines.append("\n")

    dest.write_text("".join(lines), encoding="utf-8")
