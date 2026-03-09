"""m4bmaker — entry point: wire all modules and drive the conversion pipeline."""

from __future__ import annotations

import tempfile
from pathlib import Path

from m4bmaker import __version__
from m4bmaker.chapters import build_chapters, write_ffmetadata
from m4bmaker.cli import parse_args
from m4bmaker.cover import find_cover
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


def main() -> None:
    args = parse_args()
    directory: Path = args.directory.resolve()

    log(f"m4bmaker {__version__}")
    log(f"Working directory: {directory}")

    # 1. Detect tool locations (exits early if missing).
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()

    # 2. Scan for audio files.
    log("Scanning directory...")
    files = scan_audio_files(directory)
    log(f"Found {len(files)} audio file(s)")

    # 3. Locate cover image.
    log("Looking for cover art...")
    cover = find_cover(directory, cli_override=args.cover)
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
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
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
