"""Load and rewrite chapter metadata in existing .m4b files without re-encoding.

Uses ``ffprobe -show_chapters`` to read current chapter markers and
``ffmpeg -c copy`` to write updated chapters back into the container
without touching the audio stream.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from m4bmaker.chapters import write_ffmetadata
from m4bmaker.errors import M4BError
from m4bmaker.models import BookMetadata, Chapter
from m4bmaker.utils import subprocess_flags


def load_m4b_chapters(path: Path, ffprobe: str) -> tuple[list[Chapter], float]:
    """Return ``(chapters, total_duration_s)`` from an existing .m4b file.

    Uses ``ffprobe -show_chapters -show_format``.  If the file contains no
    chapter markers an empty list is returned (total_duration is still set).
    Raises :class:`~m4bmaker.errors.M4BError` if ffprobe fails.
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
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", check=True, **subprocess_flags()
        )
    except subprocess.CalledProcessError as exc:
        raise M4BError(f"Error reading '{path.name}': {exc.stderr.strip()}") from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise M4BError(
            f"Error parsing ffprobe output for '{path.name}': {exc}"
        ) from exc

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


def _write_narrator_atom(dest: Path, narrator: str) -> None:
    """Write *narrator* into the Apple ``©nrt`` atom via mutagen.

    Apple Books reads narrator from ``©nrt``, not ``©wrt`` (composer) — ffmpeg
    has no direct way to target ``©nrt``, so it's written as a follow-up
    mutagen pass after the ffmpeg run succeeds. Best-effort: any mutagen
    failure here must not fail an otherwise-successful save, so callers
    should wrap this in a broad ``try/except``.
    """
    from mutagen.mp4 import MP4

    audio: Any = MP4(str(dest))  # type: ignore[no-untyped-call]
    if audio.tags is None:
        audio.add_tags()
    audio.tags["\xa9nrt"] = [narrator]
    audio.save()


def save_m4b_chapters(
    source: Path,
    chapters: list[Chapter],
    total_duration: float,
    dest: Path,
    ffmpeg: str,
    *,
    metadata: BookMetadata | None = None,
) -> None:
    """Rewrite *dest* with updated chapter metadata, keeping audio intact.

    *source* and *dest* may be the same path — an intermediate temp file is
    used in that case so the original is not corrupted on failure. The
    in-place case streams the temp output onto *dest* via a sibling tmp file
    plus :func:`os.replace`, rather than reading the (often large) file
    fully into memory.

    When *metadata* is provided, all four ``-metadata`` flags are always
    passed to ffmpeg — including empty values, which is how ffmpeg clears a
    tag. Omitting empty values would silently keep the old tag even after
    the user cleared the field in the GUI. ``metadata=None`` writes no
    ``-metadata`` flags (behaviour unchanged).

    If *metadata* has a non-empty narrator, the Apple ``©nrt`` atom is also
    written (via mutagen) after a successful ffmpeg run, since Apple Books
    reads narrator from ``©nrt`` rather than ``©wrt``.

    Raises :class:`~m4bmaker.errors.M4BError` if ffmpeg fails.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        meta_file = tmp_dir / "chapters.ffmetadata"
        write_ffmetadata(
            chapters, metadata or BookMetadata(), meta_file, total_duration
        )

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
            "0",  # preserve all metadata from source; explicit flags below override
            "-map_chapters",
            "1",  # chapters come from the ffmetadata file
            "-c",
            "copy",
        ]
        # Override specific metadata fields with the values provided by the
        # caller. Using explicit -metadata flags (not relying on the
        # ffmetadata global section) ensures changes made in the GUI are
        # always written to the output file — including clearing a field:
        # an empty -metadata value tells ffmpeg to clear the tag, so empty
        # values must be passed too, not skipped.
        if metadata is not None:
            for flag, value in [
                ("title", metadata.title),
                ("artist", metadata.author),
                ("composer", metadata.narrator),
                ("genre", metadata.genre),
            ]:
                cmd += ["-metadata", f"{flag}={value}"]
        cmd += [
            "-metadata",
            "stik=2",  # iTunes audiobook type — required for iOS Books
            "-brand",
            "M4B ",  # ftyp major brand — required for iOS Books
            str(out_path),
        ]
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                check=True,
                timeout=600,
                **subprocess_flags(),
            )
        except subprocess.CalledProcessError as exc:
            raise M4BError(
                f"Error saving chapters to '{dest.name}': {exc.stderr.strip()}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise M4BError(
                f"Error: ffmpeg timed out saving chapters to '{dest.name}'."
            ) from exc

        if in_place:
            replace_tmp = dest.with_name(dest.name + ".tmp_replace")
            shutil.copyfile(out_path, replace_tmp)
            os.replace(replace_tmp, dest)

        if metadata is not None and metadata.narrator:
            try:
                _write_narrator_atom(dest, metadata.narrator)
            except Exception:  # noqa: BLE001
                # Narrator atom write is best-effort; the chapter/tag save
                # above already succeeded and must not be rolled back.
                pass
