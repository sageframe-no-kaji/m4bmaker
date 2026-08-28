"""Silence-based chapter detection.

Chapters normally come from filenames (:mod:`m4bmaker.chapters`). That fails
for the two shapes users most often have: a CD rip whose tracks are named
``Track 07`` across six discs, and a single large file with no internal marks.
This module derives boundaries from the audio itself instead.

Detection is heuristic and **will** be imperfect — it finds breaks that are not
chapters and misses ones that are. That is acceptable because correction is
cheap and already built: the chapter table supports rename, merge, split, and
millisecond editing, and the player lets the user scrub a boundary and hear
whether it lands. Detect roughly, fix visually, convert. Nothing here writes to
a file; results populate the table for review.

The ffmpeg call follows the analysis-pass shape established by
:func:`m4bmaker.encoder.measure_loudness` — run ffmpeg over the concat list,
parse what it writes to stderr, stay cancellable, report progress off the UI
thread.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from m4bmaker.errors import EncodeCancelled, M4BError
from m4bmaker.models import Chapter
from m4bmaker.utils import subprocess_flags

#: Default noise floor. Anything quieter than this counts as silence.
DEFAULT_THRESHOLD_DB = -30.0

#: Default minimum length of a silence span, in seconds, before it is reported.
DEFAULT_MIN_SILENCE = 1.5

#: Default minimum chapter length, in seconds. A dramatic pause mid-sentence
#: must not become a four-second chapter.
DEFAULT_MIN_CHAPTER = 30.0

_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")

#: ffmpeg's end-of-run summary, e.g. ``size=N/A time=00:00:19.00 bitrate=N/A``.
#: Used to close a silence span that runs to the end of the audio.
_TIME_RE = re.compile(r"time=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


def _parse_eof_seconds(stderr_data: str) -> float | None:
    """Return the last ``time=`` position ffmpeg reported, in seconds.

    ffmpeg prints a running position and a final summary line; the last one is
    where the audio ended. Returns ``None`` if no such line is present, in
    which case an unterminated silence span cannot be placed.
    """
    matches = _TIME_RE.findall(stderr_data)
    if not matches:
        return None
    hours, minutes, seconds = matches[-1]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_silence_spans(stderr_data: str) -> list[tuple[float, float]]:
    """Extract ``(start, end)`` silence spans, in seconds, from ffmpeg stderr.

    ffmpeg emits ``silence_start`` and ``silence_end`` on separate lines, and
    ordinary log lines are freely interleaved between them, so the two are
    matched by order rather than by adjacency.

    A trailing ``silence_start`` with no matching ``silence_end`` — the audio
    ended mid-silence, which is common, since books often end on a fade — is
    closed at the end of the file.
    """
    starts: list[float] = []
    ends: list[float] = []
    for line in stderr_data.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            starts.append(float(start_match.group(1)))
        end_match = _SILENCE_END_RE.search(line)
        if end_match:
            ends.append(float(end_match.group(1)))

    spans = [(start, end) for start, end in zip(starts, ends)]

    if len(starts) > len(ends):
        eof = _parse_eof_seconds(stderr_data)
        if eof is not None and eof > starts[len(ends)]:
            spans.append((starts[len(ends)], eof))

    return spans


def detect_silence(
    source: Path,
    ffmpeg: str,
    threshold_db: float = DEFAULT_THRESHOLD_DB,
    min_duration: float = DEFAULT_MIN_SILENCE,
    cancel_event: "threading.Event | None" = None,
    progress_callback: Callable[[float], None] | None = None,
) -> list[tuple[float, float]]:
    """Find silence spans in the assembled audio described by *source*.

    *source* is an ffmpeg **concat list** — the same input :func:`encode` and
    :func:`m4bmaker.encoder.measure_loudness` take — so the timestamps returned
    are relative to the whole book rather than to any one file. A single-file
    book is a one-line list.

    *progress_callback* receives the number of **seconds of audio analysed so
    far**, not a fraction: this function does not know the book's total
    duration, and the caller that does can turn the two into a percentage.

    Args:
        source: Path to the ffmpeg concat list.
        ffmpeg: Path to the ffmpeg executable.
        threshold_db: Noise floor in dB; quieter than this counts as silence.
        min_duration: Shortest silence span to report, in seconds.
        cancel_event: Set to abort the analysis.
        progress_callback: Called with seconds analysed as the run proceeds.

    Returns:
        ``(start, end)`` spans in seconds, in order.

    Raises:
        M4BError: if ffmpeg is missing or exits non-zero.
        EncodeCancelled: if *cancel_event* fires while ffmpeg is running.
    """
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(source),
        "-af",
        f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-progress",
        "pipe:1",
        "-nostdin",
        "-f",
        "null",
        "-",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            **subprocess_flags(),
        )
    except FileNotFoundError as exc:
        raise M4BError(f"Error: ffmpeg executable not found at '{ffmpeg}'.") from exc

    stderr_buf: list[str] = []
    done = threading.Event()

    def _read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_buf.append(line)

    def _read_progress() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            if done.is_set():
                break
            line = raw.strip()
            if not line.startswith("out_time_ms=") or progress_callback is None:
                continue
            try:
                analysed_ms = max(0, int(line.split("=", 1)[1]) // 1000)
            except ValueError:
                continue
            progress_callback(analysed_ms / 1000.0)

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    progress_thread = threading.Thread(target=_read_progress, daemon=True)
    stderr_thread.start()
    progress_thread.start()

    cancelled = False
    try:
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                proc.kill()
                break
            time.sleep(0.1)
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        done.set()
        stderr_thread.join()
        progress_thread.join()

    if cancelled:
        proc.wait()
        raise EncodeCancelled("Chapter detection cancelled.")

    stderr_data = "".join(stderr_buf)

    if proc.returncode != 0:
        tail = "\n".join(stderr_data.strip().splitlines()[-30:])
        raise M4BError(
            f"Error: ffmpeg exited with code {proc.returncode} during silence "
            f"detection.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr (last 30 lines):\n{tail}"
        )

    return parse_silence_spans(stderr_data)


def silence_to_chapters(
    spans: list[tuple[float, float]],
    total_duration: float,
    min_chapter_length: float = DEFAULT_MIN_CHAPTER,
) -> list[Chapter]:
    """Convert silence *spans* into chapter markers.

    Three rules, each of which matters:

    - A chapter begins where a silence span **ends**, not where it begins. The
      pause belongs to the chapter before it, the way a reader hears it.
    - The first chapter always starts at ``0.0``, whatever leading silence the
      file opens with.
    - A boundary that would produce a chapter shorter than *min_chapter_length*
      is dropped, measured against the last boundary actually kept — so a run
      of short pauses collapses instead of accumulating.

    Titles are ``Chapter 1``, ``Chapter 2``, … because silence carries no
    names. The returned chapters have ``source_file=None``: they are positions
    within the assembled book, not per-file markers.
    """
    boundaries = [0.0]
    for _start, end in spans:
        if end - boundaries[-1] < min_chapter_length:
            continue
        # A boundary so close to the end that the final chapter would be a
        # stub is no more useful than one that crowds its predecessor. Skipped
        # when the total is unknown (0.0) — otherwise every boundary would look
        # like it sat past the end of the book and all of them would be cut.
        if total_duration > 0 and total_duration - end < min_chapter_length:
            continue
        boundaries.append(end)

    return [
        Chapter(index=i, start_time=start, title=f"Chapter {i}", source_file=None)
        for i, start in enumerate(boundaries, start=1)
    ]
