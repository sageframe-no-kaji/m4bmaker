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
    """Attempt to read title, author, narrator, and genre from *first_file*.

    Returns a dict with keys 'title', 'author', 'narrator', 'genre'.
    Missing fields are returned as empty strings.
    """
    meta: dict[str, str] = {"title": "", "author": "", "narrator": "", "genre": ""}

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
        meta["genre"] = _first_tag(tags, "genre", "TCON")
    except Exception:
        # If mutagen cannot read the file, return empty — prompts will fill in.
        pass

    return meta


def prompt_missing(
    meta: dict[str, str],
    args: Namespace,
    hints: dict[str, str] | None = None,
) -> dict[str, str]:
    """Confirm or fill every metadata field interactively.

    Every field is presented for confirmation — even fields already populated
    from tags or CLI flags — with the best-known value pre-filled.

    Precedence for pre-fill: CLI flag > current tag value > dirname hint.

    - title, author, narrator: required; cannot be empty.
    - genre: optional; empty is allowed.

    With ``--no-prompt``, values are resolved silently without interaction.
    """
    result = dict(meta)
    no_prompt: bool = getattr(args, "no_prompt", False)

    def _confirm(field: str, label: str, required: bool = True) -> str:
        cli_val: str = getattr(args, field, None) or ""
        tag_val: str = result.get(field, "")
        hint_val: str = (hints or {}).get(field, "")
        prefill = cli_val or tag_val or hint_val

        if no_prompt:
            if prefill:
                return prefill
            if required:
                sys.exit(
                    f"Error: '{field}' is required but was not found in tags "
                    f"and --no-prompt is set. Pass --{field} <value> to supply it."
                )
            return ""

        prompt_str = f"{label} [{prefill}]: " if prefill else f"{label}: "
        value = input(prompt_str).strip()
        if not value:
            if prefill:
                return prefill
            if required:
                sys.exit(f"Error: '{field}' cannot be empty.")
            return ""
        return value

    result["title"] = _confirm("title", "Book title")
    result["author"] = _confirm("author", "Author")
    result["narrator"] = _confirm("narrator", "Narrator")
    result["genre"] = _confirm("genre", "Genre", required=False)

    return result
