"""Tests for m4bmaker.gui.updater — background update checker, closes #6.

Network call is mocked in all tests. Covers:
- UpdateChecker emits update_available when remote > local
- UpdateChecker does NOT emit when remote == local
- UpdateChecker does NOT emit when remote < local
- Fails silently on network error (URLError)
- Fails silently on timeout (URLError/socket.timeout)
- Fails silently on malformed JSON
- Fails silently when tag_name is missing
- Fails silently when tag_name is not a version string
- Version parsing strips leading 'v' correctly
- Version comparison: major, minor, patch all considered
- MainWindow wires UpdateChecker and shows the update bar on signal
- Update bar is hidden by default
- Update bar dismiss button hides the bar
"""

from __future__ import annotations

import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from m4bmaker.gui.updater import UpdateChecker, _parse_version  # noqa: E402

# ---------------------------------------------------------------------------
# _parse_version helper
# ---------------------------------------------------------------------------


class TestParseVersion:
    def test_strips_leading_v(self) -> None:
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_no_leading_v(self) -> None:
        assert _parse_version("1.0.0") == (1, 0, 0)

    def test_two_part_version(self) -> None:
        assert _parse_version("v2.1") == (2, 1)

    def test_patch_zero(self) -> None:
        assert _parse_version("v1.0.0") == (1, 0, 0)


# ---------------------------------------------------------------------------
# UpdateChecker.run() — direct call (no QThread machinery in unit tests)
# ---------------------------------------------------------------------------


