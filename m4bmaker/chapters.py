"""ffprobe-based duration probing and FFMETADATA chapter file generation."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from m4bmaker.errors import M4BError
from m4bmaker.models import BookMetadata, Chapter
from m4bmaker.utils import subprocess_flags

# Matches leading digits optionally followed by separators (space/dash/dot/underscore).
# Examples stripped: "01 - ", "1.", "02_", "003 "
_CHAPTER_TITLE_RE = re.compile(r"^\d+[\s.\-_]*")


def _strip_chapter_prefix(stem: str) -> str:
    """Remove leading numeric prefix and separators from a filename stem."""
    cleaned = _CHAPTER_TITLE_RE.sub("", stem).strip()
    return cleaned if cleaned else stem


class _Probe(NamedTuple):
    """What :func:`_probe_file` reads from one audio file."""

    duration: float
    title: str | None
    # (start_seconds, title_or_None) for each chapter marker embedded in the
    # file, in order; empty when the file carries none.
    chapters: list[tuple[float, str | None]]


def _probe_file(file: Path, ffprobe: str) -> _Probe:
    """Run ffprobe on *file*: duration, title tag, and embedded chapters."""
    cmd = [
        ffprobe,
        "-v",
        "error",  # "-v quiet" would guarantee an empty stderr on failure
        "-print_format",
        "json",
        "-show_format",
        "-show_chapters",
        str(file),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            check=True,
            timeout=120,
            **subprocess_flags(),
        )
    except subprocess.CalledProcessError as exc:
        raise M4BError(
            f"Error: ffprobe failed for '{file}'.\n"
            f"The file may be corrupt or in an unsupported format.\n"
            f"ffprobe stderr: {exc.stderr.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise M4BError(f"Error: ffprobe timed out probing '{file}'.") from exc
    except (FileNotFoundError, OSError) as exc:
        raise M4BError(f"Error: ffprobe executable not found at '{ffprobe}'.") from exc

    try:
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise M4BError(
            f"Error: could not parse ffprobe output for '{file}': {exc}"
        ) from exc

    title = data.get("format", {}).get("tags", {}).get("title") or None
    embedded: list[tuple[float, str | None]] = []
    for raw in data.get("chapters", []):
        try:
            start = float(raw["start_time"])
        except (KeyError, TypeError, ValueError):
            continue  # a marker without a usable start time cannot be placed
        embedded.append((start, raw.get("tags", {}).get("title") or None))
    return _Probe(duration, title, embedded)


def get_duration(file: Path, ffprobe: str) -> float:
    """Return the duration of *file* in seconds using ffprobe JSON output."""
    return _probe_file(file, ffprobe)[0]


def build_chapters(
    files: list[Path],
    ffprobe: str,
    progress_fn: Callable[[int, int, str], None] | None = None,
) -> list[Chapter]:
    """Build a Chapter list from *files* using ffprobe for durations.

    Chapters are indexed sequentially starting at 1, with *start_time* in
    seconds (float).  *source_file* is set to the corresponding input path.

    A file contributes one chapter, titled from its title tag or filename —
    unless it carries its own chapter markers (an M4B, typically), in which
    case those are kept, shifted to the file's position in the book (#28).
    Merging chaptered books must not flatten each one to a single chapter.
    """
    chapters: list[Chapter] = []
    cursor_s: float = 0.0
    total = len(files)

    for i, path in enumerate(files, 1):
        if progress_fn is not None:
            progress_fn(i, total, path.name)
        probe = _probe_file(path, ffprobe)
        file_title = probe.title if probe.title else _strip_chapter_prefix(path.stem)
        for offset, title in _file_chapters(probe, file_title):
            chapters.append(
                Chapter(
                    index=len(chapters) + 1,
                    start_time=cursor_s + offset,
                    title=title,
                    source_file=path,
                    file_offset=offset,
                )
            )
        cursor_s += probe.duration

    return chapters


def _file_chapters(probe: _Probe, file_title: str) -> list[tuple[float, str]]:
    """Return ``(offset_in_file, title)`` for each chapter *probe*'s file adds.

    Embedded markers at or past the end of the audio are dropped, and the
    first kept marker is pinned to 0.0 so no audio at the head of the file
    falls outside a chapter. A marker without a title takes the file's
    title, numbered when the file has more than one chapter.
    """
    markers = sorted(
        (start, title)
        for start, title in probe.chapters
        if 0.0 <= start < probe.duration
    )
    if not markers:
        return [(0.0, file_title)]
    numbered = len(markers) > 1
    result: list[tuple[float, str]] = []
    for n, (start, title) in enumerate(markers, 1):
        fallback = f"{file_title} {n}" if numbered else file_title
        result.append((0.0 if n == 1 else start, title or fallback))
    return result


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


def _escape_ffmeta(value: str) -> str:
    """Escape a value for use on the right-hand side of an FFMETADATA1 line.

    Per ffmpeg's ffmetadata spec, the characters ``=``, ``;``, ``#``, ``\\``,
    and newline are special and must be backslash-escaped. Backslash is
    escaped first so its escape sequence isn't itself re-escaped.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace("=", "\\=")
    value = value.replace(";", "\\;")
    value = value.replace("#", "\\#")
    value = value.replace("\n", "\\\n")
    return value


def write_ffmetadata(
    chapters: list[Chapter],
    meta: BookMetadata,
    dest: Path,
    total_duration_s: float,
) -> None:
    """Write an FFMETADATA1 file with global tags and chapter markers to *dest*.

    Chapter END timestamps are derived from the next chapter's *start_time*;
    the final chapter ends at *total_duration_s*. Values are backslash-escaped
    per the FFMETADATA1 spec (see :func:`_escape_ffmeta`).
    """
    lines: list[str] = [";FFMETADATA1\n"]

    # Global metadata tags
    if meta.title:
        lines.append(f"title={_escape_ffmeta(meta.title)}\n")
    if meta.author:
        lines.append(f"artist={_escape_ffmeta(meta.author)}\n")
    if meta.narrator:
        lines.append(f"composer={_escape_ffmeta(meta.narrator)}\n")
    if meta.genre:
        lines.append(f"genre={_escape_ffmeta(meta.genre)}\n")

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
        lines.append(f"title={_escape_ffmeta(chapter.title)}\n")
        lines.append("\n")

    dest.write_text("".join(lines), encoding="utf-8")
