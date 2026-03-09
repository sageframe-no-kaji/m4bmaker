"""Shared pytest fixtures for GUI tests.

Sets QT_QPA_PLATFORM=offscreen before any Qt import so the test
suite can run headlessly in CI with no display.
"""

from __future__ import annotations

import os
import sys

import pytest

# Must be set before the first QApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication shared across all GUI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
    # Do NOT call app.quit() — pytest-qt style; let the process clean up.
