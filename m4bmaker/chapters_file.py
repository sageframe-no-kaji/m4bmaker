"""Parser for external chapter list files (--chapters-file).

File format
-----------
Each non-blank, non-comment line must be::

    TIMESTAMP  TITLE

where *TIMESTAMP* is either ``MM:SS`` or ``H:MM:SS`` and *TITLE* is any
non-empty string.  Lines beginning with ``#`` are treated as comments and
ignored.

Examples::

    00:00 Opening Engagement
    10:37 The Surprise
    1:19:17 Port Mahon
"""

from __future__ import annotations

import re
from pathlib import Path

from m4bmaker.errors import M4BError
from m4bmaker.models import Chapter

# Matches either  MM:SS  or  H:MM:SS  (H may be more than one digit).
_TIMESTAMP_RE = re.compile(r"^(\d+:\d{2}(?::\d{2})?)\s+(.+)$")


def _parse_timestamp(ts: str) -> float:
    """Convert a *MM:SS* or *H:MM:SS* string to seconds (float).

    Raises :class:`ValueError` for any string that doesn't match those patterns.
    """
    parts = ts.split(":")
    try:
        int_parts = [int(p) for p in parts]
    except ValueError:
        raise ValueError(f"non-integer in timestamp {ts!r}")

    if len(int_parts) == 2:
        m, s = int_parts
        if not (0 <= s < 60):
            raise ValueError(f"seconds out of range in {ts!r}")
        return m * 60.0 + s
    elif len(int_parts) == 3:
        h, m, s = int_parts
        if not (0 <= m < 60 and 0 <= s < 60):
            raise ValueError(f"minutes or seconds out of range in {ts!r}")
        return h * 3600.0 + m * 60.0 + s
    raise ValueError(f"unrecognised timestamp format {ts!r}")  # pragma: no cover


def load_chapters_file(path: Path) -> list[Chapter]:
    """Parse *path* and return a :class:`~m4bmaker.models.Chapter` list.

    Raises :class:`~m4bmaker.errors.M4BError` if:

    - the file cannot be read
    - any non-blank, non-comment line is malformed
    - the file contains no chapters after filtering
    - the first chapter does not start at or after 0, or timestamps are not
      strictly increasing
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise M4BError(f"Error: cannot read chapters file '{path}': {exc}") from exc

    chapters: list[Chapter] = []
    # Track the source line number for each parsed chapter, for validation
    # error messages below.
    linenos: list[int] = []
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        m = _TIMESTAMP_RE.match(line)
        if not m:
            raise M4BError(
                f"Error: malformed line {lineno} in '{path.name}':\n"
                f"  {raw_line!r}\n"
                f"Expected format: MM:SS TITLE  or  H:MM:SS TITLE"
            )

        ts_str, title = m.group(1), m.group(2).strip()
        try:
            start_time = _parse_timestamp(ts_str)
        except ValueError as exc:
            raise M4BError(
                f"Error: invalid timestamp on line {lineno} of '{path.name}': {exc}"
            ) from exc

        chapters.append(
            Chapter(
                index=len(chapters) + 1,
                start_time=start_time,
                title=title,
                source_file=None,
            )
        )
        linenos.append(lineno)

    if not chapters:
        raise M4BError(f"Error: no chapters found in '{path.name}'")

    if chapters[0].start_time < 0:
        raise M4BError(
            f"Error: line {linenos[0]} of '{path.name}' has a negative start "
            f"time ({chapters[0].start_time}s) — the first chapter must start "
            f"at or after 0:00"
        )

    for i in range(1, len(chapters)):
        if chapters[i].start_time <= chapters[i - 1].start_time:
            raise M4BError(
                f"Error: line {linenos[i]} of '{path.name}' is not after the "
                f"previous chapter's timestamp — chapter timestamps must be "
                f"strictly increasing:\n"
                f"  chapter {chapters[i - 1].index} starts at "
                f"{chapters[i - 1].start_time}s, "
                f"chapter {chapters[i].index} starts at "
                f"{chapters[i].start_time}s"
            )

    return chapters
