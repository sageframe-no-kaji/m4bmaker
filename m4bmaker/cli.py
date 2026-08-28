"""Argument parser for the make_m4b command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Return the configured ArgumentParser for make_m4b."""
    parser = argparse.ArgumentParser(
        prog="m4bmaker",
        description=(
            "Convert a directory of audio files into a single .m4b audiobook "
            "with chapters, cover art, and embedded metadata."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  make_m4b /audiobooks/Dune\n"
            "  make_m4b . --title 'Dune' --author 'Frank Herbert' --stereo\n"
            "  make_m4b /books/Dune --bitrate 128k --output ~/Desktop/Dune.m4b\n"
        ),
    )

    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        type=Path,
        metavar="DIRECTORY",
        help="Directory containing the audio files (default: current directory).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Explicit output .m4b file path. Overrides --output-dir and --flat. "
            "Defaults to <output-dir>/Author/Title/Author - Title.m4b."
        ),
    )
    parser.add_argument(
        "--output-dir",
        "-O",
        type=Path,
        default=None,
        metavar="DIR",
        help=(
            "Base directory for the auto-generated output path. "
            "Default: same directory as the audio files. "
            "Ignored when --output is given."
        ),
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        default=False,
        help=(
            "Write the .m4b directly into the output directory as "
            "Author - Title.m4b instead of creating Author/Title/ subfolders."
        ),
    )
    parser.add_argument(
        "--title",
        "-t",
        default=None,
        metavar="TITLE",
        help="Book title (overrides tag extraction and skips the title prompt).",
    )
    parser.add_argument(
        "--author",
        "-a",
        default=None,
        metavar="AUTHOR",
        help="Author name (overrides tag extraction and skips the author prompt).",
    )
    parser.add_argument(
        "--narrator",
        "-n",
        default=None,
        metavar="NARRATOR",
        help="Narrator name (overrides tag extraction and skips the narrator prompt).",
    )
    parser.add_argument(
        "--genre",
        "-g",
        default=None,
        metavar="GENRE",
        help="Genre (overrides tag extraction and skips the genre prompt).",
    )
    parser.add_argument(
        "--cover",
        "-c",
        type=str,
        default=None,
        metavar="IMAGE_OR_URL",
        help=(
            "Path or URL to a cover image (.jpg/.jpeg/.png). "
            "Bypasses auto-detection."
        ),
    )
    parser.add_argument(
        "--bitrate",
        "-b",
        default="96k",
        metavar="BITRATE",
        help="Audio bitrate passed to ffmpeg -b:a (default: 96k).",
    )
    parser.add_argument(
        "--stereo",
        action="store_true",
        default=False,
        help="Encode in stereo (2 channels). Default is mono (1 channel).",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        default=False,
        help=(
            "Normalize loudness to EBU R128 spoken-word targets "
            "(I=-18 LUFS, TP=-2 dBTP, LRA=11). Off by default."
        ),
    )
    parser.add_argument(
        "--normalize-two-pass",
        dest="normalize_two_pass",
        action="store_true",
        default=False,
        help=(
            "Measure loudness in a separate pass before encoding, for a more "
            "accurate result. Implies --normalize and roughly doubles "
            "encoding time."
        ),
    )
    parser.add_argument(
        "--detect-chapters",
        dest="detect_chapters",
        action="store_true",
        default=False,
        help=(
            "Derive chapter markers from silence in the audio instead of from "
            "filenames. Detection is heuristic — review the result before "
            "relying on it. Ignored when --chapters-file is given."
        ),
    )
    parser.add_argument(
        "--silence-threshold",
        dest="silence_threshold",
        type=float,
        default=-30.0,
        metavar="DB",
        help=(
            "Noise floor for --detect-chapters, in dB. Audio quieter than this "
            "counts as silence (default: -30.0)."
        ),
    )
    parser.add_argument(
        "--silence-duration",
        dest="silence_duration",
        type=float,
        default=1.5,
        metavar="SECONDS",
        help=(
            "Shortest silence that can mark a chapter break, in seconds "
            "(default: 1.5)."
        ),
    )
    parser.add_argument(
        "--asin",
        default=None,
        metavar="ASIN",
        help=(
            "Audible ASIN to fetch metadata and chapter names from Audnexus "
            "(api.audnex.us). Passing this flag makes one network request; "
            "the ASIN is the only thing sent."
        ),
    )
    parser.add_argument(
        "--asin-region",
        dest="asin_region",
        default="us",
        metavar="REGION",
        help=(
            "Audible storefront the ASIN belongs to: us, uk, de, fr, ca, au, "
            "etc. (default: us). An ASIN is storefront-specific."
        ),
    )
    parser.add_argument(
        "--asin-use-timings",
        dest="asin_use_timings",
        action="store_true",
        default=False,
        help=(
            "Use Audible's chapter timings instead of only its names. The "
            "shift needed to match your audio is derived, and no shift is "
            "applied if the book does not line up consistently. Default is to "
            "keep your own chapter boundaries and take only the names."
        ),
    )
    parser.add_argument(
        "--chapters-file",
        dest="chapters_file",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "Path to a plain-text chapter list. "
            "Each non-blank line must be: TIMESTAMP TITLE\n"
            "where TIMESTAMP is MM:SS or H:MM:SS. "
            "When supplied, overrides the auto-generated chapter markers."
        ),
    )
    parser.add_argument(
        "--no-prompt",
        dest="no_prompt",
        action="store_true",
        default=False,
        help=(
            "Disable all interactive prompts. "
            "Missing required metadata will cause an error exit. "
            "Use with --title, --author, --narrator to supply values non-interactively."
        ),
    )

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse and return CLI arguments, defaulting directory to cwd if omitted."""
    import os

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.directory is None:
        args.directory = Path(os.getcwd())

    return args
