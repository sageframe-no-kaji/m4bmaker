"""ffmpeg concat list writer and audio encode command."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from m4bmaker.errors import EncodeCancelled, M4BError
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


#: EBU R128 targets for spoken word.  Broadcast presets (-23 LUFS) are too
#: quiet for audiobook listening and music presets (-16) too hot; -18 is the
#: value the audiobook tooling ecosystem has settled on.
LOUDNORM_I = "-18"
LOUDNORM_TP = "-2"
LOUDNORM_LRA = "11"

#: Fields ffmpeg's ``loudnorm=print_format=json`` pass must supply for the
#: measurements to be usable in a second pass.  A block missing any of these
#: is treated as malformed rather than partially applied.
_LOUDNORM_REQUIRED_FIELDS = (
    "input_i",
    "input_tp",
    "input_lra",
    "input_thresh",
    "target_offset",
)

#: Non-nested ``{...}`` blocks.  loudnorm's JSON object is flat, so this is
#: sufficient and avoids pulling in a full brace matcher.
_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _build_loudnorm_filter(measured: dict[str, str] | None = None) -> str:
    """Return the ``loudnorm`` filter string for the encode pass.

    Without *measured*, this is a single-pass filter at the spoken-word
    targets.  With *measured* (the output of :func:`measure_loudness`), the
    measured values are supplied so loudnorm can apply ``linear=true`` — a
    single gain adjustment across the whole book rather than the dynamic
    compression the single-pass mode falls back to.
    """
    parts = [f"I={LOUDNORM_I}", f"TP={LOUDNORM_TP}", f"LRA={LOUDNORM_LRA}"]
    if measured is not None:
        parts += [
            f"measured_I={measured['input_i']}",
            f"measured_TP={measured['input_tp']}",
            f"measured_LRA={measured['input_lra']}",
            f"measured_thresh={measured['input_thresh']}",
            f"offset={measured['target_offset']}",
            "linear=true",
        ]
    return "loudnorm=" + ":".join(parts)


def _parse_loudnorm_json(stderr_data: str) -> dict[str, str]:
    """Extract loudnorm's measurement object from ffmpeg's *stderr_data*.

    ffmpeg writes the JSON as a standalone block among ordinary log lines —
    it is neither the whole stream nor reliably the last thing on it
    (ffmpeg 8.x emits ``[out#0/null ...]`` and a ``size=`` summary after it).
    So the block is located rather than assumed positionally: candidate
    ``{...}`` spans are tried newest-first and the first one that parses and
    carries the expected fields wins.

    Raises:
        M4BError: if no such block is present, or the one found is malformed.
    """
    for match in reversed(list(_JSON_BLOCK_RE.finditer(stderr_data))):
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        # _JSON_BLOCK_RE only matches ``{...}``, so a successful parse is
        # always a dict — no isinstance guard is reachable here.
        if any(field not in parsed for field in _LOUDNORM_REQUIRED_FIELDS):
            continue
        return {str(k): str(v) for k, v in parsed.items()}

    tail = "\n".join(stderr_data.strip().splitlines()[-30:])
    raise M4BError(
        "Error: could not read loudness measurements from ffmpeg.\n"
        "Expected a JSON block from the loudnorm filter containing "
        f"{', '.join(_LOUDNORM_REQUIRED_FIELDS)}.\n"
        f"stderr (last 30 lines):\n{tail}"
    )


def measure_loudness(
    concat: Path,
    ffmpeg: str,
    cancel_event: "threading.Event | None" = None,
) -> dict[str, str]:
    """Measure the loudness of the assembled audio and return the raw fields.

    Runs ffmpeg over the concat input with ``loudnorm`` in ``print_format=json``
    mode and a null output — decoding the whole book without encoding it — then
    parses the measurement block ffmpeg writes to **stderr**.  The result is
    passed to :func:`encode` as *loudnorm_measured* for the second pass.

    This is the analysis-pass shape: run ffmpeg over the concat list, read
    stderr, stay cancellable, return parsed data.

    Raises:
        M4BError: if ffmpeg is missing, exits non-zero, or writes no usable
            measurement block.
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
        str(concat),
        "-af",
        _build_loudnorm_filter() + ":print_format=json",
        "-nostdin",
        "-f",
        "null",
        "-",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            **subprocess_flags(),
        )
    except FileNotFoundError as exc:
        raise M4BError(f"Error: ffmpeg executable not found at '{ffmpeg}'.") from exc

    stderr_buf: list[str] = []

    def _read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_buf.append(line)

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

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
        stderr_thread.join()

    if cancelled:
        proc.wait()
        raise EncodeCancelled("Encoding cancelled.")

    stderr_data = "".join(stderr_buf)

    if proc.returncode != 0:
        tail = "\n".join(stderr_data.strip().splitlines()[-30:])
        raise M4BError(
            f"Error: ffmpeg exited with code {proc.returncode} during the "
            f"loudness measurement pass.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr (last 30 lines):\n{tail}"
        )

    return _parse_loudnorm_json(stderr_data)


def write_concat_list(files: list[Path], dest: Path) -> None:
    """Write an ffmpeg concat demuxer file to *dest*.

    Uses unquoted paths with backslash-escaped special characters.  ffmpeg's
    concat demuxer (tested up to 8.x) does not treat ``\'`` inside a
    single-quoted string as an escape — the apostrophe terminates the string.
    The only reliable approach is to leave paths unquoted and escape each
    special character individually with a leading backslash.

    Raises :class:`~m4bmaker.errors.M4BError` if a resolved path contains a
    newline, carriage return, or tab: the concat demuxer's escaping for
    those characters is unverified (see the warning below), so rather than
    risk silently mis-parsing the list, the file is rejected and the user is
    told to rename it.

    .. warning::
        Unit tests for this function can only assert on the *string content* of
        the concat file, not on ffmpeg's actual parsing of it.  If you change
        the escaping strategy, verify with a live ffmpeg run against a path that
        contains the characters you are trying to escape.  This was learned the
        hard way: the original ``file 'path\\'s'`` approach passed all unit
        tests but silently truncated the path at runtime (issue #8).
    """
    lines: list[str] = []
    for path in files:
        posix_path = path.resolve().as_posix()
        if any(c in posix_path for c in ("\n", "\r", "\t")):
            raise M4BError(
                f"File path contains a newline, carriage return, or tab "
                f"character that cannot be safely written to the ffmpeg "
                f"concat list: {path}\n"
                f"Please rename the file (or its containing directory) to "
                f"remove that character."
            )
        # Backslash must be escaped first to avoid double-escaping.
        escaped = (
            posix_path.replace("\\", "\\\\")
            .replace(" ", "\\ ")
            .replace("'", "\\'")
            .replace('"', '\\"')
            .replace("#", "\\#")
        )
        lines.append(f"file {escaped}\n")
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
    *,
    normalize: bool = False,
    loudnorm_measured: dict[str, str] | None = None,
) -> None:
    """Run ffmpeg to produce the final .m4b file with live progress bar.

    Stream mapping:
      - Input 0: concat demuxer (audio)
      - Input 1: FFMETADATA file (chapters + global tags)
      - Input 2 (optional): cover image

    The output is an AAC-encoded M4B (MP4 audiobook) container.
    ffmpeg progress data is read from stdout via ``-progress pipe:1``.

    When *normalize* is true an EBU R128 ``loudnorm`` filter is applied at
    spoken-word targets.  Supplying *loudnorm_measured* (from
    :func:`measure_loudness`) switches it to the accurate two-pass form.  When
    *normalize* is false no filter is added and the command is unchanged.

    Encoding is atomic: ffmpeg writes to a sibling ``<output>.partial`` path
    in the same directory, which is moved onto *output* via :func:`os.replace`
    only after a successful (returncode 0) run. On failure, cancellation, or
    a ``KeyboardInterrupt``, the partial file is removed and any pre-existing
    good file at *output* is left untouched.

    Raises:
        M4BError: if the ffmpeg executable is missing or exits non-zero.
        EncodeCancelled: if *cancel_event* fires while ffmpeg is running.
    """
    partial = output.with_name(output.name + ".partial")

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
        # Nothing is emitted when normalize is false, so the default command
        # is byte-for-byte what it was before loudness support existed.
        *(["-af", _build_loudnorm_filter(loudnorm_measured)] if normalize else []),
        "-metadata",
        "stik=2",  # iTunes media type: Audiobook (required by Apple Books)
        "-brand",
        "M4B ",  # ftyp major brand — required for iOS Books to recognise as audiobook
        "-movflags",
        "+faststart",  # optimise for streaming
        "-progress",
        "pipe:1",  # write progress key=value pairs to stdout
        "-nostdin",  # do not read from stdin
        "-f",
        "mp4",  # explicit muxer — the ".partial" staging suffix defeats
        # ffmpeg's extension-based auto-detection, which would otherwise
        # fail with "Unable to choose an output format".
        str(partial),
    ]

    stderr_buf: list[str] = []
    done = threading.Event()

    def _cleanup_partial() -> None:
        partial.unlink(missing_ok=True)

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

    cancelled = False
    try:
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                proc.kill()
                break
            time.sleep(0.1)
    except BaseException:
        # Covers KeyboardInterrupt as well as any other propagating
        # exception: the child process and partial output must not survive.
        proc.kill()
        proc.wait()
        _cleanup_partial()
        raise
    finally:
        done.set()
        reader.join()
        stderr_thread.join()

    if cancelled:
        proc.wait()
        _cleanup_partial()
        raise EncodeCancelled("Encoding cancelled.")

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
        _cleanup_partial()
        stderr_data = "".join(stderr_buf)
        tail = "\n".join(stderr_data.strip().splitlines()[-30:])
        raise M4BError(
            f"Error: ffmpeg exited with code {proc.returncode}.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr (last 30 lines):\n{tail}"
        )

    os.replace(partial, output)
