"""Phase 6D — tests for app.py entry point and styles.py stylesheet."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_stylesheet_is_nonempty_string():
    """Covers m4bmaker/gui/styles.py: STYLESHEET constant."""
    from m4bmaker.gui.styles import STYLESHEET  # noqa: E402

    assert isinstance(STYLESHEET, str)
    assert "background-color" in STYLESHEET


def test_main_creates_app_window_and_exits():
    """Covers m4bmaker/gui/app.py: main() function body."""
    with (
        patch("m4bmaker.gui.app.QApplication") as MockQApp,
        patch("m4bmaker.gui.app.MainWindow") as MockWindow,
        patch("m4bmaker.gui.app.sys.exit") as mock_exit,
    ):
        MockQApp.return_value.exec.return_value = 0

        from m4bmaker.gui.app import main  # noqa: E402

        main()

    MockQApp.return_value.setApplicationName.assert_called_once_with("m4bmaker")
    MockQApp.return_value.setStyleSheet.assert_called_once()
    MockWindow.return_value.show.assert_called_once()
    mock_exit.assert_called_once_with(0)
