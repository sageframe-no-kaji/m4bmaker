"""m4bmaker — entry point: wire all modules and drive the conversion pipeline."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from m4bmaker import __version__
from m4bmaker.chapters import format_chapter_table
from m4bmaker.chapters_file import load_chapters_file
from m4bmaker.cli import parse_args
from m4bmaker.cover import download_cover, find_cover, is_url
from m4bmaker.encoder import _render_bar
from m4bmaker.metadata import extract_metadata, prompt_missing
from m4bmaker.models import BookMetadata, Chapter
from m4bmaker.pipeline import load_audiobook, run_pipeline
from m4bmaker.preflight import format_preflight_report, run_preflight
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
    for ch in chapters:
        value = input(f"  Chapter {ch.index} [{ch.title}]: ").strip()
        edited.append(
            Chapter(
                index=ch.index,
                start_time=ch.start_time,
                title=value if value else ch.title,
                source_file=ch.source_file,
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

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 2. Locate cover image (URL download, auto-detect, or interactive prompt).
        log("Looking for cover art...")
        cover, cover_user_specified = _resolve_cover(
            args.cover, directory, tmp_dir, interactive
        )
        if cover:
            log(f"Cover art: {cover.name}")
        else:
            log("No cover art found — skipping")

        # 2b. Confirm or replace cover interactively.
        if not cover_user_specified:
            cover = _confirm_cover(cover, tmp_dir, interactive)

        # 3. Load audiobook: scan files, extract metadata, build chapters.
        log("Scanning audio files…")
        book = load_audiobook(directory, ffprobe, progress_fn=_probe_progress)
        log(f"Found {len(book.files)} audio file(s)")

        # 3b. Audio preflight analysis.
        log("Analysing audio formats…")
        analysis = run_preflight(book.files, ffprobe)
        print(format_preflight_report(analysis))

        # 3b. Override chapters from --chapters-file if supplied.
        if args.chapters_file:
            book.chapters = load_chapters_file(args.chapters_file)
            log(
                f"Loaded {len(book.chapters)} chapter(s) from {args.chapters_file.name}"
            )
        else:
            log(f"Generated {len(book.chapters)} chapter(s)")

        # Override cover with resolved value (interactive or CLI-supplied).
        book.cover = cover

        # 4. Complete metadata interactively.
        log("Reading metadata...")
        raw_meta = extract_metadata(book.files[0])
        hints = _hints_from_dirname(directory)
        filled = prompt_missing(raw_meta, args, hints=hints)
        book.metadata = BookMetadata(
            title=filled["title"],
            author=filled["author"],
            narrator=filled["narrator"],
            genre=filled.get("genre", ""),
        )
        log(
            f"Title: {book.metadata.title} | Author: {book.metadata.author} "
            f"| Narrator: {book.metadata.narrator}"
            + (f" | Genre: {book.metadata.genre}" if book.metadata.genre else "")
        )

        # 5. Resolve output path.
        meta_dict = {
            "title": book.metadata.title,
            "author": book.metadata.author,
        }
        if args.output:
            output = args.output.resolve()
        else:
            base_dir = args.output_dir.resolve() if args.output_dir else directory
            output = _output_path(base_dir, meta_dict, flat=args.flat)
            output = _confirm_output(output, interactive)
        log(f"Output: {output}")

        # 6. Chapter preview + optional inline editing (interactive only).
        if interactive and sys.stdout.isatty():
            _print_chapter_table(book.chapters)
            answer = input("  Edit chapter titles? [y/N]: ").strip().lower()
            if answer == "y":
                book.chapters = _edit_chapters_inline(book.chapters)

        # 7. Encode via shared pipeline.
        channels = 2 if args.stereo else 1
        log(
            f"Encoding audiobook "
            f"(codec=aac, bitrate={args.bitrate}, "
            f"channels={'stereo' if channels == 2 else 'mono'})..."
        )
        run_pipeline(
            book=book,
            output_path=output,
            bitrate=args.bitrate,
            stereo=args.stereo,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        log(f"Done. Created: {output}")


if __name__ == "__main__":  # pragma: no cover
    main()
