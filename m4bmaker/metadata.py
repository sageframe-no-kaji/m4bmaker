"""Audio metadata extraction via mutagen and interactive user prompts."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from m4bmaker.errors import M4BError
from m4bmaker.utils import safe_input

_MP4_EXTENSIONS = frozenset({".m4a", ".m4b"})


def _first_tag(tags: Any, *keys: str) -> str:
    """Return the string value of the first matching key in *tags*, or ''."""
    for key in keys:
        val = tags.get(key)
        if val:
            # mutagen values are often lists; take the first element.
            item = val[0] if isinstance(val, list) else val
            return str(item).strip()
    return ""


def _mp4_narrator(first_file: Path) -> str:
    """Read the narrator from raw MP4 atoms: ``©nrt`` first, then ``©wrt``.

    mutagen's EasyMP4 exposes neither atom directly — ``©nrt`` (Apple's
    dedicated narrator atom) isn't in its key set at all, and ``©wrt``
    (composer) is also absent. Both must be read via :class:`mutagen.mp4.MP4`
    directly. Returns ``""`` if neither atom is present or the file can't be
    read as MP4.
    """
    try:
        from mutagen.mp4 import MP4

        # mutagen's py.typed marker exists but MP4.__init__ isn't fully
        # annotated, so mypy sees this constructor call as untyped.
        raw: Any = MP4(str(first_file))  # type: ignore[no-untyped-call]
        if not raw.tags:
            return ""
        for atom in ("\xa9nrt", "\xa9wrt"):
            val = raw.tags.get(atom, [])
            if val:
                return str(val[0]).strip()
    except Exception:
        pass
    return ""


def extract_metadata(first_file: Path) -> dict[str, str]:
    """Attempt to read title, author, narrator, and genre from *first_file*.

    Returns a dict with keys 'title', 'author', 'narrator', 'genre'.
    Missing fields are returned as empty strings.

    For MP4/M4B files, narrator is read from the raw ``©nrt``/``©wrt`` atoms
    before falling back to the easy-tag chain below: mutagen's EasyMP4
    exposes ``comment`` but not ``composer``, so on an m4b with a comment
    atom (store blurbs are common) the easy-tag chain would otherwise surface
    the comment as the narrator.
    """
    meta: dict[str, str] = {"title": "", "author": "", "narrator": "", "genre": ""}

    if first_file.suffix.lower() in _MP4_EXTENSIONS:
        mp4_narrator = _mp4_narrator(first_file)
        if mp4_narrator:
            meta["narrator"] = mp4_narrator

    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(first_file), easy=True)
        if audio is None or audio.tags is None:
            return meta

        tags = audio.tags
        meta["title"] = _first_tag(tags, "title", "TIT2")
        meta["author"] = _first_tag(tags, "artist", "albumartist", "TPE1", "TPE2")
        meta["genre"] = _first_tag(tags, "genre", "TCON")

        if not meta["narrator"]:
            # 'narrator' is non-standard; try composer tag names. 'comment'
            # and 'TPUB' (publisher) are deliberately excluded — they hold
            # unrelated data and were the source of the m4b narrator bug.
            meta["narrator"] = _first_tag(tags, "composer", "TCOM", "narrator")
    except Exception:
        # If mutagen cannot read the file, return what we have so far
        # (possibly an MP4 narrator) — prompts will fill in the rest.
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
        try:
            value = safe_input(prompt_str).strip()
        except M4BError as exc:
            sys.exit(str(exc))
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
