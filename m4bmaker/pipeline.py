"""Shared pipeline: loading, chapter building, and encoding orchestration.

Both the CLI (``m4bmaker.__main__``) and the GUI (``m4bmaker.gui``) must call
these functions rather than reimplementing the conversion logic.
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from m4bmaker.chapters import build_chapters, get_duration, write_ffmetadata
from m4bmaker.cover import extract_cover_from_audio, find_cover
from m4bmaker.encoder import encode, write_concat_list
from m4bmaker.errors import M4BError
from m4bmaker.metadata import extract_metadata
from m4bmaker.models import Book, BookMetadata, Chapter, PipelineResult
from m4bmaker.preflight import probe_file, run_preflight
from m4bmaker.repair import RepairResult
from m4bmaker.scanner import scan_audio_files
from m4bmaker.utils import find_ffmpeg


def load_audiobook(
    source: Path | list[Path],
    ffprobe: str,
    progress_fn: Callable[[int, int, str], None] | None = None,
) -> Book:
    """Scan, sort, probe, and return a :class:`Book` ready for editing.

    *source* may be:

    - a directory :class:`~pathlib.Path` — all audio files within are
      scanned and naturally sorted.
    - a ``list[Path]`` of audio files — used as-is (caller is responsible
      for ordering).

    Metadata is extracted from the first audio file via ``mutagen``.
    Cover art is auto-detected from image files alongside the audio files
    (only when *source* is a directory).

    The returned :class:`Book` is the central object that flows through the
    editing step before :func:`run_pipeline` encodes it.
    """
    if isinstance(source, list):
        files = source
        cover = None
    else:
        files = scan_audio_files(source)
        cover = find_cover(source)

    raw_meta = extract_metadata(files[0]) if files else {}
    metadata = BookMetadata(
        title=raw_meta.get("title", ""),
        author=raw_meta.get("author", ""),
        narrator=raw_meta.get("narrator", ""),
        genre=raw_meta.get("genre", ""),
    )

    chapters = build_chapters(files, ffprobe, progress_fn=progress_fn)

    # Compute total duration for UI reorder/remove support
    if chapters:
        total_duration = chapters[-1].start_time + get_duration(files[-1], ffprobe)
    else:
        total_duration = 0.0

    # Fallback: extract embedded cover from first audio file if none found on disk
    if cover is None and files:
        cover = extract_cover_from_audio(files[0], find_ffmpeg())

    return Book(
        files=files,
        chapters=chapters,
        metadata=metadata,
        cover=cover,
        total_duration=total_duration,
    )


def _check_codec_uniformity(files: list[Path], ffprobe: str) -> None:
    """Raise :class:`M4BError` if *files* mix audio codecs.

    The concat demuxer requires uniform codec parameters across all inputs;
    a stray file in a different codec (e.g. one .flac among .mp3s) silently
    produces corrupt output rather than failing loudly.
    """
    analysis = run_preflight(files, ffprobe)
    if not analysis.has_codec_mismatch:
        return

    by_codec: dict[str, list[str]] = {}
    for path in files:
        info = probe_file(path, ffprobe)
        codec = info.codec_name or "unknown"
        by_codec.setdefault(codec, []).append(path.name)

    lines = [
        "Error: input files use more than one audio codec — the concat "
        "demuxer requires all files to share one format.",
    ]
    for codec, names in sorted(by_codec.items()):
        lines.append(f"  {codec}: {', '.join(names)}")
    lines.append("Convert all files to a single format before encoding.")
    raise M4BError("\n".join(lines))


def _retime_chapters_after_repair(
    chapters: list[Chapter], active_files: list[Path], ffprobe: str
) -> list[Chapter]:
    """Rebuild chapter start_times cumulatively from *active_files* durations.

    Repair (``-fflags +discardcorrupt``) can shorten a file by dropping
    corrupt frames, so chapter start times computed from pre-repair
    durations drift for every chapter after a repaired file. This re-probes
    each active (post-repair) file and rebuilds start_times from scratch,
    preserving each chapter's index/title but replacing source_file with the
    corresponding active file.

    Only meaningful when chapters derive 1:1 from files (``source_file`` is
    not ``None``); the caller is responsible for checking that precondition.
    """
    retimed: list[Chapter] = []
    cursor_s = 0.0
    for i, chapter in enumerate(chapters):
        source = active_files[i] if i < len(active_files) else chapter.source_file
        retimed.append(
            Chapter(
                index=chapter.index,
                start_time=cursor_s,
                title=chapter.title,
                source_file=source,
            )
        )
        if source is not None:
            cursor_s += get_duration(source, ffprobe)
    return retimed


def run_pipeline(
    book: Book,
    output_path: Path,
    bitrate: str = "96k",
    stereo: bool = False,
    sample_rate: int | None = None,
    cover: Path | None = None,
    progress_callback: Callable[[str, float], None] | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    _tmp_dir: Path | None = None,
    cancel_event: "threading.Event | None" = None,
    repair_result: RepairResult | None = None,
) -> PipelineResult:
    """Encode *book* to *output_path* and return a :class:`PipelineResult`.

    Parameters
    ----------
    book:
        A :class:`Book` produced by :func:`load_audiobook`, optionally with
        metadata and chapter titles already edited interactively.
    output_path:
        Destination ``.m4b`` path.  Parent directories are created if absent.
    bitrate:
        ffmpeg ``-b:a`` value (e.g. ``"96k"``).
    stereo:
        If ``True`` encode in stereo (2 channels), otherwise mono.
    cover:
        Cover image path.  If ``None``, ``book.cover`` is used.
    progress_callback:
        Optional ``(message: str, fraction: float)`` callable.  Called at key
        pipeline stages with a human-readable status and a 0–1 progress
        estimate.
    ffmpeg / ffprobe:
        Executable paths for the two tools.
    _tmp_dir:
        Inject a temporary directory (used in tests to inspect intermediate
        files without relying on :mod:`tempfile`).
    repair_result:
        A :class:`~m4bmaker.repair.RepairResult` already computed by the
        caller (e.g. the CLI's own preflight repair pass). When provided,
        the internal repair pass is skipped and this result is used instead
        — avoids running repair twice. Defaults to ``None``, which runs
        repair internally (unchanged behaviour for the GUI).
    """
    from m4bmaker.repair import apply_repair, run_repair

    effective_cover = cover if cover is not None else book.cover
    channels = 2 if stereo else 1

    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _cb(msg: str, frac: float) -> None:
        if progress_callback is not None:
            progress_callback(msg, frac)

    _cb("Scanning audio files…", 0.0)

    def _run(tmp_path: Path) -> PipelineResult:
        # ── Repair pass ──────────────────────────────────────────────────
        def _repair_cb(msg: str) -> None:
            _cb(msg, 0.0)

        if repair_result is not None:
            active_repair_result = repair_result
        else:
            active_repair_result = run_repair(
                files=book.files,
                tmp_dir=tmp_path,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
                progress_callback=_repair_cb,
            )
        active_files = apply_repair(book.files, active_repair_result)
        if active_repair_result.needed_repair:
            _cb(
                f"Repaired {active_repair_result.repaired} file(s). Continuing…",
                0.0,
            )

        # ── Codec uniformity check ──────────────────────────────────────
        if active_files:
            _check_codec_uniformity(active_files, ffprobe)

        # ── Chapter retiming ────────────────────────────────────────────
        working_chapters = book.chapters
        chapters_from_files = bool(book.chapters) and all(
            ch.source_file is not None for ch in book.chapters
        )
        if active_repair_result.needed_repair and chapters_from_files:
            working_chapters = _retime_chapters_after_repair(
                book.chapters, active_files, ffprobe
            )

        # ── Compute total duration ────────────────────────────────────────
        if working_chapters:
            last_ch = working_chapters[-1]
            if last_ch.source_file is not None:
                last_duration = get_duration(last_ch.source_file, ffprobe)
                total_duration_s = last_ch.start_time + last_duration
            else:
                # Chapters loaded from a --chapters-file have no source_file;
                # the book's total_duration (from load_audiobook) is the
                # authoritative total in that case.
                total_duration_s = book.total_duration
        else:
            total_duration_s = 0.0

        total_ms = int(total_duration_s * 1000)

        # ── Chapter metadata & concat list ───────────────────────────────
        _cb("Generating chapter markers…", 0.0)
        meta_file = tmp_path / "ffmetadata.txt"
        concat_file = tmp_path / "concat.txt"
        write_ffmetadata(working_chapters, book.metadata, meta_file, total_duration_s)
        write_concat_list(active_files, concat_file)

        # ── Encode ───────────────────────────────────────────────────────
        _cb(f"Encoding {len(active_files)} file(s) to M4B…", 0.0)

        def _encode_progress(frac: float) -> None:
            pct = int(frac * 100)
            _cb(f"Encoding audiobook… {pct}%", frac)

        encode(
            concat=concat_file,
            meta_file=meta_file,
            cover=effective_cover,
            output=output_path,
            bitrate=bitrate,
            channels=channels,
            sample_rate=sample_rate,
            ffmpeg=ffmpeg,
            total_ms=total_ms,
            progress_callback=_encode_progress,
            cancel_event=cancel_event,
        )

        _cb("Done.", 1.0)
        return PipelineResult(
            output_file=output_path,
            chapter_count=len(working_chapters),
            duration_seconds=total_duration_s,
        )

    if _tmp_dir is not None:
        return _run(_tmp_dir)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            return _run(Path(tmp))
