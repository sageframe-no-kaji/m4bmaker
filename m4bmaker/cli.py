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
            "Output .m4b file path. "
            "Defaults to <DIRECTORY>/<Title> - <Author>.m4b "
            "(or audiobook.m4b if metadata is unavailable)."
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
        "--cover",
        "-c",
        type=Path,
        default=None,
        metavar="IMAGE",
        help="Path to cover image (.jpg/.jpeg/.png). Bypasses auto-detection.",
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