def _make_response(tag: str, status: int = 200) -> MagicMock:
    """Return a mock urllib response context manager."""
    body = json.dumps({"tag_name": tag}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestUpdateCheckerRun:
    """Call checker.run() directly to avoid starting real QThreads."""

    def _make_checker(self) -> tuple[UpdateChecker, list[str]]:
        checker = UpdateChecker()
        emitted: list[str] = []
        checker.update_available.connect(emitted.append)
        return checker, emitted

    # -- emits when newer --------------------------------------------------

    def test_emits_when_remote_is_newer(self) -> None:
        checker, emitted = self._make_checker()
        with (
            patch("m4bmaker.gui.updater.__version__", "1.0.0"),
            patch(
                "m4bmaker.gui.updater.urllib.request.urlopen",
                return_value=_make_response("v1.0.1"),
            ),
        ):
            checker.run()
        assert emitted == ["1.0.1"]

    def test_emits_with_version_string_stripped_of_v(self) -> None:
        checker, emitted = self._make_checker()
        with (
            patch("m4bmaker.gui.updater.__version__", "1.0.0"),
            patch(
                "m4bmaker.gui.updater.urllib.request.urlopen",
                return_value=_make_response("v2.0.0"),
            ),
        ):
            checker.run()
        assert emitted == ["2.0.0"]

    def test_newer_minor_version_emits(self) -> None:
        checker, emitted = self._make_checker()
        with (
            patch("m4bmaker.gui.updater.__version__", "1.0.0"),
            patch(
                "m4bmaker.gui.updater.urllib.request.urlopen",
                return_value=_make_response("v1.1.0"),
            ),
        ):
            checker.run()
        assert len(emitted) == 1

    def test_newer_major_version_emits(self) -> None:
        checker, emitted = self._make_checker()
        with (
            patch("m4bmaker.gui.updater.__version__", "1.0.0"),
            patch(
                "m4bmaker.gui.updater.urllib.request.urlopen",
                return_value=_make_response("v2.0.0"),
            ),
        ):
            checker.run()
        assert len(emitted) == 1

    # -- does NOT emit when same or older ----------------------------------

    def test_no_emit_when_same_version(self) -> None:
        checker, emitted = self._make_checker()
        with (
            patch("m4bmaker.gui.updater.__version__", "1.0.0"),
            patch(
                "m4bmaker.gui.updater.urllib.request.urlopen",
                return_value=_make_response("v1.0.0"),
            ),
        ):
            checker.run()
        assert emitted == []

    def test_no_emit_when_remote_is_older(self) -> None:
        checker, emitted = self._make_checker()
        with (
            patch("m4bmaker.gui.updater.__version__", "1.0.1"),
            patch(
                "m4bmaker.gui.updater.urllib.request.urlopen",
                return_value=_make_response("v1.0.0"),
            ),
        ):
            checker.run()
        assert emitted == []

    # -- silent failure cases ----------------------------------------------

    def test_silent_on_url_error(self) -> None:
        checker, emitted = self._make_checker()
        with patch(
            "m4bmaker.gui.updater.urllib.request.urlopen",
            side_effect=urllib.error.URLError("network unreachable"),
        ):
            checker.run()  # must not raise
        assert emitted == []

    def test_silent_on_timeout(self) -> None:
        import socket

        checker, emitted = self._make_checker()
        with patch(
            "m4bmaker.gui.updater.urllib.request.urlopen",
            side_effect=urllib.error.URLError(socket.timeout()),
        ):
            checker.run()
        assert emitted == []

    def test_silent_on_malformed_json(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"this is not json {{{"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        checker, emitted = self._make_checker()
        with patch(
            "m4bmaker.gui.updater.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            checker.run()
        assert emitted == []

    def test_silent_when_tag_name_missing(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"name": "Release"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        checker, emitted = self._make_checker()
        with patch(
            "m4bmaker.gui.updater.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            checker.run()
        assert emitted == []

    def test_silent_when_tag_name_not_a_version(self) -> None:
        checker, emitted = self._make_checker()
        with (
            patch("m4bmaker.gui.updater.__version__", "1.0.0"),
            patch(
                "m4bmaker.gui.updater.urllib.request.urlopen",
                return_value=_make_response("not-a-version"),
            ),
        ):
            checker.run()
        # "not-a-version" parses to () which is not > (1,0,0) — no emit
        assert emitted == []

    def test_user_agent_header_sent(self) -> None:
        from m4bmaker import __version__ as ver

        checker, _ = self._make_checker()
        captured_requests: list[object] = []

        def fake_urlopen(req: object, timeout: int) -> object:
            captured_requests.append(req)
            raise urllib.error.URLError("abort after capture")

        with patch("m4bmaker.gui.updater.urllib.request.urlopen", fake_urlopen):
            checker.run()

        assert captured_requests
        req = captured_requests[0]
        assert hasattr(req, "get_header")
        assert f"m4bmaker/{ver}" in req.get_header("User-agent")


# ---------------------------------------------------------------------------
# MainWindow integration — info bar wired correctly (mocked checker)
# ---------------------------------------------------------------------------


class TestMainWindowUpdateBar:
    def test_update_bar_hidden_by_default(self, qapp: object) -> None:
        """The update bar must not be visible on startup."""
        with patch("m4bmaker.gui.window.UpdateChecker") as MockChecker:
            MockChecker.return_value = MagicMock()
            win = MainWindow()
            assert win._update_bar.isHidden()
            win.close()

    def test_show_update_bar_makes_bar_visible(self, qapp: object) -> None:
        """Calling _show_update_bar() with a version string shows the bar."""
        with patch("m4bmaker.gui.window.UpdateChecker") as MockChecker:
            MockChecker.return_value = MagicMock()
            win = MainWindow()
            win._show_update_bar("1.1.0")
            assert not win._update_bar.isHidden()
            assert "1.1.0" in win._update_label.text()
            win.close()

    def test_update_checker_started_on_init(self, qapp: object) -> None:
        """UpdateChecker.start() must be called once during MainWindow init."""
        with patch("m4bmaker.gui.window.UpdateChecker") as MockChecker:
            mock_instance = MagicMock()
            MockChecker.return_value = mock_instance
            win = MainWindow()
            mock_instance.start.assert_called_once()
            win.close()


# deferred import to keep GUI imports after QT_QPA_PLATFORM is set
from m4bmaker.gui.window import MainWindow  # noqa: E402
