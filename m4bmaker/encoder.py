"""ffmpeg concat list writer and audio encode command."""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from pathlib import Path

from m4bmaker.utils import subprocess_flags


def _format_ms(ms: int) -> str:
    """Format a millisecond count as H:MM:SS."""
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


def _render_bar(fraction: float, width: int = 30) -> str:
    """Return a Unicode block progress bar string including brackets."""
    filled = round(min(1.0, max(0.0, fraction)) * width)
    return "[" + "\u2588" * filled + "\u2591" * (width - filled) + "]"


def _progress_reader(
    stdout: Iterable[str],
    total_ms: int,
    done: threading.Event,
    progress_callback: Callable[[float], None] | None = None,
) -> None:
    """Read ffmpeg -progress lines and paint a live progress bar on stdout."""
    bar_width = 30
    for raw in stdout:
        if done.is_set():
            break
        line: str = raw
        line = line.strip()
        if not line.startswith("out_time_ms="):
            continue
        try:
            current_ms = max(0, int(line.split("=", 1)[1]) // 1000)
        except ValueError:
            continue
        if total_ms > 0:
            frac = min(1.0, current_ms / total_ms)
            if progress_callback is not None:
                progress_callback(frac)
            if sys.stdout is not None and sys.stdout.isatty():
                bar = _render_bar(frac, bar_width)
                pct = int(frac * 100)
                elapsed = _format_ms(current_ms)
                total_str = _format_ms(total_ms)
                sys.stdout.write(
                    f"\r  Encoding {bar}  {pct:3d}%  {elapsed} / {total_str}\033[K"
                )
                sys.stdout.flush()


def write_concat_list(files: list[Path], dest: Path) -> None:
    """Write an ffmpeg concat demuxer file to *dest*.

    Each path is escaped: single-quotes inside filenames are doubled,
    and the whole path is wrapped in single-quotes, as required by the
    ffmpeg concat demuxer format.
    """
    lines: list[str] = []
    for path in files:
        # Use forward-slash paths (as_posix) so ffmpeg's concat demuxer doesn't
        # misinterpret Windows backslashes as escape sequences.
        # Escape single-quotes and backslashes per ffmpeg concat demuxer rules.
        posix_path = path.resolve().as_posix()
        escaped = posix_path.replace("'", "\\'")
        lines.append(f"file '{escaped}'\n")
    dest.write_text("".join(lines), encoding="utf-8")


def encode(
    concat: Path,
    meta_file: Path,
    cover: Path | None,
    output: Path,
    bitrate: str,
    channels: int,
    ffmpeg: str,
    total_ms: int = 0,
    sample_rate: int | None = None,
    progress_callback: Callable[[float], None] | None = None,
    cancel_event: "threading.Event | None" = None,
) -> None:
    """Run ffmpeg to produce the final .m4b file with live progress bar.

    Stream mapping:
      - Input 0: concat demuxer (audio)
      - Input 1: FFMETADATA file (chapters + global tags)
      - Input 2 (optional): cover image

    The output is an AAC-encoded M4B (MP4 audiobook) container.
    ffmpeg progress data is read from stdout via ``-progress pipe:1``.
    """
    cmd: list[str] = [
        ffmpeg,
        "-y",  # overwrite without asking
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat),  # input 0: audio concat list
        "-i",
        str(meta_file),  # input 1: FFMETADATA chapters
    ]

    if cover is not None:
        cmd += ["-i", str(cover)]  # input 2: cover art

    cmd += [
        "-map_metadata",
        "1",  # apply global tags + chapters from input 1
        "-map_chapters",
        "1",  # apply chapter markers from input 1
        "-map",
        "0:a",  # map audio from input 0
    ]

    if cover is not None:
        # Determine whether the cover can be muxed as-is or needs transcoding.
        # M4B (MP4) only supports JPEG and PNG cover art; formats like WebP
        # must be transcoded to MJPEG.
        _ext = Path(cover).suffix.lower()
        _copy_cover = _ext in {".jpg", ".jpeg", ".png"}
        cmd += [
            "-map",
            "2:v",  # map cover image from input 2
            "-c:v",
            "copy" if _copy_cover else "mjpeg",
            "-disposition:v",
            "attached_pic",
        ]

    cmd += [
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-ac",
        str(channels),
        *(["-ar", str(sample_rate)] if sample_rate is not None else []),
        "-metadata",
        "stik=2",  # iTunes media type: Audiobook (required by Apple Books)
        "-brand",
        "M4B ",  # ftyp major brand — required for iOS Books to recognise as audiobook
        "-movflags",
        "+faststart",  # optimise for streaming
        "-progress",
        "pipe:1",  # write progress key=value pairs to stdout
        "-nostdin",  # do not read from stdin
        str(output),
    ]

    stderr_buf: list[str] = []
    done = threading.Event()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            **subprocess_flags(),
        )
    except FileNotFoundError:
        sys.exit(f"Error: ffmpeg executable not found at '{ffmpeg}'.")

    def _read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_buf.append(line)

    reader = threading.Thread(
        target=_progress_reader,
        args=(proc.stdout, total_ms, done, progress_callback),
        daemon=True,
    )
    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    reader.start()
    stderr_thread.start()

    try:
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                break
            threading.Event().wait(0.1)
    finally:
        done.set()
        reader.join()
        stderr_thread.join()

    if sys.stdout is not None and sys.stdout.isatty():
        if proc.returncode == 0 and total_ms > 0:
            bar = _render_bar(1.0, 30)
            total_str = _format_ms(total_ms)
            sys.stdout.write(
                f"\r  Encoding {bar}  100%  {total_str} / {total_str}\033[K\n"
            )
        else:
            sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    if proc.returncode != 0:
        stderr_data = "".join(stderr_buf)
        sys.exit(
            f"Error: ffmpeg exited with code {proc.returncode}.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr:\n{stderr_data.strip()}"
        )
