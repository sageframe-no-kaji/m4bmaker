"""Audio metadata extraction via mutagen and interactive user prompts."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from typing import Any


def _first_tag(tags: Any, *keys: str) -> str:
    """Return the string value of the first matching key in *tags*, or ''."""
    for key in keys:
        val = tags.get(key)
        if val:
            # mutagen values are often lists; take the first element.
            item = val[0] if isinstance(val, list) else val
            return str(item).strip()
    return ""


def extract_metadata(first_file: Path) -> dict[str, str]:
    """Attempt to read title, author, and narrator from *first_file* using mutagen.

    Returns a dict with keys 'title', 'author', 'narrator'.
    Missing fields are returned as empty strings.
    """
    meta: dict[str, str] = {"title": "", "author": "", "narrator": ""}

    try:
        from mutagen import File as MutagenFile  # type: ignore[attr-defined]

        audio = MutagenFile(str(first_file), easy=True)
        if audio is None or audio.tags is None:
            return meta

        tags = audio.tags
        meta["title"] = _first_tag(tags, "title", "TIT2")
        meta["author"] = _first_tag(tags, "artist", "albumartist", "TPE1", "TPE2")
        # 'narrator' is non-standard; try several common tag names.
        meta["narrator"] = _first_tag(
            tags, "composer", "TCOM", "narrator", "TPUB", "comment"
        )
    except Exception:
        # If mutagen cannot read the file, return empty — prompts will fill in.
        pass

    return meta


def prompt_missing(
    meta: dict[str, str],
    args: Namespace,
    hints: dict[str, str] | None = None,
) -> dict[str, str]:
    """Fill in missing metadata fields from CLI flags or interactive prompts.

    *hints* is an optional dict of pre-filled defaults (e.g. derived from the
    directory name) shown as ``[default]`` in the prompt.  Pressing Enter
    accepts the hint.  When ``--no-prompt`` is set and a hint is available it
    is used silently; when no hint is available the process exits.

    - title, author: prompted if missing and not supplied via CLI.
    - narrator: always prompted unless --narrator CLI flag is set.

    Returns a new dict with all three fields populated.
    """
    result = dict(meta)

    # Apply CLI overrides first.
    if getattr(args, "title", None):
        result["title"] = args.title
    if getattr(args, "author", None):
        result["author"] = args.author
    if getattr(args, "narrator", None):
        result["narrator"] = args.narrator

    no_prompt: bool = getattr(args, "no_prompt", False)

    def _prompt(field: str, label: str) -> str:
        hint = (hints or {}).get(field, "")
        if no_prompt:
            if hint:
                return hint
            sys.exit(
                f"Error: '{field}' is required but was not found in tags and "
                f"--no-prompt is set. Pass --{field} <value> to supply it."
            )
        prompt_str = f"{label} [{hint}]: " if hint else f"{label}: "
        value = input(prompt_str).strip()
        if not value:
            if hint:
                return hint
            sys.exit(f"Error: '{field}' cannot be empty.")
        return value

    if not result["title"]:
        result["title"] = _prompt("title", "Enter book title")
    if not result["author"]:
        result["author"] = _prompt("author", "Enter author")
    # Narrator is always prompted unless already set by CLI or tags.
    if not result["narrator"]:
        result["narrator"] = _prompt("narrator", "Enter narrator")

    return result
