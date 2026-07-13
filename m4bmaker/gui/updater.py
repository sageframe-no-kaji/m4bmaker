"""Background update checker for m4Bookmaker.

Runs once per session at startup in a QThread. Silently fetches the GitHub
Releases API, compares the latest tag against the running __version__, and
emits ``update_available(str)`` with the new version string if one exists.

Network call:
    GET https://api.github.com/repos/sageframe-no-kaji/m4bmaker/releases/latest
    User-Agent: m4bmaker/<version>

Fails silently on any network or parse error — the user is never informed of
a failed check.

Privacy note:
    This is the only outbound network call made by m4Bookmaker. It sends your
    IP address and the installed version to the GitHub API. No other data is
    transmitted. See README.md for details.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from json import JSONDecodeError, loads as json_loads

from PySide6.QtCore import QThread, Signal

from m4bmaker import __version__

_log = logging.getLogger(__name__)

_API_URL = "https://api.github.com/repos/sageframe-no-kaji/m4bmaker/releases/latest"
_RELEASES_URL = "https://github.com/sageframe-no-kaji/m4bmaker/releases"
_TIMEOUT = 5  # seconds


def _parse_version(tag: str) -> tuple[int, ...]:
    """Convert a version tag to a comparable tuple of ints.

    Consumes the leading numeric dot-run: purely-numeric segments are taken in
    full, and the run stops at the first segment that is not purely numeric
    (after taking that segment's own numeric prefix).  This keeps pre-release
    and build suffixes from corrupting the ordering:

        ``v1.2.3-beta``   → ``(1, 2, 3)``   (not ``(1, 2)`` as a naive
                                             ``str.isdigit`` filter produced)
        ``1.4.0+build.7`` → ``(1, 4, 0)``   (build metadata dropped)
        ``2.10rc1.5``     → ``(2, 10)``     (stops at the ``rc`` segment)

    Pre-release ordering itself is handled in :meth:`UpdateChecker.run`.
    Garbage input yields ``()`` — a fail-safe that never compares as newer.
    """
    parts: list[int] = []
    for segment in tag.lstrip("vV").split("."):
        if segment.isdigit():
            parts.append(int(segment))
            continue
        # First non-numeric segment: take its numeric prefix, then stop.
        num = ""
        for ch in segment:
            if ch.isdigit():
                num += ch
            else:
                break
        if num:
            parts.append(int(num))
        break
    return tuple(parts)


class UpdateChecker(QThread):
    """QThread that checks GitHub Releases for a newer version.

    Emits ``update_available(str)`` with the new version string when a newer
    release is found. Emits nothing if the check fails or the app is current.
    """

    update_available: Signal = Signal(str)

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                _API_URL,
                headers={"User-Agent": f"m4bmaker/{__version__}"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json_loads(resp.read().decode("utf-8"))

            tag: object = data.get("tag_name", "")
            if not isinstance(tag, str) or not tag:
                return

            remote = _parse_version(tag)
            local = _parse_version(__version__)

            # Compare numeric versions.  A pre-release of a *higher* numeric
            # version (1.2.3-beta) is newer than the current release (1.2.2)
            # because its parsed tuple (1,2,3) already exceeds (1,2,2).  A
            # pre-release with the *same* numeric tuple as the current release
            # is NOT newer (don't offer 1.2.3-beta to a 1.2.3 user).  Empty
            # tuples from garbage tags never compare as newer (fail-safe).
            if remote > local:
                self.update_available.emit(tag.lstrip("vV"))

        except (urllib.error.URLError, OSError, JSONDecodeError, ValueError) as exc:
            _log.debug("Update check failed (this is non-critical): %s", exc)
