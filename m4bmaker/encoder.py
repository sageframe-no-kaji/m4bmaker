"""ffmpeg concat list writer and audio encode command."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def write_concat_list(files: list[Path], dest: Path) -> None:
    """Write an ffmpeg concat demuxer file to *dest*.

    Each path is escaped: single-quotes inside filenames are doubled,
    and the whole path is wrapped in single-quotes, as required by the
    ffmpeg concat demuxer format.
    """
    lines: list[str] = []
    for path in files:
        # Escape single-quotes inside the path (ffmpeg concat format requires it).
        escaped = str(path.resolve()).replace("'", "'\\''")
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
) -> None:
    """Run ffmpeg to produce the final .m4b file.

    Stream mapping:
      - Input 0: concat demuxer (audio)
      - Input 1: FFMETADATA file (chapters + global tags)
      - Input 2 (optional): cover image

    The output is an AAC-encoded M4B (MP4 audiobook) container.
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
        cmd += [
            "-map",
            "2:v",  # map cover image from input 2
            "-c:v",
            "copy",
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
        "-movflags",
        "+faststart",  # optimise for streaming
        str(output),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit(f"Error: ffmpeg executable not found at '{ffmpeg}'.")

    if result.returncode != 0:
        sys.exit(
            f"Error: ffmpeg exited with code {result.returncode}.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr:\n{result.stderr.strip()}"
        )
