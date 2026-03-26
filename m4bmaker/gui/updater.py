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
    """Convert a version tag like 'v1.2.3' or '1.2.3' to a comparable tuple."""
    return tuple(int(x) for x in tag.lstrip("v").split(".") if x.isdigit())


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

            if remote > local:
                self.update_available.emit(tag.lstrip("v"))

        except (urllib.error.URLError, OSError, JSONDecodeError, ValueError) as exc:
            _log.debug("Update check failed (this is non-critical): %s", exc)
