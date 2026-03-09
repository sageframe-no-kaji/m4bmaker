"""m4bmaker — entry point: wire all modules and drive the conversion pipeline."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from m4bmaker import __version__
from m4bmaker.chapters import build_chapters, write_ffmetadata
from m4bmaker.cli import parse_args
from m4bmaker.cover import download_cover, find_cover, is_url
from m4bmaker.encoder import encode, write_concat_list
from m4bmaker.metadata import extract_metadata, prompt_missing
from m4bmaker.scanner import scan_audio_files
from m4bmaker.utils import find_ffmpeg, find_ffprobe, log


def _output_path(directory: Path, meta: dict[str, str]) -> Path:
    """Derive the output .m4b filename from metadata, with a safe fallback."""
    title = meta.get("title", "").strip()
    author = meta.get("author", "").strip()

    if title and author:
        # Sanitise characters that are illegal in filenames on macOS/Linux.
        def safe(s: str) -> str:
            return s.replace("/", "-").replace("\x00", "")

        name = f"{safe(title)} - {safe(author)}.m4b"
    elif title:
        name = f"{title.replace('/', '-')}.m4b"
    else:
        name = "audiobook.m4b"

    return directory / name


def _hints_from_dirname(directory: Path) -> dict[str, str]:
    """Extract title/author hints from an 'Author - Title' directory name."""
    name = directory.name
    if " - " in name:
        author, _, title = name.partition(" - ")
        return {"author": author.strip(), "title": title.strip()}
    return {"title": name.strip()}


def _resolve_cover(
    cover_arg: str | None,
    directory: Path,
    tmp_dir: Path,
    interactive: bool,
) -> Path | None:
    """Resolve the cover image from CLI argument, directory scan, or user prompt.

    Resolution order:
    1. *cover_arg* provided — URL: download (retry interactively on failure);
       local path: passed directly to :func:`find_cover`.
    2. Auto-detect a single image file in *directory*.
    3. If *interactive*, prompt the user for a URL or local path.
    """
    if cover_arg is not None:
        if is_url(cover_arg):
            return _fetch_cover_url(cover_arg, tmp_dir, interactive)
        return find_cover(directory, cli_override=Path(cover_arg).expanduser())

    cover = find_cover(directory)
    if cover is not None:
        return cover

    if interactive:
        return _prompt_cover(tmp_dir)
    return None


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
        cover = _resolve_cover(args.cover, directory, tmp_dir, interactive)
        if cover:
            log(f"Cover art: {cover.name}")
        else:
            log("No cover art found — skipping")

        # 4. Read and complete metadata.
        log("Reading metadata...")
        meta = extract_metadata(files[0])
        hints = _hints_from_dirname(directory)
        meta = prompt_missing(meta, args, hints=hints)
        log(
            f"Title: {meta['title']} | Author: {meta['author']} "
            f"| Narrator: {meta['narrator']}"
        )

        # 5. Resolve output path.
        output: Path = (
            args.output.resolve() if args.output else _output_path(directory, meta)
        )
        log(f"Output: {output}")

        # 6. Build chapter list and write FFMETADATA.
        log("Generating chapter markers...")
        meta_file = tmp_dir / "ffmetadata.txt"
        concat_file = tmp_dir / "concat.txt"

        chapters = build_chapters(
            files,
            ffprobe,
            progress_fn=lambda i, n, name: log(f"  [{i}/{n}] {name}"),
        )
        write_ffmetadata(chapters, meta, meta_file)
        log(f"Generated {len(chapters)} chapter(s)")

        # 7. Write concat list.
        write_concat_list(files, concat_file)

        # 8. Encode.
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
        )

    log(f"Done. Output: {output}")


if __name__ == "__main__":
    main()
