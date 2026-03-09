"""ffprobe-based duration probing and FFMETADATA chapter file generation."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
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
        "-v",
        "quiet",
        "-print_format",
        "json",
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
        sys.exit(f"Error: could not parse ffprobe output for '{file}': {exc}")

    return duration


def build_chapters(
    files: list[Path],
    ffprobe: str,
    progress_fn: Callable[[int, int, str], None] | None = None,
) -> list[Chapter]:
    """Build a Chapter list from *files* using ffprobe for durations."""
    chapters: list[Chapter] = []
    cursor_ms = 0
    total = len(files)

    for i, path in enumerate(files, 1):
        if progress_fn is not None:
            progress_fn(i, total, path.name)
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


def _format_chapter_ms(ms: int) -> str:
    """Format a millisecond offset as H:MM:SS for display and chapter files."""
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


def format_chapter_table(chapters: list[Chapter]) -> str:
    """Return a Unicode box-drawing table of chapters as a multi-line string."""
    if not chapters:
        return "  (no chapters)"

    title_width = min(max(len(c.title) for c in chapters), 40)
    title_width = max(title_width, 5)  # minimum column width

    num_w = max(len(str(len(chapters))), 1)
    time_w = 8  # "H:MM:SS" is at most 8 chars (e.g. "9:59:59")

    top = f"  ┌{'─' * (num_w + 2)}┬{'─' * (time_w + 2)}┬{'─' * (title_width + 2)}┐"
    hdr = f"  │ {'#':>{num_w}} │ {'Start':<{time_w}} │ {'Title':<{title_width}} │"
    sep = f"  ├{'─' * (num_w + 2)}┼{'─' * (time_w + 2)}┼{'─' * (title_width + 2)}┤"
    bot = f"  └{'─' * (num_w + 2)}┴{'─' * (time_w + 2)}┴{'─' * (title_width + 2)}┘"

    rows = [top, hdr, sep]
    for i, ch in enumerate(chapters, 1):
        start = _format_chapter_ms(ch.start_ms)
        title = ch.title
        if len(title) > title_width:
            title = title[: title_width - 1] + "\u2026"
        rows.append(f"  │ {i:>{num_w}} │ {start:<{time_w}} │ {title:<{title_width}} │")
    rows.append(bot)
    return "\n".join(rows)


def write_ffmetadata(chapters: list[Chapter], meta: dict[str, str], dest: Path) -> None:
    """Write an FFMETADATA1 file with global tags and chapter markers to *dest*."""
    lines: list[str] = [";FFMETADATA1\n"]

    # Global metadata tags
    if meta.get("title"):
        lines.append(f"title={meta['title']}\n")
    if meta.get("author"):
        lines.append(f"artist={meta['author']}\n")
    if meta.get("narrator"):
        lines.append(f"composer={meta['narrator']}\n")
    if meta.get("genre"):
        lines.append(f"genre={meta['genre']}\n")

    lines.append("\n")

    for chapter in chapters:
        lines.append("[CHAPTER]\n")
        lines.append("TIMEBASE=1/1000\n")
        lines.append(f"START={chapter.start_ms}\n")
        lines.append(f"END={chapter.end_ms}\n")
        lines.append(f"title={chapter.title}\n")
        lines.append("\n")

    dest.write_text("".join(lines), encoding="utf-8")
