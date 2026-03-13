"""ffprobe-based duration probing and FFMETADATA chapter file generation."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from m4bmaker.models import BookMetadata, Chapter
from m4bmaker.utils import subprocess_flags

# Matches leading digits optionally followed by separators (space/dash/dot/underscore).
# Examples stripped: "01 - ", "1.", "02_", "003 "
_CHAPTER_TITLE_RE = re.compile(r"^\d+[\s.\-_]*")


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
            **subprocess_flags(),
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
    """Build a Chapter list from *files* using ffprobe for durations.

    Chapters are indexed sequentially starting at 1, with *start_time* in
    seconds (float).  *source_file* is set to the corresponding input path.
    """
    chapters: list[Chapter] = []
    cursor_s: float = 0.0
    total = len(files)

    for i, path in enumerate(files, 1):
        if progress_fn is not None:
            progress_fn(i, total, path.name)
        duration_sec = get_duration(path, ffprobe)
        title = _strip_chapter_prefix(path.stem)
        chapters.append(
            Chapter(
                index=i,
                start_time=cursor_s,
                title=title,
                source_file=path,
            )
        )
        cursor_s += duration_sec

    return chapters


def _format_time(seconds: float) -> str:
    """Format a duration in seconds as H:MM:SS."""
    s = int(seconds)
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

    _h = "\u2500"
    _cols = [num_w, time_w, title_width]

    def _hline(left: str, join: str, right: str) -> str:
        return "  " + left + join.join(_h * (w + 2) for w in _cols) + right

    top = _hline("\u250c", "\u252c", "\u2510")
    sep = _hline("\u251c", "\u253c", "\u2524")
    bot = _hline("\u2514", "\u2534", "\u2518")
    hdr = (
        f"  \u2502 {'#':>{num_w}} \u2502"
        f" {'Start':<{time_w}} \u2502"
        f" {'Title':<{title_width}} \u2502"
    )

    rows = [top, hdr, sep]
    for ch in chapters:
        start = _format_time(ch.start_time)
        title = ch.title
        if len(title) > title_width:
            title = title[: title_width - 1] + "\u2026"
        rows.append(
            f"  \u2502 {ch.index:>{num_w}} \u2502"
            f" {start:<{time_w}} \u2502"
            f" {title:<{title_width}} \u2502"
        )
    rows.append(bot)
    return "\n".join(rows)


def write_ffmetadata(
    chapters: list[Chapter],
    meta: BookMetadata,
    dest: Path,
    total_duration_s: float,
) -> None:
    """Write an FFMETADATA1 file with global tags and chapter markers to *dest*.

    Chapter END timestamps are derived from the next chapter's *start_time*;
    the final chapter ends at *total_duration_s*.
    """
    lines: list[str] = [";FFMETADATA1\n"]

    # Global metadata tags
    if meta.title:
        lines.append(f"title={meta.title}\n")
    if meta.author:
        lines.append(f"artist={meta.author}\n")
    if meta.narrator:
        lines.append(f"composer={meta.narrator}\n")
    if meta.genre:
        lines.append(f"genre={meta.genre}\n")

    lines.append("\n")

    for i, chapter in enumerate(chapters):
        if i + 1 < len(chapters):
            end_ms = int(chapters[i + 1].start_time * 1000)
        else:
            end_ms = int(total_duration_s * 1000)
        start_ms = int(chapter.start_time * 1000)

        lines.append("[CHAPTER]\n")
        lines.append("TIMEBASE=1/1000\n")
        lines.append(f"START={start_ms}\n")
        lines.append(f"END={end_ms}\n")
        lines.append(f"title={chapter.title}\n")
        lines.append("\n")

    dest.write_text("".join(lines), encoding="utf-8")
