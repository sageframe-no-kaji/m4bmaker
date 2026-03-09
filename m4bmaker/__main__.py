"""m4bmaker — entry point: wire all modules and drive the conversion pipeline."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from m4bmaker import __version__
from m4bmaker.chapters import (
    Chapter,
    build_chapters,
    format_chapter_table,
    write_ffmetadata,
)
from m4bmaker.cli import parse_args
from m4bmaker.cover import download_cover, find_cover, is_url
from m4bmaker.encoder import _render_bar, encode, write_concat_list
from m4bmaker.metadata import extract_metadata, prompt_missing
from m4bmaker.scanner import scan_audio_files
from m4bmaker.utils import find_ffmpeg, find_ffprobe, log


def _safe(s: str) -> str:
    """Sanitise a string for use as a filename or directory component."""
    return s.replace("/", "-").replace("\x00", "")


def _output_path(base_dir: Path, meta: dict[str, str], flat: bool = False) -> Path:
    """Derive the output .m4b path from metadata.

    Default (organized): ``base_dir/Author/Title/Author - Title.m4b``
    With *flat*:         ``base_dir/Author - Title.m4b``
    """
    title = meta.get("title", "").strip()
    author = meta.get("author", "").strip()

    if title and author:
        stem = f"{_safe(author)} - {_safe(title)}"
        if flat:
            return base_dir / f"{stem}.m4b"
        return base_dir / _safe(author) / _safe(title) / f"{stem}.m4b"
    elif title:
        stem = _safe(title)
        if flat:
            return base_dir / f"{stem}.m4b"
        return base_dir / stem / f"{stem}.m4b"
    else:
        return base_dir / "audiobook.m4b"


def _confirm_output(proposed: Path, interactive: bool) -> Path:
    """Confirm or override the output path interactively."""
    if not interactive:
        return proposed
    value = input(f"Output [{proposed}]: ").strip()
    if not value:
        return proposed
    return Path(value).expanduser().resolve()


def _print_chapter_table(chapters: list[Chapter]) -> None:
    """Print the chapter preview table to stdout (TTY + interactive only)."""
    print(f"\n  Chapters ({len(chapters)})")
    print(format_chapter_table(chapters))
    print()


def _edit_chapters_inline(chapters: list[Chapter]) -> list[Chapter]:
    """Interactively edit chapter titles one by one.

    For each chapter the current title is shown as a prefill; pressing Enter
    keeps it, typing a new value replaces it.
    """
    edited: list[Chapter] = []
    for i, ch in enumerate(chapters, 1):
        value = input(f"  Chapter {i} [{ch.title}]: ").strip()
        edited.append(
            Chapter(
                title=value if value else ch.title,
                start_ms=ch.start_ms,
                end_ms=ch.end_ms,
            )
        )
    return edited


def _hints_from_dirname(directory: Path) -> dict[str, str]:
    """Extract title/author hints from an 'Author - Title' directory name."""
    name = directory.name
    if " - " in name:
        author, _, title = name.partition(" - ")
        return {"author": author.strip(), "title": title.strip()}
    return {"title": name.strip()}


def _probe_progress(i: int, n: int, name: str) -> None:
    """Display a progress bar while probing file durations."""
    if not sys.stdout.isatty():
        log(f"  [{i}/{n}] {name}")
        return
    bar = _render_bar(i / n, width=30)
    max_name = 35
    disp = (name[: max_name - 1] + "\u2026") if len(name) > max_name else name
    sys.stdout.write(f"\r  Probing {bar}  {i}/{n}  {disp:<{max_name}}\033[K")
    sys.stdout.flush()
    if i == n:
        sys.stdout.write("\n")
        sys.stdout.flush()


def _resolve_cover(
    cover_arg: str | None,
    directory: Path,
    tmp_dir: Path,
    interactive: bool,
) -> tuple[Path | None, bool]:
    """Resolve the cover image from CLI argument, directory scan, or user prompt.

    Returns ``(cover, user_specified)`` where *user_specified* is ``True`` when
    the user explicitly provided a URL or path (via CLI or interactive prompt),
    indicating that no further confirmation is needed.

    Resolution order:
    1. *cover_arg* provided — URL: download (retry interactively on failure);
       local path: passed directly to :func:`find_cover`.
    2. Auto-detect a single image file in *directory*.
    3. If *interactive*, prompt the user for a URL or local path.
    """
    if cover_arg is not None:
        if is_url(cover_arg):
            return _fetch_cover_url(cover_arg, tmp_dir, interactive), True
        return find_cover(directory, cli_override=Path(cover_arg).expanduser()), True

    cover = find_cover(directory)
    if cover is not None:
        return cover, False  # auto-detected — needs confirmation

    if interactive:
        return _prompt_cover(tmp_dir), True  # user explicitly typed URL/path
    return None, False


def _fetch_cover_url(url: str, tmp_dir: Path, interactive: bool) -> Path | None:
    """Download a cover image URL.

    On failure, prompt for retry if *interactive*; otherwise exit.
    """
    pending: str | None = url
    while True:
        if pending is not None:
            try:
                return download_cover(pending, tmp_dir)
            except Exception as exc:
                log(f"Cover download failed: {exc}")
        if not interactive:
            sys.exit(1)
        source = input(
            "Enter a different URL or local path (or press Enter to skip): "
        ).strip()
        if not source:
            return None
        if is_url(source):
            pending = source
        else:
            path = Path(source).expanduser()
            if path.is_file():
                return path
            log(f"File not found: {path} — please try again.")
            pending = None


def _prompt_cover(tmp_dir: Path) -> Path | None:
    """Interactively prompt for a cover image URL or local path.

    Loops until a valid source is provided or the user presses Enter to skip.
    """
    while True:
        source = input(
            "Enter URL or local path for cover art (or press Enter to skip): "
        ).strip()
        if not source:
            return None
        try:
            if is_url(source):
                return download_cover(source, tmp_dir)
            path = Path(source).expanduser()
            if path.is_file():
                return path
            log(f"File not found: {path} — please try again.")
        except Exception as exc:
            log(f"Cover error: {exc} — please try again.")


def _confirm_cover(
    cover: Path | None,
    tmp_dir: Path,
    interactive: bool,
) -> Path | None:
    """Confirm or replace the selected cover image interactively."""
    if not interactive:
        return cover
    while True:
        display = str(cover) if cover else "none"
        value = input(f"Cover image [{display}]: ").strip()
        if not value:
            return cover  # confirmed as-is
        if value.lower() in ("none", "skip"):
            return None
        try:
            if is_url(value):
                return download_cover(value, tmp_dir)
            path = Path(value).expanduser()
            if path.is_file():
                return path
            log(f"File not found: {path} — please try again.")
        except Exception as exc:
            log(f"Cover error: {exc} — please try again.")


def main() -> None:
    args = parse_args()
    directory: Path = args.directory.resolve()
    interactive = not args.no_prompt

    log(f"m4bmaker {__version__}")
    log(f"Working directory: {directory}")

    # 1. Detect tool locations (exits early if missing).
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()

    # 2. Scan for audio files.
    log("Scanning directory...")
    files = scan_audio_files(directory)
    log(f"Found {len(files)} audio file(s)")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 3. Locate cover image (URL download, auto-detect, or interactive prompt).
        log("Looking for cover art...")
        cover, cover_user_specified = _resolve_cover(
            args.cover, directory, tmp_dir, interactive
        )
        if cover:
            log(f"Cover art: {cover.name}")
        else:
            log("No cover art found — skipping")

        # 3b. Confirm or replace cover interactively (skip if user already provided it).
        if not cover_user_specified:
            cover = _confirm_cover(cover, tmp_dir, interactive)

        # 4. Read and complete metadata.
        log("Reading metadata...")
        meta = extract_metadata(files[0])
        hints = _hints_from_dirname(directory)
        meta = prompt_missing(meta, args, hints=hints)
        log(
            f"Title: {meta['title']} | Author: {meta['author']} "
            f"| Narrator: {meta['narrator']}"
            + (f" | Genre: {meta['genre']}" if meta.get("genre") else "")
        )

        # 5. Resolve output path.
        if args.output:
            output = args.output.resolve()
        else:
            base_dir = args.output_dir.resolve() if args.output_dir else directory
            output = _output_path(base_dir, meta, flat=args.flat)
            output = _confirm_output(output, interactive)
        output.parent.mkdir(parents=True, exist_ok=True)
        log(f"Output: {output}")

        # 6. Build chapter list and write FFMETADATA.
        log("Generating chapter markers...")
        meta_file = tmp_dir / "ffmetadata.txt"
        concat_file = tmp_dir / "concat.txt"

        chapters = build_chapters(
            files,
            ffprobe,
            progress_fn=_probe_progress,
        )
        log(f"Generated {len(chapters)} chapter(s)")

        # 6b. Chapter preview + optional inline editing (interactive only).
        if interactive and sys.stdout.isatty():
            _print_chapter_table(chapters)
            answer = input("  Edit chapter titles? [y/N]: ").strip().lower()
            if answer == "y":
                chapters = _edit_chapters_inline(chapters)

        write_ffmetadata(chapters, meta, meta_file)

        # 7. Write concat list.
        write_concat_list(files, concat_file)

        # 8. Encode.
        total_ms = chapters[-1].end_ms if chapters else 0
        channels = 2 if args.stereo else 1
        log(
            f"Encoding audiobook "
            f"(codec=aac, bitrate={args.bitrate}, "
            f"channels={'stereo' if channels == 2 else 'mono'})..."
        )
        encode(
            concat=concat_file,
            meta_file=meta_file,
            cover=cover,
            output=output,
            bitrate=args.bitrate,
            channels=channels,
            ffmpeg=ffmpeg,
            total_ms=total_ms,
        )

    log(f"Done. Output: {output}")


if __name__ == "__main__":
    main()
