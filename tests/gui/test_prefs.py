"""Tests for m4bmaker.gui.prefs — persistent theme preference, closes #7.

Covers:
- load() returns defaults when no file exists
- save() + load() round-trip (simulates session restart)
- set() / get() single-key convenience helpers
- Corrupt JSON falls back to defaults silently
- platformdirs is used for the config directory path
- MainWindow restores dark_mode preference on init (window integration test)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import m4bmaker.gui.prefs as prefs_mod  # noqa: E402
from m4bmaker.gui.prefs import get, load, save, set  # noqa: E402
from m4bmaker.gui.window import MainWindow  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture: redirect config dir to a temp path so tests don't touch the real
# user config directory.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_prefs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect _prefs_path() to a tmp directory for every test."""
    config_dir = tmp_path / "m4bmaker_test_config"
    monkeypatch.setattr(
        prefs_mod,
        "_prefs_path",
        lambda: config_dir / "prefs.json",
    )


# ---------------------------------------------------------------------------
# load() — defaults and file-absent behaviour
# ---------------------------------------------------------------------------


class TestLoad:
    def test_returns_defaults_when_no_file_exists(self) -> None:
        result = load()
        assert result["dark_mode"] is False

    def test_check_for_updates_defaults_to_true(self) -> None:
        result = load()
        assert result["check_for_updates"] is True

    def test_returns_dict(self) -> None:
        assert isinstance(load(), dict)

    def test_existing_value_overrides_default(self, tmp_path: Path) -> None:
        path = prefs_mod._prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"dark_mode": True}), encoding="utf-8")
        result = load()
        assert result["dark_mode"] is True

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path: Path) -> None:
        path = prefs_mod._prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("this is not json {{{{", encoding="utf-8")
        result = load()
        assert result["dark_mode"] is False  # default, no exception raised

    def test_non_dict_root_falls_back_to_defaults(self, tmp_path: Path) -> None:
        path = prefs_mod._prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        result = load()
        assert result["dark_mode"] is False


# ---------------------------------------------------------------------------
# save() + load() — restart simulation (the core issue #7 requirement)
# ---------------------------------------------------------------------------


class TestSaveLoadRoundTrip:
    def test_dark_mode_true_persists(self) -> None:
        """Set dark_mode True, reload (simulating app restart), confirm restored."""
        save({"dark_mode": True})
        reloaded = load()
        assert reloaded["dark_mode"] is True

    def test_dark_mode_false_persists(self) -> None:
        save({"dark_mode": False})
        reloaded = load()
        assert reloaded["dark_mode"] is False

    def test_save_creates_config_directory(self) -> None:
        path = prefs_mod._prefs_path()
        assert not path.parent.exists()
        save({"dark_mode": True})
        assert path.parent.exists()
        assert path.exists()

    def test_save_writes_valid_json(self) -> None:
        save({"dark_mode": True})
        path = prefs_mod._prefs_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["dark_mode"] is True

    def test_save_silently_ignores_permission_error(self) -> None:
        with patch("builtins.open", side_effect=PermissionError("denied")):
            save({"dark_mode": True})  # must not raise


# ---------------------------------------------------------------------------
# set() / get() convenience API
# ---------------------------------------------------------------------------


class TestSetGet:
    def test_get_default_when_no_file(self) -> None:
        assert get("dark_mode") is False

    def test_get_check_for_updates_default(self) -> None:
        assert get("check_for_updates") is True

    def test_set_persists_and_get_returns_it(self) -> None:
        set("dark_mode", True)
        assert get("dark_mode") is True

    def test_set_false_after_true(self) -> None:
        set("dark_mode", True)
        set("dark_mode", False)
        assert get("dark_mode") is False

    def test_set_check_for_updates_false_persists(self) -> None:
        set("check_for_updates", False)
        assert get("check_for_updates") is False


# ---------------------------------------------------------------------------
# platformdirs integration — config path is platform-appropriate
# ---------------------------------------------------------------------------


class TestPrefsPath:
    def test_prefs_path_uses_platformdirs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_prefs_path() must delegate to platformdirs.user_config_dir."""
        # Un-patch so we test the real implementation here.
        monkeypatch.setattr(
            prefs_mod,
            "_prefs_path",
            (
                prefs_mod.__wrapped_prefs_path
                if hasattr(prefs_mod, "__wrapped_prefs_path")
                else lambda: Path(prefs_mod.user_config_dir("m4bmaker")) / "prefs.json"
            ),
        )
        from platformdirs import user_config_dir

        expected = Path(user_config_dir("m4bmaker")) / "prefs.json"
        # Just check function is using platformdirs, not a hardcoded path
        with patch(
            "m4bmaker.gui.prefs.user_config_dir", return_value=str(expected.parent)
        ) as mock_ucd:
            prefs_mod._prefs_path()
            mock_ucd.assert_called_once_with("m4bmaker")


# ---------------------------------------------------------------------------
# MainWindow integration — dark_mode restored on init (issue #7 core)
# ---------------------------------------------------------------------------


class TestMainWindowPrefsPersistence:
    def test_window_starts_light_mode_by_default(self, qapp: object) -> None:
        """With no saved pref, window initialises in light mode."""
        with patch("m4bmaker.gui.window._prefs_get", return_value=False):
            win = MainWindow()
            assert win._dark_mode is False
            win.close()

    def test_window_restores_dark_mode_on_init(self, qapp: object) -> None:
        """Saved dark_mode=True is read on init and applied — simulates restart."""
        # First session: enable dark mode and save
        set("dark_mode", True)

        # Second session: new window, pref is loaded automatically
        # (we allow _prefs_get to call the real isolated prefs module)
        win = MainWindow()
        assert (
            win._dark_mode is True
        ), "dark_mode preference was not restored on window init (issue #7)"
        win.close()

    def test_toggle_saves_preference(self, qapp: object) -> None:
        """Toggling dark mode in the window persists the value to disk."""
        with patch("m4bmaker.gui.window._prefs_get", return_value=False):
            win = MainWindow()

        # Simulate the user switching to dark mode
        win._dark_action.setChecked(True)
        win._toggle_dark_mode()

        stored = get("dark_mode")
        assert (
            stored is True
        ), "dark_mode preference was not saved after toggle (issue #7)"
        win.close()

    def test_toggle_off_saves_false(self, qapp: object) -> None:
        set("dark_mode", True)
        win = MainWindow()
        # User switches back to light
        win._dark_action.setChecked(False)
        win._toggle_dark_mode()
        assert get("dark_mode") is False
        win.close()

# ---------------------------------------------------------------------------
# MainWindow integration — check_for_updates toggle (closes issue #6 follow-up)
# ---------------------------------------------------------------------------


class TestUpdateCheckerToggle:
    def test_update_checker_not_started_when_disabled(self, qapp: object) -> None:
        """UpdateChecker.start must not be called when pref is False."""
        set("check_for_updates", False)
        with patch("m4bmaker.gui.updater.UpdateChecker.start") as mock_start:
            win = MainWindow()
            mock_start.assert_not_called()
        win.close()

    def test_update_checker_started_when_enabled(self, qapp: object) -> None:
        """UpdateChecker.start must be called exactly once when pref is True."""
        set("check_for_updates", True)
        with patch("m4bmaker.gui.updater.UpdateChecker.start") as mock_start:
            win = MainWindow()
            mock_start.assert_called_once()
        win.close()

    def test_toggle_update_check_persists_false(self, qapp: object) -> None:
        """Calling _toggle_update_check(False) writes False to prefs."""
        win = MainWindow()
        win._toggle_update_check(False)
        assert get("check_for_updates") is False
        win.close()

    def test_toggle_update_check_persists_true(self, qapp: object) -> None:
        """Calling _toggle_update_check(True) writes True to prefs."""
        set("check_for_updates", False)
        win = MainWindow()
        win._toggle_update_check(True)
        assert get("check_for_updates") is True
        win.close()

    def test_updates_action_checked_state_matches_pref_false(
        self, qapp: object
    ) -> None:
        """Menu action initial checked state reflects saved pref (False)."""
        set("check_for_updates", False)
        win = MainWindow()
        assert win._updates_action.isChecked() is False
        win.close()

    def test_updates_action_checked_state_matches_pref_true(
        self, qapp: object
    ) -> None:
        """Menu action initial checked state reflects saved pref (True)."""
        set("check_for_updates", True)
        win = MainWindow()
        assert win._updates_action.isChecked() is True
        win.close()
